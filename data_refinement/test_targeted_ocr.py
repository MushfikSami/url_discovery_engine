"""
test_targeted_ocr.py
====================

Tests for the TARGETED OCR strategy (OCR only a fixed PDF work-list):
  * extract_pdf_page_map recovers distinct PDF->page mappings from markdown.
  * targets table: ensure / add / fetch_pending / mark / reset_stale.
  * end-to-end targeted processing: a pending target gets OCR'd into
    crawled_data_ocr and marked 'done'; a new PDF gets a real content hash.

DB tests use throwaway tables; production untouched. No network/GPU.
Run:  python test_targeted_ocr.py
"""

import asyncio
import os
import unittest

import psycopg2

import hash_aware_ocr_fleet as fleet
import seed_citizen_charter_targets as seeder

PDF_A = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"


def db_up():
    try:
        psycopg2.connect(**fleet.DB_CONFIG).close()
        return True
    except Exception:
        return False


DB_UP = db_up()


class TestExtract(unittest.TestCase):
    def test_extract_distinct_and_first_page_wins(self):
        rows = [
            ("https://site/p1", "see [a](https://s/a.pdf) and [b](https://s/b.pdf)"),
            ("https://site/p2", "again [a](https://s/a.pdf) plus [c](https://s/c.pdf)"),
            ("https://site/p3", None),
        ]
        m = seeder.extract_pdf_page_map(rows)
        self.assertEqual(set(m), {"https://s/a.pdf", "https://s/b.pdf", "https://s/c.pdf"})
        self.assertEqual(m["https://s/a.pdf"], "https://site/p1")  # first page wins
        self.assertEqual(m["https://s/c.pdf"], "https://site/p2")

    def test_extract_empty(self):
        self.assertEqual(seeder.extract_pdf_page_map([]), {})
        self.assertEqual(seeder.extract_pdf_page_map([("u", "no pdfs here")]), {})

    def test_parse_content_date(self):
        import datetime
        md = "... জমা দিন  কনটেন্টটি শেষ হাল-নাগাদ করা হয়েছে: মঙ্গলবার, ২৫ আগস্ট, ২০২৬ এ ০৮:০০:০০"
        self.assertEqual(seeder.parse_content_date(md), datetime.date(2026, 8, 25))
        old = "কনটেন্টটি শেষ হাল-নাগাদ করা হয়েছে: বুধবার, ১৫ মার্চ, ২০২৩ এ ১০:০০:০০"
        self.assertEqual(seeder.parse_content_date(old), datetime.date(2023, 3, 15))
        # missing phrase / unparseable -> None
        self.assertIsNone(seeder.parse_content_date("no date phrase here"))
        self.assertIsNone(seeder.parse_content_date(None))
        # the volatile SITE timestamp must NOT be picked up as the content date
        self.assertIsNone(seeder.parse_content_date(
            "সাইটটি শেষ হাল-নাগাদ করা হয়েছে: সোমবার, ২৮ সেপ্টেম্বর, ২০২৬ এ ২০:১৫:৩৫"))

    def test_extract_with_date_filter(self):
        import datetime
        cutoff = datetime.date(2024, 9, 1)
        recent = ("https://x/recent",
                  "কনটেন্টটি শেষ হাল-নাগাদ করা হয়েছে: সোমবার, ৩০ সেপ্টেম্বর, ২০২৫ এ ১:০০:০০ "
                  "[a](https://s/recent.pdf)")
        old = ("https://x/old",
               "কনটেন্টটি শেষ হাল-নাগাদ করা হয়েছে: বুধবার, ১৫ মার্চ, ২০২৩ এ ১:০০:০০ "
               "[b](https://s/old.pdf)")
        undated = ("https://x/undated", "no content date [c](https://s/undated.pdf)")
        m = seeder.extract_pdf_page_map([recent, old, undated], min_date=cutoff)
        self.assertEqual(set(m), {"https://s/recent.pdf"})  # only the recent page's PDF
        # without a cutoff, all three come through
        m2 = seeder.extract_pdf_page_map([recent, old, undated])
        self.assertEqual(len(m2), 3)


