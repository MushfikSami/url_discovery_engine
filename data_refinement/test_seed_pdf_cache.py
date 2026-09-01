"""
test_seed_pdf_cache.py
======================

Tests for the seed-then-run incremental OCR approach:
  * parse_pdf_blocks correctly recovers (pdf_url, text) from OCR markdown.
  * seed() populates pdf_ocr_cache from crawled_data_ocr (idempotent).
  * the fleet's URL-presence gate: is_url_cached + URL_SKIP_MODE cause a
    seeded PDF URL to be skipped (no OCR), while a NEW PDF URL is OCR'd.

DB tests use throwaway tables; production is untouched. No network/GPU.
Run:  python test_seed_pdf_cache.py
"""

import asyncio
import os
import unittest

import psycopg2

import hash_aware_ocr_fleet as fleet
import seed_pdf_cache_from_existing as seeder


def db_available():
    try:
        psycopg2.connect(**fleet.DB_CONFIG).close()
        return True
    except Exception:
        return False


DB_UP = db_available()

PDF_A = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"

OCR_MD = (
    "### [OCR EXTRACTED FROM ATTACHED PDF] ###\n"
    "Document Source: https://store/a.pdf\n"
    "--- Page 1 ---\nText of A page one\n"
    "Document Source: https://store/b.pdf\n"
    "--- Page 1 ---\nText of B\n"
)


# ==============================================================================
# PURE PARSER
# ==============================================================================
class TestParse(unittest.TestCase):
    def test_parse_two_pdfs(self):
        blocks = seeder.parse_pdf_blocks(OCR_MD)
        self.assertEqual([u for u, _ in blocks],
                         ["https://store/a.pdf", "https://store/b.pdf"])
        self.assertIn("Text of A page one", blocks[0][1])
        self.assertIn("Text of B", blocks[1][1])
        # first PDF's text must NOT bleed into the second
        self.assertNotIn("Text of B", blocks[0][1])

    def test_parse_empty_and_none(self):
        self.assertEqual(seeder.parse_pdf_blocks(""), [])
        self.assertEqual(seeder.parse_pdf_blocks(None), [])
        self.assertEqual(seeder.parse_pdf_blocks("no markers here"), [])

    def test_parse_single(self):
        md = "Document Source: https://x/only.pdf\nsome text"
        blocks = seeder.parse_pdf_blocks(md)
        self.assertEqual(blocks, [("https://x/only.pdf", "some text")])


# ==============================================================================
# SEED + URL-SKIP (DB)
# ==============================================================================
@unittest.skipUnless(DB_UP, "PostgreSQL not reachable; skipping DB tests")
class TestSeedAndSkip(unittest.TestCase):
    def setUp(self):
        pid = os.getpid()
        self.cache = f"pdf_ocr_cache_seedtest_{pid}"
        self.ocr = f"crawled_data_ocr_seedtest_{pid}"
        self.crawled = f"crawled_data_seedtest_{pid}"
        self.conn = psycopg2.connect(**fleet.DB_CONFIG)
        with self.conn.cursor() as cur:
            for t in (self.cache, self.ocr, self.crawled):
                cur.execute(f"DROP TABLE IF EXISTS {t};")
            cur.execute(f"CREATE TABLE {self.crawled} (url TEXT PRIMARY KEY, raw_markdown TEXT);")
        self.conn.commit()
        fleet.ensure_cache_table(self.conn, self.cache)
        fleet.ensure_ocr_table(self.conn, self.ocr)

        self._oc, self._oo, self._ot = fleet.CACHE_TABLE, fleet.CRAWLED_TABLE, fleet.OCR_TABLE
        fleet.CACHE_TABLE, fleet.CRAWLED_TABLE, fleet.OCR_TABLE = self.cache, self.crawled, self.ocr

        self.page = "https://gov.bd/page1"
        with self.conn.cursor() as cur:
            cur.execute(f"INSERT INTO {self.crawled}(url,raw_markdown) VALUES(%s,%s);",
                        (self.page, "base"))
            cur.execute(f"INSERT INTO {self.ocr}(url,ocr_markdown) VALUES(%s,%s);",
                        (self.page, OCR_MD))
        self.conn.commit()

        self.ocr_calls = 0

        async def stub_ocr(b):
            self.ocr_calls += 1
            return "FRESH_OCR"
        self.stub_ocr = stub_ocr

    def tearDown(self):
        fleet.CACHE_TABLE, fleet.CRAWLED_TABLE, fleet.OCR_TABLE = self._oc, self._oo, self._ot
        self.conn.rollback()
        with self.conn.cursor() as cur:
            for t in (self.cache, self.ocr, self.crawled):
                cur.execute(f"DROP TABLE IF EXISTS {t};")
        self.conn.commit()
        self.conn.close()

    def test_seed_populates_cache(self):
        pages, seeded = seeder.seed(self.conn, dry_run=False,
                                    ocr_table=self.ocr, cache_table=self.cache)
        self.assertEqual(seeded, 2)
        self.assertTrue(fleet.is_url_cached(self.conn, "https://store/a.pdf", self.cache))
        self.assertTrue(fleet.is_url_cached(self.conn, "https://store/b.pdf", self.cache))
        self.assertFalse(fleet.is_url_cached(self.conn, "https://store/NEW.pdf", self.cache))

    def test_seed_dry_run_writes_nothing(self):
        pages, seeded = seeder.seed(self.conn, dry_run=True,
                                    ocr_table=self.ocr, cache_table=self.cache)
        self.assertEqual(seeded, 2)
        self.assertFalse(fleet.is_url_cached(self.conn, "https://store/a.pdf", self.cache))

    def test_seed_idempotent(self):
        seeder.seed(self.conn, False, self.ocr, self.cache)
        seeder.seed(self.conn, False, self.ocr, self.cache)  # second run must not error/dupe
        with self.conn.cursor() as cur:
            cur.execute(f"SELECT count(*) FROM {self.cache};")
            self.assertEqual(cur.fetchone()[0], 2)

    def test_seeded_url_is_skipped_new_url_is_ocred(self):
        seeder.seed(self.conn, False, self.ocr, self.cache)
        # A seeded (already-done) PDF must NOT be OCR'd again.
        self.assertTrue(fleet.is_url_cached(self.conn, "https://store/a.pdf", self.cache))
        # A brand-new PDF url runs through handle_pdf -> OCR happens once.
        action = asyncio.run(fleet.handle_pdf(
            self.conn, self.page, "https://store/NEW.pdf", PDF_A, self.stub_ocr))
        self.assertEqual(action, "ocr")
        self.assertEqual(self.ocr_calls, 1)
        # ...and the new PDF is now cached with a REAL hash (not the seed sentinel).
        cached = fleet.get_cache_entry(self.conn, "https://store/NEW.pdf", self.cache)
        self.assertIsNotNone(cached)
        self.assertNotEqual(cached[0], seeder.SEED_HASH)


if __name__ == "__main__":
    unittest.main(verbosity=2)
