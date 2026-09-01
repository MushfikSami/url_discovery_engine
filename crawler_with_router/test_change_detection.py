"""
test_change_detection.py
========================

Rigorous tests for the incremental-crawl change-detection layer, so a refresh
run over 140k+ rows only rewrites URLs whose content actually changed.

Proves:
  1. Hashing is stable and change-sensitive.
  2. conditional_headers only fires for known-static pages (never JS-heavy /
     unknown -> no 304 that would wrongly skip a JS page).
  3. classify_decision: static + identical raw HTML  -> skip parse+write.
  4. write_decision: identical markdown            -> skip write.
  5. New URL / changed content                     -> update.
  6. DB layer: ensure_hash_columns is idempotent; upsert/record round-trip;
     a "static unchanged" refresh does NOT touch raw_markdown or
     content_updated_at, but DOES bump last_checked.
  7. The backfill migration seeds content_hash without touching content.

Safety: DB tests use throwaway tables (`*_test_<pid>`); production `crawled_data`
is never read or written. No network or browser is used.

Run:  python test_change_detection.py
"""

import os
import time
import unittest

import psycopg2

import change_detection as cd
import migrate_add_content_hash as mig
from db_setup import DB_CONFIG


def db_available():
    try:
        psycopg2.connect(**DB_CONFIG).close()
        return True
    except Exception:
        return False


DB_UP = db_available()

HTML_A = "<html><body><h1>Notice 12</h1><p>original body</p></body></html>"
HTML_A_DUP = "<html><body><h1>Notice 12</h1><p>original body</p></body></html>"
HTML_B = "<html><body><h1>Notice 12</h1><p>UPDATED body</p></body></html>"


# ==============================================================================
# PURE LOGIC
# ==============================================================================
class TestPure(unittest.TestCase):
    def test_hash_stable_and_sensitive(self):
        self.assertEqual(cd.sha256_text(HTML_A), cd.sha256_text(HTML_A_DUP))
        self.assertNotEqual(cd.sha256_text(HTML_A), cd.sha256_text(HTML_B))

    def test_hash_none_is_empty(self):
        self.assertEqual(cd.sha256_text(None), cd.sha256_text(""))

    def test_hashes_match_requires_both(self):
        self.assertTrue(cd.hashes_match("x", "x"))
        self.assertFalse(cd.hashes_match("x", "y"))
        self.assertFalse(cd.hashes_match("x", None))   # first sighting -> not a match
        self.assertFalse(cd.hashes_match(None, "x"))
        self.assertFalse(cd.hashes_match(None, None))

    def test_conditional_headers_static_only(self):
        static = {"is_js_heavy": False, "http_etag": 'W/"abc"', "http_last_modified": "Mon"}
        self.assertEqual(
            cd.conditional_headers(static),
            {"If-None-Match": 'W/"abc"', "If-Modified-Since": "Mon"},
        )
        # JS-heavy -> no conditional (must fetch a body to re-render)
        self.assertEqual(cd.conditional_headers({**static, "is_js_heavy": True}), {})
        # unknown classification -> no conditional (must fetch to classify)
        self.assertEqual(cd.conditional_headers({**static, "is_js_heavy": None}), {})
        # no stored row -> no conditional
        self.assertEqual(cd.conditional_headers(None), {})

    def test_classify_decision(self):
        h = cd.sha256_text(HTML_A)
        stored_static = {"is_js_heavy": False, "source_hash": h, "content_hash": "m"}
        # static + identical raw HTML -> skip
        self.assertEqual(cd.classify_decision(False, h, stored_static), "skip_unchanged")
        # static + different raw HTML -> parse
        self.assertEqual(cd.classify_decision(False, cd.sha256_text(HTML_B), stored_static), "parse")
        # JS-heavy never short-circuits on raw HTML
        self.assertEqual(cd.classify_decision(True, h, stored_static), "parse")
        # no stored -> parse
        self.assertEqual(cd.classify_decision(False, h, None), "parse")

    def test_write_decision(self):
        stored = {"content_hash": cd.sha256_text("MD")}
        self.assertEqual(cd.write_decision(cd.sha256_text("MD"), stored), "skip_unchanged")
        self.assertEqual(cd.write_decision(cd.sha256_text("DIFFERENT"), stored), "update")
        self.assertEqual(cd.write_decision(cd.sha256_text("MD"), None), "update")  # new row


