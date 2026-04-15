"""
Database Setup Script.

This script creates the database and schema for the Website Discovery Service.

Usage:
    python scripts/setup_database.py

This will:
1. Connect to PostgreSQL using credentials from .env
2. Create database if it doesn't exist
3. Create database user with proper permissions
4. Run schema migration
5. Verify all tables and indexes were created
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import asyncpg
from dotenv import load_dotenv
from loguru import logger

# Load environment variables
env_path = Path(__file__).parent.parent / ".env"
if env_path.exists():
    load_dotenv(env_path)

# Get database connection info
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = os.getenv("DB_PORT", "5432")
DB_USER = os.getenv("DB_USER", "postgres")
DB_PASSWORD = os.getenv("DB_PASSWORD", "")
DB_NAME = os.getenv("DB_NAME", "url_discovery_db")

# Superuser database for creating new databases
SUPERUSER_DB = "postgres"


async def get_connection(db_name: str = SUPERUSER_DB) -> asyncpg.Connection:
    """
    Get a database connection.

    Args:
        db_name: Database name to connect to.

    Returns:
        Database connection.
    """
    logger.info(f"Connecting to PostgreSQL on {DB_HOST}:{DB_PORT} as {DB_USER}")

    conn = await asyncpg.connect(
        host=DB_HOST,
        port=DB_PORT,
        user=DB_USER,
        password=DB_PASSWORD,
        database=db_name,
    )

    return conn


async def database_exists(conn: asyncpg.Connection, name: str) -> bool:
    """
    Check if a database exists.

    Args:
        conn: Database connection.
        name: Database name to check.

    Returns:
        True if database exists.
    """
    row = await conn.fetchval(
        "SELECT EXISTS(SELECT 1 FROM pg_database WHERE datname = $1)",
        name,
    )
    return row


async def create_database(conn: asyncpg.Connection, name: str) -> None:
    """
    Create a new database.

    Args:
        conn: Database connection (must connect to a different database).
        name: Database name to create.
    """
    logger.info(f"Creating database: {name}")

    await conn.execute(f'CREATE DATABASE "{name}"')
    logger.info(f"Database {name} created successfully")


async def create_user(conn: asyncpg.Connection, user: str, password: str) -> None:
    """
    Create a database user.

    Args:
        conn: Database connection.
        user: Username to create.
        password: User password.
    """
    # Check if user exists
    exists = await conn.fetchval(
        "SELECT EXISTS(SELECT 1 FROM pg_roles WHERE rolname = $1)",
        user,
    )

    if exists:
        logger.info(f"User {user} already exists, updating password")
        await conn.execute(
            f"ALTER USER \"{user}\" WITH PASSWORD '{password}'"
        )
    else:
        logger.info(f"Creating user: {user}")
        await conn.execute(
            f"CREATE USER \"{user}\" WITH PASSWORD '{password}'"
        )

    logger.info(f"User {user} created/updated successfully")


async def grant_permissions(conn: asyncpg.Connection, user: str, db_name: str) -> None:
    """
    Grant permissions to a user.

    Args:
        conn: Database connection.
        user: Username to grant permissions to.
        db_name: Database to grant permissions on.
    """
    logger.info(f"Granting permissions to {user} on {db_name}")

    # Connect to the target database
    target_conn = await asyncpg.connect(
        host=DB_HOST,
        port=DB_PORT,
        user=DB_USER,
        password=DB_PASSWORD,
        database=db_name,
    )

    try:
        # Grant schema usage
        await target_conn.execute(
            f'GRANT USAGE ON SCHEMA public TO "{user}"'
        )

        # Grant table permissions
        await target_conn.execute(
            f'GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO "{user}"'
        )

        # Grant sequence permissions
        await target_conn.execute(
            f'GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO "{user}"'
        )

        # Set default permissions
        await target_conn.execute(
            f'ALTER DEFAULT PRIVILEGES IN SCHEMA public '
            f'GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO "{user}"'
        )
        await target_conn.execute(
            f'ALTER DEFAULT PRIVILEGES IN SCHEMA public '
            f'GRANT USAGE, SELECT ON SEQUENCES TO "{user}"'
        )

        await target_conn.close()
        logger.info("Permissions granted successfully")

    except Exception as e:
        logger.error(f"Failed to grant permissions: {e}")
        await target_conn.close()
        raise


async def run_schema_migration() -> None:
    """
    Run the schema migration.

    Reads the schema SQL file and executes it.
    """
    logger.info("Running schema migration...")

    # Connect to the database
    conn = await get_connection(DB_NAME)

    try:
        # Read schema SQL
        migrations_dir = Path(__file__).parent.parent / "migrations"
        schema_file = migrations_dir / "001_initial_schema.sql"

        if not schema_file.exists():
            raise FileNotFoundError(f"Schema file not found: {schema_file}")

        schema_sql = schema_file.read_text(encoding="utf-8")

        # Execute schema
        await conn.execute(schema_sql)
        logger.info("Schema migration completed successfully")

    finally:
        await conn.close()


async def verify_setup() -> dict[str, bool]:
    """
    Verify that the database setup is complete.

    Returns:
        Dictionary with verification results.
    """
    logger.info("Verifying database setup...")

    conn = await get_connection(DB_NAME)

    results: dict[str, bool] = {}

    try:
        # Check tables
        tables = ["domains", "seed_urls", "url_queue", "discovery_log"]
        for table in tables:
            exists = await conn.fetchval("""
                SELECT EXISTS (
                    SELECT FROM information_schema.tables
                    WHERE table_schema = 'public'
                    AND table_name = $1
                )
            """, table)
            results[f"table_{table}"] = exists

        # Check indexes
        indexes = [
            "idx_domains_domain",
            "idx_domains_is_live",
            "idx_url_queue_status_priority",
        ]
        for index in indexes:
            exists = await conn.fetchval("""
                SELECT EXISTS (
                    SELECT FROM pg_indexes
                    WHERE schemaname = 'public'
                    AND indexname = $1
                )
            """, index)
            results[f"index_{index}"] = exists

        # Check views
        views = ["v_live_domains", "v_dead_domains", "v_discovery_stats"]
        for view in views:
            exists = await conn.fetchval("""
                SELECT EXISTS (
                    SELECT FROM information_schema.views
                    WHERE table_schema = 'public'
                    AND table_name = $1
                )
            """, view)
            results[f"view_{view}"] = exists

        # Check functions
        functions = ["update_rediscovered_at", "log_discovery", "upsert_domain"]
        for func in functions:
            exists = await conn.fetchval("""
                SELECT EXISTS (
                    SELECT FROM pg_proc
                    WHERE proname = $1
                )
            """, func)
            results[f"function_{func}"] = exists

    finally:
        await conn.close()

    # Log results
    for check, result in results.items():
        status = "OK" if result else "MISSING"
        logger.info(f"  {check}: {status}")

    return results


async def main() -> int:
    """
    Main database setup function.

    Returns:
        Exit code (0 for success, 1 for failure).
    """
    logger.info("=" * 50)
    logger.info("Website Discovery Service - Database Setup")
    logger.info("=" * 50)

    try:
        # Connect to superuser database
        conn = await get_connection(SUPERUSER_DB)

        # Create user if needed
        await create_user(conn, DB_USER, DB_PASSWORD)

        # Create database if needed
        if not await database_exists(conn, DB_NAME):
            await create_database(conn, DB_NAME)

        # Grant permissions
        await grant_permissions(conn, DB_USER, DB_NAME)

        await conn.close()

        # Run schema migration
        await run_schema_migration()

        # Verify setup
        results = await verify_setup()

        # Check if all checks passed
        all_passed = all(results.values())

        print("\n" + "=" * 50)
        if all_passed:
            logger.info("Database setup completed successfully!")
            logger.info("=" * 50)
            print("\nNext steps:")
            print("  1. Add seed URLs:")
            print("     python -m src.tools.ingest_seed_urls seeds/input.txt manual")
            print("\n  2. Run the discovery service:")
            print("     python -m src.main")
            print("\n  3. Generate status report:")
            print("     python -m src.tools.status_report")
        else:
            logger.error("Database setup failed!")
            logger.error(f"Failed checks: {[k for k, v in results.items() if not v]}")

        print("=" * 50)
        return 0 if all_passed else 1

    except Exception as e:
        logger.error(f"Database setup failed: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
