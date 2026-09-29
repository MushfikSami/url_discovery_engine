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
import re

import psycopg2

import hash_aware_ocr_fleet as fleet

# Pattern matching all citizen-charter pages (singular/plural, any language slug,
# any section). Verified to yield 1,709 distinct PDFs.
PAGE_PATTERN = "%citizen%charter%"
PDF_RE = re.compile(r'https?://[^\s\)\]\("\'<>]+\.pdf', re.I)


def extract_pdf_page_map(rows):
    """rows = iterable of (page_url, raw_markdown).
    Returns dict {pdf_url -> page_url}: first page seen that references each PDF.
    Pure function (no DB/network) for testing."""
    mapping = {}
    for page_url, md in rows:
        if not md:
            continue
        for pdf_url in PDF_RE.findall(md):
            if pdf_url not in mapping:
                mapping[pdf_url] = page_url
    return mapping


def run(dry_run=False, page_pattern=PAGE_PATTERN):
    conn = psycopg2.connect(**fleet.DB_CONFIG)
    fleet.ensure_targets_table(conn)

    with conn.cursor() as cur:
        cur.execute(
            "SELECT url, raw_markdown FROM crawled_data WHERE url ILIKE %s;",
            (page_pattern,),
        )
        rows = cur.fetchall()

    mapping = extract_pdf_page_map(rows)
    print(f"[*] Citizen-charter pages scanned: {len(rows):,}")
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