# ==============================================================================
# DB LAYER
# ==============================================================================
@unittest.skipUnless(DB_UP, "PostgreSQL not reachable; skipping DB tests")
class TestDB(unittest.TestCase):
    def setUp(self):
        self.table = f"crawled_data_cdtest_{os.getpid()}"
        self.conn = psycopg2.connect(**DB_CONFIG)
        with self.conn.cursor() as cur:
            cur.execute(f"DROP TABLE IF EXISTS {self.table};")
            cur.execute(
                f"CREATE TABLE {self.table} "
                f"(url TEXT PRIMARY KEY, raw_markdown TEXT, snippet TEXT, keywords TEXT[]);"
            )
        self.conn.commit()
        cd.ensure_hash_columns(self.conn, self.table)
        self.url = "https://x.gov.bd/notice/12"

    def tearDown(self):
        self.conn.rollback()
        with self.conn.cursor() as cur:
            cur.execute(f"DROP TABLE IF EXISTS {self.table};")
        self.conn.commit()
        self.conn.close()

    def _row(self):
        with self.conn.cursor() as cur:
            cur.execute(
                f"SELECT raw_markdown, content_hash, source_hash, http_etag, "
                f"is_js_heavy, last_checked, content_updated_at "
                f"FROM {self.table} WHERE url=%s;", (self.url,))
            return cur.fetchone()

    def test_ensure_columns_idempotent(self):
        cd.ensure_hash_columns(self.conn, self.table)  # second call must not error
        with self.conn.cursor() as cur:
            cur.execute(
                "SELECT column_name FROM information_schema.columns WHERE table_name=%s;",
                (self.table,))
            cols = {r[0] for r in cur.fetchall()}
        for c in cd.HASH_COLUMNS:
            self.assertIn(c, cols)

    def test_get_row_state_none_for_missing(self):
        self.assertIsNone(cd.get_row_state(self.conn, "https://nope", self.table))

    def test_upsert_then_state_roundtrip(self):
        cd.upsert_content(self.conn, self.url, "MARKDOWN", "snip", ["k"],
                          source_hash="SRC", etag='W/"1"', last_modified="Mon",
                          is_js_heavy=False, table=self.table)
        st = cd.get_row_state(self.conn, self.url, self.table)
        self.assertEqual(st["content_hash"], cd.sha256_text("MARKDOWN"))
        self.assertEqual(st["source_hash"], "SRC")
        self.assertEqual(st["http_etag"], 'W/"1"')
        self.assertIs(st["is_js_heavy"], False)

    def test_record_unchanged_preserves_content(self):
        cd.upsert_content(self.conn, self.url, "MARKDOWN", "snip", ["k"],
                          "SRC", 'W/"1"', "Mon", False, self.table)
        before = self._row()
        time.sleep(0.01)
        cd.record_unchanged(self.conn, self.url, "SRC2", 'W/"2"', "Tue", False, self.table)
        after = self._row()
        # raw_markdown + content_hash + content_updated_at unchanged...
        self.assertEqual(after[0], before[0])              # raw_markdown
        self.assertEqual(after[1], before[1])              # content_hash
        self.assertEqual(after[6], before[6])              # content_updated_at
        # ...but validators refreshed and last_checked advanced.
        self.assertEqual(after[2], "SRC2")                 # source_hash
        self.assertEqual(after[3], 'W/"2"')                # http_etag
        self.assertGreater(after[5], before[5])            # last_checked bumped

    def test_changed_content_updates_hash_and_timestamp(self):
        cd.upsert_content(self.conn, self.url, "V1", "s", ["k"], "S1", None, None, False, self.table)
        first = self._row()
        time.sleep(0.01)
        cd.upsert_content(self.conn, self.url, "V2", "s", ["k"], "S2", None, None, False, self.table)
        second = self._row()
        self.assertEqual(second[0], "V2")
        self.assertEqual(second[1], cd.sha256_text("V2"))
        self.assertNotEqual(second[1], first[1])
        self.assertGreater(second[6], first[6])            # content_updated_at bumped

    def test_touch_last_checked_only(self):
        cd.upsert_content(self.conn, self.url, "V1", "s", ["k"], "S1", None, None, False, self.table)
        before = self._row()
        time.sleep(0.01)
        cd.touch_last_checked(self.conn, self.url, self.table)
        after = self._row()
        self.assertEqual(after[0], before[0])              # content untouched
        self.assertGreater(after[5], before[5])            # last_checked bumped


# ==============================================================================
# BACKFILL MIGRATION
# ==============================================================================
@unittest.skipUnless(DB_UP, "PostgreSQL not reachable; skipping DB tests")
class TestBackfill(unittest.TestCase):
    def setUp(self):
        self.table = f"crawled_data_bftest_{os.getpid()}"
        self.conn = psycopg2.connect(**DB_CONFIG)
        with self.conn.cursor() as cur:
            cur.execute(f"DROP TABLE IF EXISTS {self.table};")
            cur.execute(
                f"CREATE TABLE {self.table} "
                f"(url TEXT PRIMARY KEY, raw_markdown TEXT, snippet TEXT, keywords TEXT[]);"
            )
            cur.execute(
                f"INSERT INTO {self.table} (url, raw_markdown) VALUES "
                f"('u1','hello world'),('u2','other content'),('u3',NULL);"
            )
        self.conn.commit()
        cd.ensure_hash_columns(self.conn, self.table)

    def tearDown(self):
        self.conn.rollback()
        with self.conn.cursor() as cur:
            cur.execute(f"DROP TABLE IF EXISTS {self.table};")
        self.conn.commit()
        self.conn.close()

    def test_count_missing(self):
        # u1, u2 have markdown+no hash; u3 has NULL markdown (excluded)
        self.assertEqual(mig.count_missing(self.conn, self.table), 2)

    def test_backfill_sets_correct_hashes_only(self):
        # Reproduce the migration's backfill against the throwaway table.
        with self.conn.cursor() as cur:
            cur.execute(
                f"SELECT url, raw_markdown FROM {self.table} "
                f"WHERE content_hash IS NULL AND raw_markdown IS NOT NULL;")
            rows = cur.fetchall()
        batch = [(cd.sha256_text(md), url) for url, md in rows]
        mig._flush(self.conn, self.table, batch)

        with self.conn.cursor() as cur:
            cur.execute(f"SELECT url, raw_markdown, content_hash FROM {self.table} ORDER BY url;")
            got = cur.fetchall()
        by_url = {r[0]: r for r in got}
        self.assertEqual(by_url["u1"][2], cd.sha256_text("hello world"))
        self.assertEqual(by_url["u2"][2], cd.sha256_text("other content"))
        self.assertIsNone(by_url["u3"][2])                 # NULL markdown -> still no hash
        # content itself untouched
        self.assertEqual(by_url["u1"][1], "hello world")
        self.assertEqual(mig.count_missing(self.conn, self.table), 0)  # nothing left


if __name__ == "__main__":
    unittest.main(verbosity=2)
