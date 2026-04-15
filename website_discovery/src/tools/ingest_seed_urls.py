"""
Seed URL Ingestion Tool.

This tool allows you to add seed URLs to the database from a text file.
Each line in the file should contain one URL.

Usage:
    python -m src.tools.ingest_seed_urls <file.txt> [source]

    python -m src.tools.ingest_seed_urls seeds/input.txt manual
    python -m src.tools.ingest_seed_urls seeds/batch.csv batch

Tool Usage:
    ===================================
    Purpose: Add seed URLs for discovery
    ===================================

    1. Create a seed file with one URL per line:

       https://bangladesh.gov.bd
       https://ministry.gov.bd
       https://example.gov.bd

    2. Run the tool:

       python -m src.tools.ingest_seed_urls seeds/input.txt manual

    3. Verify seeds were added:

       psql -U url_discovery -d url_discovery_db -c "SELECT * FROM seed_urls;"

    Sources:
        - manual: URLs added manually by user
        - batch: URLs added in bulk import
        - api: URLs added via API
        - import: URLs imported from another source
        - export: URLs exported from the system
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any

from loguru import logger

from src.database.connection import get_pool


async def ingest_seed_urls(
    file_path: str,
    source: str = "manual",
) -> dict[str, Any]:
    """
    Ingest seed URLs from a file into the database.

    Args:
        file_path: Path to .txt file with one URL per line.
        source: Source identifier (manual/batch/api/import/export).

    Returns:
        Dictionary with ingestion statistics.
    """
    pool = await get_pool()
    stats = {
        "total_lines": 0,
        "valid_urls": 0,
        "inserted": 0,
        "skipped_duplicates": 0,
        "errors": 0,
    }

    try:
        # Read file
        path = Path(file_path)
        if not path.exists():
            logger.error(f"File not found: {file_path}")
            return stats

        content = path.read_text(encoding="utf-8")
        lines = content.strip().split("\n")
        stats["total_lines"] = len(lines)

        # Process each line
        for line in lines:
            url = line.strip()

            if not url:
                continue

            # Normalize URL
            if not url.startswith(("http://", "https://")):
                url = f"https://{url}"

            try:
                # Check if URL already exists
                exists = await pool.fetchval(
                    "SELECT id FROM seed_urls WHERE url = $1",
                    url,
                )

                if exists:
                    stats["skipped_duplicates"] += 1
                    logger.debug(f"URL already exists: {url}")
                    continue

                # Insert new seed URL
                await pool.execute(
                    """
                    INSERT INTO seed_urls (url, source, added_at)
                    VALUES ($1, $2, CURRENT_TIMESTAMP)
                    """,
                    url,
                    source,
                )

                stats["valid_urls"] += 1
                stats["inserted"] += 1
                logger.info(f"Added seed URL: {url}")

            except Exception as e:
                stats["errors"] += 1
                logger.error(f"Error processing URL {url}: {e}")

        return stats

    except Exception as e:
        logger.error(f"Failed to ingest seed URLs: {e}")
        return stats


async def ingest_from_database(
    source_table: str,
    url_column: str = "url",
    target_source: str = "import",
) -> dict[str, Any]:
    """
    Ingest seed URLs from another database table.

    Args:
        source_table: Table name to read from.
        url_column: Column name containing URLs.
        target_source: Source identifier for inserted URLs.

    Returns:
        Dictionary with ingestion statistics.
    """
    pool = await get_pool()
    stats = {
        "total_urls": 0,
        "inserted": 0,
        "skipped_duplicates": 0,
        "errors": 0,
    }

    try:
        # Read URLs from source table
        rows = await pool.fetch(
            f"SELECT {url_column} FROM {source_table}"
        )

        stats["total_urls"] = len(rows)

        for row in rows:
            url = row[url_column]

            if not url or not isinstance(url, str):
                continue

            # Normalize URL
            if not url.startswith(("http://", "https://")):
                url = f"https://{url}"

            # Check if already exists
            exists = await pool.fetchval(
                "SELECT id FROM seed_urls WHERE url = $1",
                url,
            )

            if exists:
                stats["skipped_duplicates"] += 1
                continue

            # Insert
            await pool.execute(
                """
                INSERT INTO seed_urls (url, source, added_at)
                VALUES ($1, $2, CURRENT_TIMESTAMP)
                """,
                url,
                target_source,
            )

            stats["inserted"] += 1
            logger.info(f"Imported: {url}")

        return stats

    except Exception as e:
        logger.error(f"Failed to import from {source_table}: {e}")
        return stats


def main() -> None:
    """
    CLI entry point for seed URL ingestion.

    Usage:
        python -m src.tools.ingest_seed_urls <file.txt> [source]
    """
    if len(sys.argv) < 2:
        print(__doc__)
        print("\nUsage: python -m src.tools.ingest_seed_urls <file.txt> [source]")
        print("Sources: manual, batch, api, import, export")
        sys.exit(1)

    file_path = sys.argv[1]
    source = sys.argv[2] if len(sys.argv) > 2 else "manual"

    logger.info(f"Starting seed URL ingestion from {file_path}")
    logger.info(f"Source: {source}")

    # Run ingestion
    stats = asyncio.run(ingest_seed_urls(file_path, source))

    # Print results
    print("\n" + "=" * 50)
    print("Seed URL Ingestion Summary")
    print("=" * 50)
    print(f"Total lines:      {stats['total_lines']}")
    print(f"Valid URLs:       {stats['valid_urls']}")
    print(f"Inserted:         {stats['inserted']}")
    print(f"Skipped (duplicates): {stats['skipped_duplicates']}")
    print(f"Errors:           {stats['errors']}")
    print("=" * 50)

    if stats["inserted"] > 0:
        print(f"\nSuccessfully added {stats['inserted']} seed URLs!")
        print("\nTo start discovery, run:")
        print("  python -m src.main")
    else:
        print("\nNo new URLs were added.")

    sys.exit(0 if stats["errors"] == 0 else 1)


if __name__ == "__main__":
    main()
