"""
test_hash_aware_ocr.py
======================

Rigorous test suite for hash_aware_ocr_fleet.py.

Goals
-----
Prove, before it runs against 140k+ production rows, that:
  1. Hash detection is correct (same bytes -> same hash; 1 byte flip -> new hash).
  2. An unchanged PDF is NEVER sent to OCR on restart.
  3. A changed PDF IS re-OCR'd and its block in `crawled_data_ocr` is REPLACED,
     not duplicated.
  4. A new PDF is OCR'd once and cached.
  5. "Reheal": if the hash is unchanged but the OCR block was lost, the
     cached text is restored WITHOUT calling OCR.
  6. Invalid/oversize/non-PDF payloads are rejected before any OCR.
  7. Empty OCR output still records the hash (no infinite re-OCR loop).
  8. `crawled_data.raw_markdown` (the base HTML content) is NEVER touched by
     any of this -- OCR text only ever lands in `crawled_data_ocr`.
  9. `split_markdown_ocr` correctly separates legacy-mixed rows, and the
     one-time migration script applies that split idempotently.

Safety
------
The DB tests run against throwaway tables (`*_test_<pid>`) that are created and
dropped inside each test. Production `crawled_data` / `pdf_ocr_cache` /
`crawled_data_ocr` are never read or written. OCR is replaced by a counting
stub, so no GPU or vLLM server is required. If Postgres is unreachable the DB
tests self-skip; the pure-logic tests always run.

Run:  python test_hash_aware_ocr.py
"""

import asyncio
import os
import unittest

import psycopg2

import hash_aware_ocr_fleet as fleet
import migrate_split_ocr_table as migrator


# ---- minimal, valid PDF byte payloads for testing -----------------------------
PDF_A = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"
PDF_A_DUP = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"  # identical to A
PDF_B = b"%PDF-1.4\n1 0 obj<< /changed 1 >>endobj\ntrailer<<>>\n%%EOF\n"  # different
NOT_A_PDF = b"<html>this is not a pdf</html>"


def db_available():
    try:
        c = psycopg2.connect(**fleet.DB_CONFIG)
        c.close()
        return True
    except Exception:
        return False


DB_UP = db_available()


