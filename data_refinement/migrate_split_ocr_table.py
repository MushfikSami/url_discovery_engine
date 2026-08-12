"""
migrate_split_ocr_table.py
===========================

One-time migration: split the OCR portion out of `crawled_data.raw_markdown`
into its own table, `crawled_data_ocr(url, ocr_markdown, updated_at)`, keyed
by the page URL.

Why
---
The legacy fleets (`vision_ocr_fleet.py`, `sweep_stragglers_fleet.py`) append
OCR text directly onto `crawled_data.raw_markdown`. That mixes two different
kinds of content in one column: the page's own HTML-derived markdown and text
extracted from attached PDFs. `hash_aware_ocr_fleet.py` now writes OCR text to
`crawled_data_ocr` instead -- this script backfills that separation for rows
that already have OCR text mixed into `raw_markdown` from earlier runs.

What it does
------------
For every `crawled_data` row whose `raw_markdown` contains an OCR marker
(`split_markdown_ocr` in `hash_aware_ocr_fleet.py` recognizes both the legacy
plain tag and the hash-aware `<!-- OCR-PDF-START -->` markers):

  1. Split at the first marker: everything before is the base HTML markdown,
     everything from the marker onward is the OCR portion.
  2. Upsert the OCR portion into `crawled_data_ocr.ocr_markdown` for that url.
  3. Overwrite `crawled_data.raw_markdown` with just the base portion.

Both writes happen in the same transaction per row, so a row is never left
half-migrated. The migration is idempotent and safe to re-run: once
`raw_markdown` no longer contains a marker, the row is excluded by the
`WHERE` clause on the next run.

Usage
-----
    python migrate_split_ocr_table.py --dry-run   # preview, no writes
    python migrate_split_ocr_table.py              # perform the migration
"""

import argparse

import psycopg2
from tqdm import tqdm

import hash_aware_ocr_fleet as fleet

BATCH_SIZE = 200


def fetch_migration_candidates(conn, crawled_table=None):
    crawled_table = crawled_table or fleet.CRAWLED_TABLE
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT url, raw_markdown FROM {crawled_table}
            WHERE raw_markdown LIKE %s OR raw_markdown LIKE %s;
            """,
            (f"%{fleet.OCR_HUMAN_TAG}%", "%<!-- OCR-PDF-START%"),
        )
        return cur.fetchall()


def migrate_row(conn, url, raw_markdown, dry_run, crawled_table=None, ocr_table=None):
    """Split one row and, unless dry_run, write both halves in one transaction.

    Returns (base_markdown, ocr_markdown) for reporting, or None if the row
    had no OCR marker after all (shouldn't happen given the WHERE filter, but
    checked defensively since `split_markdown_ocr` is the single source of
    truth for what counts as an OCR boundary).
    """
    crawled_table = crawled_table or fleet.CRAWLED_TABLE
    ocr_table = ocr_table or fleet.OCR_TABLE

    base, ocr = fleet.split_markdown_ocr(raw_markdown)
    if ocr is None:
        return None

    if dry_run:
        return base, ocr

    with conn.cursor() as cur:
        cur.execute(
            f"""
            INSERT INTO {ocr_table} (url, ocr_markdown, updated_at)
            VALUES (%s, %s, NOW())
            ON CONFLICT (url) DO UPDATE SET
                ocr_markdown = EXCLUDED.ocr_markdown,
                updated_at   = NOW();
            """,
            (url, ocr),
        )
        cur.execute(
            f"UPDATE {crawled_table} SET raw_markdown = %s WHERE url = %s;",
            (base, url),
        )
    conn.commit()
    return base, ocr


def run_migration(dry_run=False):
    conn = psycopg2.connect(**fleet.DB_CONFIG)
    fleet.ensure_ocr_table(conn)

    rows = fetch_migration_candidates(conn)
    print(f"📊 Found {len(rows)} rows with OCR content mixed into raw_markdown.")
    if not rows:
        print("✅ Nothing to migrate.")
        conn.close()
        return

    migrated = 0
    skipped = 0
    total_ocr_chars = 0

    for url, raw_markdown in tqdm(rows, desc="Splitting OCR into crawled_data_ocr"):
        result = migrate_row(conn, url, raw_markdown, dry_run)
        if result is None:
            skipped += 1
            continue
        base, ocr = result
        migrated += 1
        total_ocr_chars += len(ocr)

    conn.close()

    mode = "Would migrate" if dry_run else "Migrated"
    print(f"\n🎉 {mode} {migrated} rows ({total_ocr_chars:,} OCR chars moved). "
          f"Skipped {skipped} (no marker found after all).")
    if dry_run:
        print("Dry run only -- no changes written. Re-run without --dry-run to apply.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Preview the split without writing anything to the database.",
    )
    args = parser.parse_args()
    run_migration(dry_run=args.dry_run)
