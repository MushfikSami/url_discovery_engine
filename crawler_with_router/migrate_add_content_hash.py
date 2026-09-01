"""
migrate_add_content_hash.py
===========================

One-time migration to enable incremental crawling on an already-populated
`crawled_data` table.

Two steps:
  1. Add the change-detection columns (idempotent) via
     `change_detection.ensure_hash_columns`.
  2. Backfill `content_hash = sha256(raw_markdown)` for every existing row that
     doesn't have one yet. This establishes the *baseline*: on the next crawl,
     a page whose re-rendered markdown hashes to the same value is recognized as
     unchanged and skipped, instead of being re-written.

Baseline note
-------------
`source_hash` (raw HTML) and the HTTP validators (ETag / Last-Modified) can only
be captured by actually fetching a page, so they are left NULL here. Consequence:

  * The FIRST incremental crawl still fetches every page (and re-renders JS-heavy
    ones) to seed those validators -- but it only WRITES rows whose markdown
    changed, and it records source_hash / ETag as it goes.
  * EVERY subsequent crawl is then fully incremental: static pages short-circuit
    on the raw-HTML hash or a 304, skipping parse and write entirely.

Usage:
    python migrate_add_content_hash.py --dry-run
    python migrate_add_content_hash.py
"""

import argparse

import psycopg2
from tqdm import tqdm

import change_detection as cd
from db_setup import DB_CONFIG

BATCH = 2000


def count_missing(conn, table):
    with conn.cursor() as cur:
        cur.execute(
            f"SELECT count(*) FROM {table} "
            f"WHERE content_hash IS NULL AND raw_markdown IS NOT NULL;"
        )
        return cur.fetchone()[0]


def run(dry_run=False, table=None):
    table = table or cd.CRAWLED_TABLE
    conn = psycopg2.connect(**DB_CONFIG)

    print("[*] Ensuring change-detection columns exist...")
    cd.ensure_hash_columns(conn, table)

    total = count_missing(conn, table)
    print(f"[*] Rows needing a content_hash baseline: {total:,}")
    if total == 0:
        print("[+] Nothing to backfill.")
        conn.close()
        return

    if dry_run:
        print("[dry-run] Would backfill content_hash for the above rows. No writes.")
        conn.close()
        return

    # Stream URL+markdown with a server-side cursor; write hashes back in batches.
    read_cur = conn.cursor(name="backfill_hash")
    read_cur.itersize = BATCH
    read_cur.execute(
        f"SELECT url, raw_markdown FROM {table} "
        f"WHERE content_hash IS NULL AND raw_markdown IS NOT NULL;"
    )

    write_conn = psycopg2.connect(**DB_CONFIG)
    done = 0
    batch = []
    for url, md in tqdm(read_cur, total=total, desc="Backfilling content_hash"):
        batch.append((cd.sha256_text(md), url))
        if len(batch) >= BATCH:
            _flush(write_conn, table, batch)
            done += len(batch)
            batch = []
    if batch:
        _flush(write_conn, table, batch)
        done += len(batch)

    read_cur.close()
    conn.close()
    write_conn.close()
    print(f"\n[+] Backfilled content_hash for {done:,} rows.")


def _flush(conn, table, batch):
    with conn.cursor() as cur:
        cur.executemany(
            f"UPDATE {table} SET content_hash = %s WHERE url = %s;", batch
        )
    conn.commit()


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true", help="Preview only; no writes.")
    args = ap.parse_args()
    run(dry_run=args.dry_run)