# ==============================================================================
# PURE LOGIC (no DB, no OCR) -- always runs
# ==============================================================================
class TestPureHelpers(unittest.TestCase):
    def test_hash_deterministic(self):
        self.assertEqual(fleet.compute_pdf_hash(PDF_A), fleet.compute_pdf_hash(PDF_A_DUP))

    def test_hash_sensitive_to_change(self):
        self.assertNotEqual(fleet.compute_pdf_hash(PDF_A), fleet.compute_pdf_hash(PDF_B))

    def test_hash_single_byte_flip(self):
        flipped = bytearray(PDF_A)
        flipped[-2] ^= 0x01
        self.assertNotEqual(fleet.compute_pdf_hash(PDF_A), fleet.compute_pdf_hash(bytes(flipped)))

    def test_is_valid_pdf(self):
        self.assertTrue(fleet.is_valid_pdf(PDF_A))
        self.assertTrue(fleet.is_valid_pdf(b"   \n%PDF-1.7 stuff"))  # leading whitespace ok
        self.assertFalse(fleet.is_valid_pdf(NOT_A_PDF))
        self.assertFalse(fleet.is_valid_pdf(b""))
        self.assertFalse(fleet.is_valid_pdf(b"%PDF" + b"x" * (fleet.MAX_PDF_BYTES + 1)))

    def test_decide_action(self):
        h = "abc"
        # new PDF
        self.assertEqual(fleet.decide_action(None, h, False), "ocr")
        # changed
        self.assertEqual(fleet.decide_action("old", h, True), "ocr")
        # unchanged + block present
        self.assertEqual(fleet.decide_action(h, h, True), "skip")
        # unchanged + block missing -> reheal
        self.assertEqual(fleet.decide_action(h, h, False), "reheal")

    def test_replace_ocr_block_insert(self):
        md = "existing content"
        block = fleet.build_ocr_block("http://x/a.pdf", "HELLO")
        out = fleet.replace_ocr_block(md, "http://x/a.pdf", block)
        self.assertIn("existing content", out)
        self.assertIn("HELLO", out)
        self.assertTrue(fleet.block_present(out, "http://x/a.pdf"))

    def test_replace_ocr_block_idempotent(self):
        """Re-applying must REPLACE, not duplicate."""
        md = "base"
        b1 = fleet.build_ocr_block("http://x/a.pdf", "TEXT_V1")
        once = fleet.replace_ocr_block(md, "http://x/a.pdf", b1)
        # same block applied again
        twice = fleet.replace_ocr_block(once, "http://x/a.pdf", b1)
        self.assertEqual(once, twice)
        self.assertEqual(twice.count("TEXT_V1"), 1)

    def test_replace_ocr_block_updates_content(self):
        md = "base"
        b1 = fleet.build_ocr_block("http://x/a.pdf", "TEXT_V1")
        step1 = fleet.replace_ocr_block(md, "http://x/a.pdf", b1)
        b2 = fleet.build_ocr_block("http://x/a.pdf", "TEXT_V2")
        step2 = fleet.replace_ocr_block(step1, "http://x/a.pdf", b2)
        self.assertNotIn("TEXT_V1", step2)
        self.assertIn("TEXT_V2", step2)
        self.assertEqual(step2.count("TEXT_V2"), 1)

    def test_replace_ocr_block_multiple_pdfs_isolated(self):
        """Replacing one PDF's block must not disturb another PDF's block."""
        md = "base"
        md = fleet.replace_ocr_block(md, "http://x/a.pdf", fleet.build_ocr_block("http://x/a.pdf", "AAA"))
        md = fleet.replace_ocr_block(md, "http://x/b.pdf", fleet.build_ocr_block("http://x/b.pdf", "BBB"))
        md = fleet.replace_ocr_block(md, "http://x/a.pdf", fleet.build_ocr_block("http://x/a.pdf", "AAA2"))
        self.assertIn("BBB", md)
        self.assertIn("AAA2", md)
        self.assertNotIn("AAA\n", md)  # old A text gone
        self.assertEqual(md.count("BBB"), 1)

    def test_split_markdown_ocr_no_marker(self):
        base, ocr = fleet.split_markdown_ocr("just html content, no OCR here")
        self.assertEqual(base, "just html content, no OCR here")
        self.assertIsNone(ocr)

    def test_split_markdown_ocr_none_input(self):
        base, ocr = fleet.split_markdown_ocr(None)
        self.assertIsNone(base)
        self.assertIsNone(ocr)

    def test_split_markdown_ocr_legacy_tag(self):
        mixed = (
            "original html markdown\n\n"
            f"\n\n{fleet.OCR_HUMAN_TAG}\nDocument Source: http://x/a.pdf\nEXTRACTED TEXT\n"
        )
        base, ocr = fleet.split_markdown_ocr(mixed)
        self.assertEqual(base, "original html markdown")
        self.assertIn(fleet.OCR_HUMAN_TAG, ocr)
        self.assertIn("EXTRACTED TEXT", ocr)
        self.assertNotIn("EXTRACTED TEXT", base)

    def test_split_markdown_ocr_hash_aware_markers(self):
        block = fleet.build_ocr_block("http://x/a.pdf", "TEXT_V1")
        mixed = "original html markdown" + block
        base, ocr = fleet.split_markdown_ocr(mixed)
        self.assertEqual(base, "original html markdown")
        self.assertIn("TEXT_V1", ocr)
        self.assertTrue(fleet.block_present(ocr, "http://x/a.pdf"))

    def test_split_markdown_ocr_multiple_legacy_appends(self):
        """Two concatenated legacy appends (from repeated sweep runs) must all
        end up on the OCR side of the split, not just the first."""
        mixed = (
            "original html markdown"
            f"\n\n{fleet.OCR_HUMAN_TAG}\nDocument Source: http://x/a.pdf\nTEXT_A\n"
            f"\n\n{fleet.OCR_HUMAN_TAG}\nDocument Source: http://x/b.pdf\nTEXT_B\n"
        )
        base, ocr = fleet.split_markdown_ocr(mixed)
        self.assertEqual(base, "original html markdown")
        self.assertIn("TEXT_A", ocr)
        self.assertIn("TEXT_B", ocr)


