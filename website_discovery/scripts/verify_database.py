"""
Database verification script.

This script verifies all database tables, columns, indexes, and views
have been created correctly.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

import asyncpg
from dotenv import load_dotenv

# Load environment
load_dotenv(Path(__file__).parent / ".env")

DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = os.getenv("DB_PORT", "5432")
DB_USER = os.getenv("DB_USER", "postgres")
DB_PASSWORD = os.getenv("DB_PASSWORD", "")
DB_NAME = os.getenv("DB_NAME", "url_discovery_db")


async def verify_database() -> None:
    """Verify database structure."""
    # Use postgres user with no password for local verification
    conn = await asyncpg.connect(
        host=DB_HOST,
        port=DB_PORT,
        user="postgres",
        database=DB_NAME,
    )

    print("=" * 60)
    print("Database Verification for:", DB_NAME)
    print("=" * 60)

    # 1. List tables
    print("\n[1] TABLES")
    print("-" * 40)
    tables = await conn.fetch("""
        SELECT table_name
        FROM information_schema.tables
        WHERE table_schema = 'public'
        ORDER BY table_name
    """)
    for table in tables:
        print(f"  - {table['table_name']}")

    # 2. Show table structures
    print("\n[2] TABLE STRUCTURES")
    print("-" * 40)
    for table in [t['table_name'] for t in tables]:
        print(f"\n  Table: {table}")
        columns = await conn.fetch(f"""
            SELECT column_name, data_type, is_nullable, column_default
            FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = '{table}'
            ORDER BY ordinal_position
        """)
        for col in columns:
            nullable = "NULL" if col["is_nullable"] == "YES" else "NOT NULL"
            default = col["column_default"] or ""
            print(f"    - {col['column_name']}: {col['data_type']} ({nullable}) {default}")

    # 3. List indexes
    print("\n[3] INDEXES")
    print("-" * 40)
    indexes = await conn.fetch("""
        SELECT indexname, tablename
        FROM pg_indexes
        WHERE schemaname = 'public'
        ORDER BY tablename, indexname
    """)
    for idx in indexes:
        print(f"  - {idx['indexname']} on {idx['tablename']}")

    # 4. List views
    print("\n[4] VIEWS")
    print("-" * 40)
    views = await conn.fetch("""
        SELECT table_name
        FROM information_schema.views
        WHERE table_schema = 'public'
        ORDER BY table_name
    """)
    for view in views:
        print(f"  - {view['table_name']}")

    # 5. List functions
    print("\n[5] FUNCTIONS")
    print("-" * 40)
    functions = await conn.fetch("""
        SELECT proname
        FROM pg_proc
        WHERE pronamespace = (SELECT oid FROM pg_namespace WHERE nspname = 'public')
        ORDER BY proname
    """)
    for func in functions:
        print(f"  - {func['proname']}")

    # 6. Sample data
    print("\n[6] SAMPLE DATA")
    print("-" * 40)

    # Domains
    domains = await conn.fetch("SELECT COUNT(*) as count FROM domains")
    print(f"  domains: {domains[0]['count']} records")

    # Seed URLs
    seeds = await conn.fetch("SELECT COUNT(*) as count FROM seed_urls")
    print(f"  seed_urls: {seeds[0]['count']} records")

    # Url Queue
    queue = await conn.fetch("SELECT COUNT(*) as count FROM url_queue")
    print(f"  url_queue: {queue[0]['count']} records")

    # Discovery Log
    log = await conn.fetch("SELECT COUNT(*) as count FROM discovery_log")
    print(f"  discovery_log: {log[0]['count']} records")

    await conn.close()

    print("\n" + "=" * 60)
    print("Database verification complete!")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(verify_database())