@unittest.skipUnless(DB_UP, "PostgreSQL not reachable; skipping DB tests")
class TestTargetsDB(unittest.TestCase):
    def setUp(self):
        pid = os.getpid()
        self.targets = f"pdf_ocr_targets_test_{pid}"
        self.cache = f"pdf_ocr_cache_ttest_{pid}"
        self.ocr = f"crawled_data_ocr_ttest_{pid}"
        self.crawled = f"crawled_data_ttest_{pid}"
        self.conn = psycopg2.connect(**fleet.DB_CONFIG)
        with self.conn.cursor() as cur:
            for t in (self.targets, self.cache, self.ocr, self.crawled):
                cur.execute(f"DROP TABLE IF EXISTS {t};")
            cur.execute(f"CREATE TABLE {self.crawled} (url TEXT PRIMARY KEY, raw_markdown TEXT);")
        self.conn.commit()
        fleet.ensure_targets_table(self.conn, self.targets)
        fleet.ensure_cache_table(self.conn, self.cache)
        fleet.ensure_ocr_table(self.conn, self.ocr)
        self._ot, self._oc, self._oo = fleet.TARGETS_TABLE, fleet.CACHE_TABLE, fleet.OCR_TABLE
        self._ocr_crawled = fleet.CRAWLED_TABLE
        fleet.TARGETS_TABLE, fleet.CACHE_TABLE, fleet.OCR_TABLE, fleet.CRAWLED_TABLE = \
            self.targets, self.cache, self.ocr, self.crawled

        self.page = "https://gov.bd/pages/office-citizen-charters/x"
        with self.conn.cursor() as cur:
            cur.execute(f"INSERT INTO {self.crawled}(url,raw_markdown) VALUES(%s,%s);", (self.page, "base"))
        self.conn.commit()

        self.ocr_calls = 0
        async def stub_ocr(b):
            self.ocr_calls += 1
            return "CHARTER_TEXT"
        self.stub_ocr = stub_ocr

    def tearDown(self):
        fleet.TARGETS_TABLE, fleet.CACHE_TABLE, fleet.OCR_TABLE, fleet.CRAWLED_TABLE = \
            self._ot, self._oc, self._oo, self._ocr_crawled
        self.conn.rollback()
        with self.conn.cursor() as cur:
            for t in (self.targets, self.cache, self.ocr, self.crawled):
                cur.execute(f"DROP TABLE IF EXISTS {t};")
        self.conn.commit()
        self.conn.close()

    def test_add_fetch_mark_reset(self):
        fleet.add_target(self.conn, "https://s/a.pdf", self.page, self.targets)
        fleet.add_target(self.conn, "https://s/a.pdf", self.page, self.targets)  # dup ignored
        fleet.add_target(self.conn, "https://s/b.pdf", self.page, self.targets)
        pend = fleet.fetch_pending_targets(self.conn, self.targets)
        self.assertEqual(len(pend), 2)
        fleet.mark_target(self.conn, "https://s/a.pdf", "done", self.targets)
        self.assertEqual(len(fleet.fetch_pending_targets(self.conn, self.targets)), 1)
        # stale 'processing' gets reset back to pending
        fleet.mark_target(self.conn, "https://s/b.pdf", "processing", self.targets)
        fleet.reset_stale_targets(self.conn, self.targets)
        pend = fleet.fetch_pending_targets(self.conn, self.targets)
        self.assertEqual([p[0] for p in pend], ["https://s/b.pdf"])

    def test_transient_failure_requeues_until_budget(self):
        """A transient failure requeues to 'pending' until MAX_OCR_ATTEMPTS, then
        'failed' -- so an outage can't permanently burn the work-list."""
        pdf = "https://s/flaky.pdf"
        fleet.add_target(self.conn, pdf, self.page, self.targets)
        orig = fleet.MAX_OCR_ATTEMPTS
        fleet.MAX_OCR_ATTEMPTS = 3
        try:
            s1 = fleet.record_target_failure(self.conn, pdf, permanent=False, targets_table=self.targets)
            self.assertEqual(s1, "pending")
            s2 = fleet.record_target_failure(self.conn, pdf, permanent=False, targets_table=self.targets)
            self.assertEqual(s2, "pending")
            s3 = fleet.record_target_failure(self.conn, pdf, permanent=False, targets_table=self.targets)
            self.assertEqual(s3, "failed")  # 3rd attempt hits the budget
        finally:
            fleet.MAX_OCR_ATTEMPTS = orig

    def test_permanent_failure_is_terminal(self):
        pdf = "https://s/notapdf"
        fleet.add_target(self.conn, pdf, self.page, self.targets)
        s = fleet.record_target_failure(self.conn, pdf, permanent=True, targets_table=self.targets)
        self.assertEqual(s, "failed")
        self.assertEqual(fleet.fetch_pending_targets(self.conn, self.targets), [])

    def test_end_to_end_target_ocr(self):
        """Simulate the targeted worker's core: handle_pdf on a target PDF writes
        OCR to crawled_data_ocr and the target is marked done."""
        pdf_url = "https://s/charter.pdf"
        fleet.add_target(self.conn, pdf_url, self.page, self.targets)

        action = asyncio.run(fleet.handle_pdf(self.conn, self.page, pdf_url, PDF_A, self.stub_ocr))
        fleet.mark_target(self.conn, pdf_url, "done" if action != "invalid" else "failed", self.targets)

        self.assertEqual(action, "ocr")
        self.assertEqual(self.ocr_calls, 1)
        # OCR text landed in crawled_data_ocr under the page URL
        md = fleet.get_ocr_markdown(self.conn, self.page, self.ocr)
        self.assertIn("CHARTER_TEXT", md)
        self.assertTrue(fleet.block_present(md, pdf_url))
        # new PDF cached with a REAL content hash
        cached = fleet.get_cache_entry(self.conn, pdf_url, self.cache)
        self.assertEqual(cached[0], fleet.compute_pdf_hash(PDF_A))
        # target now done -> no longer pending
        self.assertEqual(fleet.fetch_pending_targets(self.conn, self.targets), [])

    def test_seed_run_populates_targets(self):
        # Two citizen-charter pages with PDFs; seeder should insert distinct PDFs.
        with self.conn.cursor() as cur:
            cur.execute(f"INSERT INTO {self.crawled}(url,raw_markdown) VALUES "
                        f"(%s,%s),(%s,%s);",
                        ("https://x/pages/office-citizen-charters/1", "[a](https://s/a.pdf)",
                         "https://x/pages/office-citizen-charters/2", "[a](https://s/a.pdf) [b](https://s/b.pdf)"))
        self.conn.commit()
        # run seeder logic against the throwaway crawled table via extract + add
        with self.conn.cursor() as cur:
            cur.execute(f"SELECT url, raw_markdown FROM {self.crawled} WHERE url ILIKE %s;",
                        ("%citizen%charter%",))
            rows = cur.fetchall()
        m = seeder.extract_pdf_page_map(rows)
        for pdf, page in m.items():
            fleet.add_target(self.conn, pdf, page, self.targets)
        pend = fleet.fetch_pending_targets(self.conn, self.targets)
        self.assertEqual({p[0] for p in pend}, {"https://s/a.pdf", "https://s/b.pdf"})


if __name__ == "__main__":
    unittest.main(verbosity=2)