# ==============================================================================
# DB + async orchestration -- uses throwaway tables, stub OCR
# ==============================================================================
@unittest.skipUnless(DB_UP, "PostgreSQL not reachable; skipping DB integration tests")
class TestHandlePdfDB(unittest.TestCase):
    def setUp(self):
        pid = os.getpid()
        self.cache_table = f"pdf_ocr_cache_test_{pid}"
        self.crawled_table = f"crawled_data_test_{pid}"
        self.ocr_table = f"crawled_data_ocr_test_{pid}"
        self.conn = psycopg2.connect(**fleet.DB_CONFIG)
        with self.conn.cursor() as cur:
            cur.execute(f"DROP TABLE IF EXISTS {self.cache_table};")
            cur.execute(f"DROP TABLE IF EXISTS {self.ocr_table};")
            cur.execute(f"DROP TABLE IF EXISTS {self.crawled_table};")
            cur.execute(
                f"CREATE TABLE {self.crawled_table} "
                f"(url TEXT PRIMARY KEY, raw_markdown TEXT, snippet TEXT, keywords TEXT[]);"
            )
        self.conn.commit()
        fleet.ensure_cache_table(self.conn, self.cache_table)
        fleet.ensure_ocr_table(self.conn, self.ocr_table)

        # Patch module-level table names so the DB helpers target test tables.
        self._orig_cache = fleet.CACHE_TABLE
        self._orig_crawled = fleet.CRAWLED_TABLE
        self._orig_ocr = fleet.OCR_TABLE
        fleet.CACHE_TABLE = self.cache_table
        fleet.CRAWLED_TABLE = self.crawled_table
        fleet.OCR_TABLE = self.ocr_table

        self.page_url = "http://gov.bd/page1"
        self.pdf_url = "http://gov.bd/doc.pdf"
        self.base_markdown = "original page markdown"
        with self.conn.cursor() as cur:
            cur.execute(
                f"INSERT INTO {self.crawled_table} (url, raw_markdown) VALUES (%s, %s);",
                (self.page_url, self.base_markdown),
            )
        self.conn.commit()

        # Counting OCR stub -- records how many times OCR actually ran.
        self.ocr_calls = 0

        async def stub_ocr(pdf_bytes):
            self.ocr_calls += 1
            # Return content that varies with the bytes so we can assert freshness.
            return f"OCR_OF_{fleet.compute_pdf_hash(pdf_bytes)[:8]}"

        self.stub_ocr = stub_ocr

    def tearDown(self):
        fleet.CACHE_TABLE = self._orig_cache
        fleet.CRAWLED_TABLE = self._orig_crawled
        fleet.OCR_TABLE = self._orig_ocr
        # A mid-test failure can leave the connection in an aborted transaction;
        # roll back first so the DROPs below always succeed (no leaked tables).
        self.conn.rollback()
        with self.conn.cursor() as cur:
            cur.execute(f"DROP TABLE IF EXISTS {self.cache_table};")
            cur.execute(f"DROP TABLE IF EXISTS {self.ocr_table};")
            cur.execute(f"DROP TABLE IF EXISTS {self.crawled_table};")
        self.conn.commit()
        self.conn.close()

    def _run(self, coro):
        return asyncio.run(coro)

    def _base_markdown(self):
        return fleet.get_markdown(self.conn, self.page_url, self.crawled_table)

    def _ocr_markdown(self):
        return fleet.get_ocr_markdown(self.conn, self.page_url, self.ocr_table)

    def test_new_pdf_is_ocred_and_cached(self):
        action = self._run(fleet.handle_pdf(self.conn, self.page_url, self.pdf_url, PDF_A, self.stub_ocr))
        self.assertEqual(action, "ocr")
        self.assertEqual(self.ocr_calls, 1)
        cached = fleet.get_cache_entry(self.conn, self.pdf_url, self.cache_table)
        self.assertIsNotNone(cached)
        self.assertEqual(cached[0], fleet.compute_pdf_hash(PDF_A))
        self.assertIn("OCR_OF_", self._ocr_markdown())

    def test_base_markdown_never_touched_by_ocr(self):
        """crawled_data.raw_markdown must stay exactly what the crawler wrote --
        OCR only ever writes to crawled_data_ocr."""
        self._run(fleet.handle_pdf(self.conn, self.page_url, self.pdf_url, PDF_A, self.stub_ocr))
        self._run(fleet.handle_pdf(self.conn, self.page_url, self.pdf_url, PDF_B, self.stub_ocr))
        self.assertEqual(self._base_markdown(), self.base_markdown)

    def test_unchanged_pdf_skips_ocr_on_restart(self):
        # First run OCRs.
        self._run(fleet.handle_pdf(self.conn, self.page_url, self.pdf_url, PDF_A, self.stub_ocr))
        self.assertEqual(self.ocr_calls, 1)
        ocr_after_first = self._ocr_markdown()
        # Second run with identical bytes: MUST skip.
        action = self._run(fleet.handle_pdf(self.conn, self.page_url, self.pdf_url, PDF_A_DUP, self.stub_ocr))
        self.assertEqual(action, "skip")
        self.assertEqual(self.ocr_calls, 1, "OCR must NOT run for an unchanged PDF")
        # OCR content unchanged (no duplication).
        self.assertEqual(self._ocr_markdown(), ocr_after_first)

    def test_changed_pdf_reocrs_and_replaces_block(self):
        self._run(fleet.handle_pdf(self.conn, self.page_url, self.pdf_url, PDF_A, self.stub_ocr))
        old_text_marker = f"OCR_OF_{fleet.compute_pdf_hash(PDF_A)[:8]}"
        self.assertIn(old_text_marker, self._ocr_markdown())
        # Now the PDF content changes.
        action = self._run(fleet.handle_pdf(self.conn, self.page_url, self.pdf_url, PDF_B, self.stub_ocr))
        self.assertEqual(action, "ocr")
        self.assertEqual(self.ocr_calls, 2, "Changed PDF must be re-OCR'd")
        md = self._ocr_markdown()
        new_text_marker = f"OCR_OF_{fleet.compute_pdf_hash(PDF_B)[:8]}"
        self.assertIn(new_text_marker, md)
        self.assertNotIn(old_text_marker, md, "Stale OCR block must be removed")
        self.assertEqual(md.count("OCR-PDF-START"), 1, "No duplicate blocks")
        # Cache updated to new hash.
        cached = fleet.get_cache_entry(self.conn, self.pdf_url, self.cache_table)
        self.assertEqual(cached[0], fleet.compute_pdf_hash(PDF_B))

    def test_reheal_restores_block_without_ocr(self):
        self._run(fleet.handle_pdf(self.conn, self.page_url, self.pdf_url, PDF_A, self.stub_ocr))
        self.assertEqual(self.ocr_calls, 1)
        # Simulate the crawled_data_ocr row being lost/reset while the hash
        # cache stays intact (e.g. manual cleanup, partial restore).
        fleet.set_ocr_markdown(self.conn, self.page_url, "", self.ocr_table)
        self.assertFalse(fleet.block_present(self._ocr_markdown(), self.pdf_url))
        # Same bytes again -> hash matches -> reheal (restore cached text, no OCR).
        action = self._run(fleet.handle_pdf(self.conn, self.page_url, self.pdf_url, PDF_A, self.stub_ocr))
        self.assertEqual(action, "reheal")
        self.assertEqual(self.ocr_calls, 1, "Reheal must NOT call OCR")
        self.assertTrue(fleet.block_present(self._ocr_markdown(), self.pdf_url))
        self.assertIn(f"OCR_OF_{fleet.compute_pdf_hash(PDF_A)[:8]}", self._ocr_markdown())
        # Base markdown was never involved.
        self.assertEqual(self._base_markdown(), self.base_markdown)

    def test_invalid_pdf_rejected(self):
        action = self._run(fleet.handle_pdf(self.conn, self.page_url, self.pdf_url, NOT_A_PDF, self.stub_ocr))
        self.assertEqual(action, "invalid")
        self.assertEqual(self.ocr_calls, 0)
        self.assertIsNone(fleet.get_cache_entry(self.conn, self.pdf_url, self.cache_table))

    def test_empty_ocr_still_records_hash(self):
        async def empty_ocr(pdf_bytes):
            self.ocr_calls += 1
            return "   "

        action = self._run(fleet.handle_pdf(self.conn, self.page_url, self.pdf_url, PDF_A, empty_ocr))
        self.assertEqual(action, "ocr")
        cached = fleet.get_cache_entry(self.conn, self.pdf_url, self.cache_table)
        self.assertIsNotNone(cached, "Hash must be recorded even for empty OCR")
        self.assertEqual(cached[0], fleet.compute_pdf_hash(PDF_A))
        # Restart: identical bytes -> skip, no second OCR of the unreadable PDF.
        action2 = self._run(fleet.handle_pdf(self.conn, self.page_url, self.pdf_url, PDF_A, empty_ocr))
        self.assertEqual(action2, "skip")
        self.assertEqual(self.ocr_calls, 1)

    def test_multiple_pdfs_same_page(self):
        pdf_url2 = "http://gov.bd/doc2.pdf"
        self._run(fleet.handle_pdf(self.conn, self.page_url, self.pdf_url, PDF_A, self.stub_ocr))
        self._run(fleet.handle_pdf(self.conn, self.page_url, pdf_url2, PDF_B, self.stub_ocr))
        md = self._ocr_markdown()
        self.assertTrue(fleet.block_present(md, self.pdf_url))
        self.assertTrue(fleet.block_present(md, pdf_url2))
        self.assertEqual(md.count("OCR-PDF-START"), 2)
        # Re-run first unchanged -> skip, second block untouched.
        action = self._run(fleet.handle_pdf(self.conn, self.page_url, self.pdf_url, PDF_A, self.stub_ocr))
        self.assertEqual(action, "skip")
        self.assertTrue(fleet.block_present(self._ocr_markdown(), pdf_url2))

    def test_apply_ocr_skips_if_page_row_missing(self):
        """If the page row vanished from crawled_data, don't create an orphan
        crawled_data_ocr row."""
        ghost_url = "http://gov.bd/does-not-exist"
        action = self._run(fleet.handle_pdf(self.conn, ghost_url, self.pdf_url, PDF_A, self.stub_ocr))
        self.assertEqual(action, "ocr")  # OCR still runs (new hash)...
        self.assertIsNone(fleet.get_ocr_markdown(self.conn, ghost_url, self.ocr_table))  # ...but nothing written


