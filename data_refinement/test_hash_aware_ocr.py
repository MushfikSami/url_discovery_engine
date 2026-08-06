"""
test_hash_aware_ocr.py
======================

Rigorous test suite for hash_aware_ocr_fleet.py.

Goals
-----
Prove, before it runs against 140k+ production rows, that:
  1. Hash detection is correct (same bytes -> same hash; 1 byte flip -> new hash).
  2. An unchanged PDF is NEVER sent to OCR on restart.
  3. A changed PDF IS re-OCR'd and its markdown block is REPLACED, not duplicated.
  4. A new PDF is OCR'd once and cached.
  5. "Reheal": if the hash is unchanged but the markdown block was lost, the
     cached text is restored WITHOUT calling OCR.
  6. Invalid/oversize/non-PDF payloads are rejected before any OCR.
  7. Empty OCR output still records the hash (no infinite re-OCR loop).

Safety
------
The DB tests run against throwaway tables (`*_test_<pid>`) that are created and
dropped inside each test. Production `crawled_data` / `pdf_ocr_cache` are never
read or written. OCR is replaced by a counting stub, so no GPU or vLLM server
is required. If Postgres is unreachable the DB tests self-skip; the pure-logic
tests always run.

Run:  python test_hash_aware_ocr.py
"""

import asyncio
import os
import unittest

import psycopg2

import hash_aware_ocr_fleet as fleet


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


# ==============================================================================
# DB + async orchestration -- uses throwaway tables, stub OCR
# ==============================================================================
@unittest.skipUnless(DB_UP, "PostgreSQL not reachable; skipping DB integration tests")
class TestHandlePdfDB(unittest.TestCase):
    def setUp(self):
        pid = os.getpid()
        self.cache_table = f"pdf_ocr_cache_test_{pid}"
        self.crawled_table = f"crawled_data_test_{pid}"
        self.conn = psycopg2.connect(**fleet.DB_CONFIG)
        with self.conn.cursor() as cur:
            cur.execute(f"DROP TABLE IF EXISTS {self.cache_table};")
            cur.execute(f"DROP TABLE IF EXISTS {self.crawled_table};")
            cur.execute(
                f"CREATE TABLE {self.crawled_table} "
                f"(url TEXT PRIMARY KEY, raw_markdown TEXT, snippet TEXT, keywords TEXT[]);"
            )
        self.conn.commit()
        fleet.ensure_cache_table(self.conn, self.cache_table)

        # Patch module-level table names so the DB helpers target test tables.
        self._orig_cache = fleet.CACHE_TABLE
        self._orig_crawled = fleet.CRAWLED_TABLE
        fleet.CACHE_TABLE = self.cache_table
        fleet.CRAWLED_TABLE = self.crawled_table

        self.page_url = "http://gov.bd/page1"
        self.pdf_url = "http://gov.bd/doc.pdf"
        with self.conn.cursor() as cur:
            cur.execute(
                f"INSERT INTO {self.crawled_table} (url, raw_markdown) VALUES (%s, %s);",
                (self.page_url, "original page markdown"),
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
        # A mid-test failure can leave the connection in an aborted transaction;
        # roll back first so the DROPs below always succeed (no leaked tables).
        self.conn.rollback()
        with self.conn.cursor() as cur:
            cur.execute(f"DROP TABLE IF EXISTS {self.cache_table};")
            cur.execute(f"DROP TABLE IF EXISTS {self.crawled_table};")
        self.conn.commit()
        self.conn.close()

    def _run(self, coro):
        return asyncio.run(coro)

    def _markdown(self):
        return fleet.get_markdown(self.conn, self.page_url, self.crawled_table)

    def test_new_pdf_is_ocred_and_cached(self):
        action = self._run(fleet.handle_pdf(self.conn, self.page_url, self.pdf_url, PDF_A, self.stub_ocr))
        self.assertEqual(action, "ocr")
        self.assertEqual(self.ocr_calls, 1)
        cached = fleet.get_cache_entry(self.conn, self.pdf_url, self.cache_table)
        self.assertIsNotNone(cached)
        self.assertEqual(cached[0], fleet.compute_pdf_hash(PDF_A))
        self.assertIn("OCR_OF_", self._markdown())

    def test_unchanged_pdf_skips_ocr_on_restart(self):
        # First run OCRs.
        self._run(fleet.handle_pdf(self.conn, self.page_url, self.pdf_url, PDF_A, self.stub_ocr))
        self.assertEqual(self.ocr_calls, 1)
        md_after_first = self._markdown()
        # Second run with identical bytes: MUST skip.
        action = self._run(fleet.handle_pdf(self.conn, self.page_url, self.pdf_url, PDF_A_DUP, self.stub_ocr))
        self.assertEqual(action, "skip")
        self.assertEqual(self.ocr_calls, 1, "OCR must NOT run for an unchanged PDF")
        # Markdown unchanged (no duplication).
        self.assertEqual(self._markdown(), md_after_first)

    def test_changed_pdf_reocrs_and_replaces_block(self):
        self._run(fleet.handle_pdf(self.conn, self.page_url, self.pdf_url, PDF_A, self.stub_ocr))
        old_text_marker = f"OCR_OF_{fleet.compute_pdf_hash(PDF_A)[:8]}"
        self.assertIn(old_text_marker, self._markdown())
        # Now the PDF content changes.
        action = self._run(fleet.handle_pdf(self.conn, self.page_url, self.pdf_url, PDF_B, self.stub_ocr))
        self.assertEqual(action, "ocr")
        self.assertEqual(self.ocr_calls, 2, "Changed PDF must be re-OCR'd")
        md = self._markdown()
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
        # Simulate the page being re-crawled: markdown reset, cache intact.
        fleet.set_markdown(self.conn, self.page_url, "freshly recrawled markdown", self.crawled_table)
        self.assertFalse(fleet.block_present(self._markdown(), self.pdf_url))
        # Same bytes again -> hash matches -> reheal (restore cached text, no OCR).
        action = self._run(fleet.handle_pdf(self.conn, self.page_url, self.pdf_url, PDF_A, self.stub_ocr))
        self.assertEqual(action, "reheal")
        self.assertEqual(self.ocr_calls, 1, "Reheal must NOT call OCR")
        self.assertTrue(fleet.block_present(self._markdown(), self.pdf_url))
        self.assertIn(f"OCR_OF_{fleet.compute_pdf_hash(PDF_A)[:8]}", self._markdown())

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
        md = self._markdown()
        self.assertTrue(fleet.block_present(md, self.pdf_url))
        self.assertTrue(fleet.block_present(md, pdf_url2))
        self.assertEqual(md.count("OCR-PDF-START"), 2)
        # Re-run first unchanged -> skip, second block untouched.
        action = self._run(fleet.handle_pdf(self.conn, self.page_url, self.pdf_url, PDF_A, self.stub_ocr))
        self.assertEqual(action, "skip")
        self.assertTrue(fleet.block_present(self._markdown(), pdf_url2))


if __name__ == "__main__":
    unittest.main(verbosity=2)
