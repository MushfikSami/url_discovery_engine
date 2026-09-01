"""
seed_pdf_cache_from_existing.py
===============================

Seed `pdf_ocr_cache` from PDFs that were ALREADY OCR'd, so the incremental OCR
fleet (`hash_aware_ocr_fleet.py` in URL_SKIP_MODE) skips them without
downloading or re-OCRing.

Why this is instant and correct
-------------------------------
The already-OCR'd text in `crawled_data_ocr.ocr_markdown` carries the source PDF
URLs as `Document Source: <url>` lines. Those URLs are content-addressed
(object-storage filenames are content hashes), so a URL that's already been OCR'd
will never change at that URL -- its mere presence is a valid "done" marker.

So we rebuild the cache purely from text already in the DB: no PDF downloads, no
GPU, no network. Each recovered `(pdf_url -> page_url, ocr_text)` becomes a
cache row with a sentinel hash (`SEED_HASH`), meaning "seeded by URL, not
content-hashed." The fleet's URL-presence gate then skips these before download;
genuinely new PDF URLs (on new OR existing pages) fall through to real OCR and
get a real content hash.

Usage:
    python seed_pdf_cache_from_existing.py --dry-run
    python seed_pdf_cache_from_existing.py
"""

import argparse
import re

import psycopg2
from tqdm import tqdm

import hash_aware_ocr_fleet as fleet

# Sentinel content hash for rows seeded by URL rather than by hashing bytes.
SEED_HASH = "url-seeded"

# Matches "Document Source: <url>" as written by the OCR fleets.
_SRC_RE = re.compile(r"Document Source:\s*(\S+)")


def parse_pdf_blocks(ocr_markdown):
    """Extract [(pdf_url, ocr_text), ...] from a page's ocr_markdown.

    Splits on each `Document Source:` marker; a PDF's text runs from just after
    its URL to the start of the next marker (or end of string). Pure function.
    """
    if not ocr_markdown:
        return []
    matches = list(_SRC_RE.finditer(ocr_markdown))
    blocks = []
    for i, m in enumerate(matches):
        pdf_url = m.group(1).strip()
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(ocr_markdown)
        text = ocr_markdown[start:end].strip()
        if pdf_url:
            blocks.append((pdf_url, text))
    return blocks


def seed(conn, dry_run=False, ocr_table=None, cache_table=None):
    """Populate the cache from crawled_data_ocr. Returns (pages, pdf_urls_seeded)."""
    ocr_table = ocr_table or fleet.OCR_TABLE
    cache_table = cache_table or fleet.CACHE_TABLE

    fleet.ensure_cache_table(conn, cache_table)

    with conn.cursor() as cur:
        cur.execute(
            f"SELECT count(*) FROM {ocr_table} WHERE ocr_markdown IS NOT NULL;"
        )
        total_pages = cur.fetchone()[0]

    read = conn.cursor(name="seed_pdf_cache")
    read.itersize = 1000
    read.execute(
        f"SELECT url, ocr_markdown FROM {ocr_table} WHERE ocr_markdown IS NOT NULL;"
    )

    seeded = 0
    pages = 0
    write = psycopg2.connect(**fleet.DB_CONFIG) if not dry_run else None
    seen = set()  # avoid re-inserting the same pdf_url twice in one run
    try:
        for page_url, md in tqdm(read, total=total_pages, desc="Seeding pdf_ocr_cache"):
            pages += 1
            for pdf_url, text in parse_pdf_blocks(md):
                if pdf_url in seen:
                    continue
                seen.add(pdf_url)
                seeded += 1
                if dry_run:
                    continue
                with write.cursor() as wc:
                    wc.execute(
                        f"""INSERT INTO {cache_table}
                            (pdf_url, page_url, pdf_hash, ocr_text,
                             last_checked, updated_at)
                            VALUES (%s, %s, %s, %s, NOW(), NOW())
                            ON CONFLICT (pdf_url) DO NOTHING;""",
                        (pdf_url, page_url, SEED_HASH, text),
                    )
                if not dry_run and seeded % 1000 == 0:
                    write.commit()
        if not dry_run:
            write.commit()
    finally:
        read.close()
        if write:
            write.close()
    return pages, seeded


def run(dry_run=False):
    conn = psycopg2.connect(**fleet.DB_CONFIG)
    try:
        pages, seeded = seed(conn, dry_run=dry_run)
    finally:
        conn.close()
    verb = "Would seed" if dry_run else "Seeded"
    print(f"\n[+] {verb} {seeded:,} distinct PDF URLs from {pages:,} OCR'd pages.")
    if dry_run:
        print("Dry run -- no writes. Re-run without --dry-run to apply.")
    else:
        print("Now run the fleet incrementally:  python hash_aware_ocr_fleet.py")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true", help="Preview only; no writes.")
    args = ap.parse_args()
    run(dry_run=args.dry_run)