# ==============================================================================
# Migration: split legacy-mixed raw_markdown into crawled_data_ocr
# ==============================================================================
@unittest.skipUnless(DB_UP, "PostgreSQL not reachable; skipping DB integration tests")
class TestMigration(unittest.TestCase):
    def setUp(self):
        pid = os.getpid()
        self.crawled_table = f"crawled_data_migtest_{pid}"
        self.ocr_table = f"crawled_data_ocr_migtest_{pid}"
        self.conn = psycopg2.connect(**fleet.DB_CONFIG)
        with self.conn.cursor() as cur:
            cur.execute(f"DROP TABLE IF EXISTS {self.ocr_table};")
            cur.execute(f"DROP TABLE IF EXISTS {self.crawled_table};")
            cur.execute(
                f"CREATE TABLE {self.crawled_table} "
                f"(url TEXT PRIMARY KEY, raw_markdown TEXT, snippet TEXT, keywords TEXT[]);"
            )
        self.conn.commit()
        fleet.ensure_ocr_table(self.conn, self.ocr_table)

        self._orig_crawled = fleet.CRAWLED_TABLE
        self._orig_ocr = fleet.OCR_TABLE
        fleet.CRAWLED_TABLE = self.crawled_table
        fleet.OCR_TABLE = self.ocr_table

        self.mixed_url = "http://gov.bd/mixed-page"
        self.clean_url = "http://gov.bd/clean-page"
        self.mixed_markdown = (
            "original html markdown for the page"
            f"\n\n{fleet.OCR_HUMAN_TAG}\nDocument Source: http://x/a.pdf\nEXTRACTED TEXT\n"
        )
        with self.conn.cursor() as cur:
            cur.execute(
                f"INSERT INTO {self.crawled_table} (url, raw_markdown) VALUES (%s, %s), (%s, %s);",
                (self.mixed_url, self.mixed_markdown, self.clean_url, "no ocr here"),
            )
        self.conn.commit()

    def tearDown(self):
        fleet.CRAWLED_TABLE = self._orig_crawled
        fleet.OCR_TABLE = self._orig_ocr
        self.conn.rollback()
        with self.conn.cursor() as cur:
            cur.execute(f"DROP TABLE IF EXISTS {self.ocr_table};")
            cur.execute(f"DROP TABLE IF EXISTS {self.crawled_table};")
        self.conn.commit()
        self.conn.close()

    def test_fetch_migration_candidates_only_returns_mixed_rows(self):
        rows = migrator.fetch_migration_candidates(self.conn, self.crawled_table)
        urls = [r[0] for r in rows]
        self.assertIn(self.mixed_url, urls)
        self.assertNotIn(self.clean_url, urls)

    def test_migrate_row_splits_and_writes_both_tables(self):
        migrator.migrate_row(
            self.conn, self.mixed_url, self.mixed_markdown, dry_run=False,
            crawled_table=self.crawled_table, ocr_table=self.ocr_table,
        )
        base = fleet.get_markdown(self.conn, self.mixed_url, self.crawled_table)
        ocr = fleet.get_ocr_markdown(self.conn, self.mixed_url, self.ocr_table)
        self.assertEqual(base, "original html markdown for the page")
        self.assertIn("EXTRACTED TEXT", ocr)
        self.assertNotIn("EXTRACTED TEXT", base)

    def test_migrate_row_dry_run_writes_nothing(self):
        migrator.migrate_row(
            self.conn, self.mixed_url, self.mixed_markdown, dry_run=True,
            crawled_table=self.crawled_table, ocr_table=self.ocr_table,
        )
        base = fleet.get_markdown(self.conn, self.mixed_url, self.crawled_table)
        ocr = fleet.get_ocr_markdown(self.conn, self.mixed_url, self.ocr_table)
        self.assertEqual(base, self.mixed_markdown, "dry-run must not modify raw_markdown")
        self.assertIsNone(ocr, "dry-run must not write crawled_data_ocr")

    def test_migrate_row_idempotent_on_rerun(self):
        migrator.migrate_row(
            self.conn, self.mixed_url, self.mixed_markdown, dry_run=False,
            crawled_table=self.crawled_table, ocr_table=self.ocr_table,
        )
        base_after_first = fleet.get_markdown(self.conn, self.mixed_url, self.crawled_table)
        # Re-running against the now-clean base (as a real re-run would fetch it)
        # must be a no-op: no OCR marker left to split on.
        result = migrator.migrate_row(
            self.conn, self.mixed_url, base_after_first, dry_run=False,
            crawled_table=self.crawled_table, ocr_table=self.ocr_table,
        )
        self.assertIsNone(result)
        self.assertEqual(
            fleet.get_markdown(self.conn, self.mixed_url, self.crawled_table),
            base_after_first,
        )

    def test_migrate_row_no_marker_is_noop(self):
        result = migrator.migrate_row(
            self.conn, self.clean_url, "no ocr here", dry_run=False,
            crawled_table=self.crawled_table, ocr_table=self.ocr_table,
        )
        self.assertIsNone(result)
        self.assertIsNone(fleet.get_ocr_markdown(self.conn, self.clean_url, self.ocr_table))


if __name__ == "__main__":
    unittest.main(verbosity=2)
