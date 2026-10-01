"""
seed_citizen_charter_targets.py
===============================

Seed `pdf_ocr_targets` with the citizen-charter PDFs -- the current OCR
strategy is to OCR ONLY these, not a topic-keyword page scan.

Source of truth: the PDF links stored in `crawled_data.raw_markdown` for pages
whose URL matches the citizen-charter pattern (`%citizen%charter%`, which is the
superset that yields the ~1,709 distinct PDFs). Each distinct PDF URL is mapped
to one citizen-charter page URL that references it (the page its OCR text will be
attached to in `crawled_data_ocr`).

Usage:
    python seed_citizen_charter_targets.py --dry-run
    python seed_citizen_charter_targets.py
"""

import argparse
import datetime
import re

import psycopg2

import hash_aware_ocr_fleet as fleet

# Pattern matching all citizen-charter pages (singular/plural, any language slug,
# any section).
PAGE_PATTERN = "%citizen%charter%"
PDF_RE = re.compile(r'https?://[^\s\)\]\("\'<>]+\.pdf', re.I)

# Only OCR PDFs whose page's CONTENT was last updated on/after this date. Uses the
# Bengali "কনটেন্টটি শেষ হাল-নাগাদ করা হয়েছে:" (content-last-updated) line -- NOT the
# volatile "সাইটটি" (site) timestamp. Pages with no parseable content-date are
# excluded (treated as too old / unknown).
CONTENT_DATE_CUTOFF = datetime.date(2024, 9, 1)

_BN_DIGITS = {c: str(i) for i, c in enumerate("০১২৩৪৫৬৭৮৯")}
_BN_MONTHS = {
    "জানুয়ারি": 1, "জানুয়ারী": 1, "ফেব্রুয়ারি": 2, "ফেব্রুয়ারী": 2, "মার্চ": 3,
    "এপ্রিল": 4, "মে": 5, "জুন": 6, "জুলাই": 7, "আগস্ট": 8, "সেপ্টেম্বর": 9,
    "অক্টোবর": 10, "নভেম্বর": 11, "ডিসেম্বর": 12,
}
# day  month  year, after the "কনটেন্টটি … হাল-নাগাদ করা হয়েছে:" phrase.
_CONTENT_DATE_RE = re.compile(
    r'কনটেন্টটি[^:：]*হাল-নাগাদ[^:：]*[:：]\s*[^,]*,\s*'
    r'([০-৯]{1,2})\s+([ঀ-৿]+)\s*,?\s*([০-৯]{4})'
)


def _bn_int(s):
    return int("".join(_BN_DIGITS.get(ch, ch) for ch in s))


def parse_content_date(markdown):
    """Return the page's content-last-updated date, or None if absent/unparseable.
    Pure function (no DB/network)."""
    if not markdown:
        return None
    m = _CONTENT_DATE_RE.search(markdown)
    if not m:
        return None
    mon = _BN_MONTHS.get(m.group(2))
    if not mon:
        return None
    try:
        return datetime.date(_bn_int(m.group(3)), mon, _bn_int(m.group(1)))
    except ValueError:
        return None


def extract_pdf_page_map(rows, min_date=None):
    """rows = iterable of (page_url, raw_markdown).
    Returns dict {pdf_url -> page_url}: first page seen that references each PDF.

    If `min_date` is set, pages whose content-last-updated date is missing or
    older than `min_date` are skipped entirely (their PDFs are not included).
    Pure function (no DB/network) for testing."""
    mapping = {}
    for page_url, md in rows:
        if not md:
            continue
        if min_date is not None:
            dt = parse_content_date(md)
            if dt is None or dt < min_date:
                continue
        for pdf_url in PDF_RE.findall(md):
            if pdf_url not in mapping:
                mapping[pdf_url] = page_url
    return mapping


def run(dry_run=False, page_pattern=PAGE_PATTERN, min_date=CONTENT_DATE_CUTOFF):
    conn = psycopg2.connect(**fleet.DB_CONFIG)
    fleet.ensure_targets_table(conn)

    with conn.cursor() as cur:
        cur.execute(
            "SELECT url, raw_markdown FROM crawled_data WHERE url ILIKE %s;",
            (page_pattern,),
        )
        rows = cur.fetchall()

    mapping = extract_pdf_page_map(rows, min_date=min_date)
    print(f"[*] Citizen-charter pages scanned: {len(rows):,}")
    if min_date:
        print(f"[*] Date filter: content updated on/after {min_date}")
    print(f"[*] Distinct PDF URLs to target:  {len(mapping):,}")

    if dry_run:
        for pdf_url, page_url in list(mapping.items())[:3]:
            print(f"    e.g. {pdf_url}\n         <- {page_url}")
        print("[dry-run] No writes. Re-run without --dry-run to seed.")
        conn.close()
        return len(mapping)

    inserted = 0
    with conn.cursor() as cur:
        for pdf_url, page_url in mapping.items():
            cur.execute(
                f"""INSERT INTO {fleet.TARGETS_TABLE} (pdf_url, page_url, status)
                    VALUES (%s, %s, 'pending')
                    ON CONFLICT (pdf_url) DO NOTHING;""",
                (pdf_url, page_url),
            )
            inserted += cur.rowcount
    conn.commit()

    with conn.cursor() as cur:
        cur.execute(f"SELECT status, count(*) FROM {fleet.TARGETS_TABLE} GROUP BY status;")
        status = dict(cur.fetchall())
    conn.close()
    print(f"[+] Inserted {inserted:,} new targets. Table status: {status}")
    return len(mapping)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true", help="Preview only; no writes.")
    args = ap.parse_args()
    run(dry_run=args.dry_run)
