"""
Database schema initialization and migrations.

This module provides functions to:
    - Initialize the database schema
    - Run migrations
    - Create necessary tables and indexes

Tables:
    - seed_urls: Initial seed URLs for discovery
    - domains: Discovered domains with status tracking
    - url_queue: URL processing queue with priorities
    - discovery_log: Audit trail of discovery actions

Indexes:
    - Unique constraints on domains and seed_urls
    - Performance indexes for frequently queried columns
    - Partial indexes for optimized queries

Usage:
    >>> from src.database.schema import initialize_schema
    >>> await initialize_schema()
"""

from __future__ import annotations

from pathlib import Path

from loguru import logger

from src.database.connection import get_pool

# Schema SQL definition
SCHEMA_SQL = """
-- ============================================
-- URL Discovery Service Database Schema
-- ============================================

-- Domain tracking table
CREATE TABLE IF NOT EXISTS domains (
    id SERIAL PRIMARY KEY,
    domain VARCHAR(255) NOT NULL UNIQUE,
    protocol VARCHAR(10) NOT NULL DEFAULT 'https',
    is_live BOOLEAN NOT NULL DEFAULT TRUE,
    status_code INTEGER,
    response_time INTEGER,  -- in milliseconds
    last_checked TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    discovered_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    rediscovered_at TIMESTAMP WITH TIME ZONE,

    -- Metadata
    content_hash VARCHAR(64),
    tags TEXT[]
);

-- Seed URLs table
CREATE TABLE IF NOT EXISTS seed_urls (
    id SERIAL PRIMARY KEY,
    url VARCHAR(500) NOT NULL UNIQUE,
    source VARCHAR(50) NOT NULL DEFAULT 'manual',
    added_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- URL queue for discovery
CREATE TABLE IF NOT EXISTS url_queue (
    id SERIAL PRIMARY KEY,
    url VARCHAR(500) NOT NULL,
    priority INTEGER NOT NULL DEFAULT 3 CHECK (priority BETWEEN 1 AND 5),
    scheduled_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    attempts INTEGER NOT NULL DEFAULT 0,
    status VARCHAR(20) NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'processing', 'completed', 'failed')),
    domain VARCHAR(255) REFERENCES domains(domain)
);

-- Discovery log for audit trail
CREATE TABLE IF NOT EXISTS discovery_log (
    id SERIAL PRIMARY KEY,
    timestamp TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    action VARCHAR(50) NOT NULL,  -- discovered, checked, failed, etc.
    domain VARCHAR(255) REFERENCES domains(domain),
    details JSONB,
    error_message TEXT
);

-- ============================================
-- Indexes for performance
-- ============================================

-- Domain lookups
CREATE INDEX IF NOT EXISTS idx_domains_domain
    ON domains(domain);

-- Live domains only
CREATE INDEX IF NOT EXISTS idx_domains_is_live
    ON domains(is_live);

-- Recently checked domains
CREATE INDEX IF NOT EXISTS idx_domains_last_checked
    ON domains(last_checked);

-- Hash-based domain lookup (for content comparison)
CREATE INDEX IF NOT EXISTS idx_domains_content_hash
    ON domains(content_hash)
    WHERE content_hash IS NOT NULL;

-- Seed URL lookups
CREATE INDEX IF NOT EXISTS idx_seed_urls_url
    ON seed_urls(url);

-- Queue status and priority
CREATE INDEX IF NOT EXISTS idx_url_queue_status
    ON url_queue(status, scheduled_at);

-- Queue by priority
CREATE INDEX IF NOT EXISTS idx_url_queue_priority
    ON url_queue(priority, scheduled_at)
    WHERE status = 'pending';

-- Discovery log by domain
CREATE INDEX IF NOT EXISTS idx_discovery_log_domain
    ON discovery_log(domain);

-- Discovery log by timestamp
CREATE INDEX IF NOT EXISTS idx_discovery_log_timestamp
    ON discovery_log(timestamp);

-- ============================================
-- Triggers
-- ============================================

-- Function to update rediscovered_at when domain becomes live again
CREATE OR REPLACE FUNCTION update_rediscovered_at()
RETURNS TRIGGER AS $$
BEGIN
    IF NEW.is_live = TRUE AND OLD.is_live = FALSE THEN
        NEW.rediscovered_at = CURRENT_TIMESTAMP;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trigger_update_rediscovered_at
    BEFORE UPDATE ON domains
    FOR EACH ROW
    EXECUTE FUNCTION update_rediscovered_at();

-- Function to log domain discoveries
CREATE OR REPLACE FUNCTION log_discovery()
RETURNS TRIGGER AS $$
BEGIN
    IF TG_EVENT = 'INSERT' THEN
        INSERT INTO discovery_log (action, domain, details)
        VALUES ('discovered', NEW.domain,
                jsonb_build_object('protocol', NEW.protocol));
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trigger_log_discovery
    AFTER INSERT ON domains
    FOR EACH ROW
    EXECUTE FUNCTION log_discovery();

-- ============================================
-- Views
-- ============================================

-- Live domains view
CREATE OR REPLACE VIEW v_live_domains AS
SELECT
    id,
    domain,
    protocol,
    status_code,
    response_time,
    last_checked
FROM domains
WHERE is_live = TRUE;

-- Statistics view
CREATE OR REPLACE VIEW v_discovery_stats AS
SELECT
    COUNT(*) as total_domains,
    SUM(CASE WHEN is_live THEN 1 ELSE 0 END) as live_domains,
    SUM(CASE WHEN NOT is_live THEN 1 ELSE 0 END) as dead_domains,
    MAX(discovered_at) as newest_discovery,
    COUNT(DISTINCT source) as seed_sources
FROM domains
JOIN seed_urls ON TRUE;  -- Simplified for stats
"""

# Migration file path
MIGRATIONS_DIR = Path(__file__).parent.parent.parent / "migrations"


async def initialize_schema() -> None:
    """
    Initialize the database schema.

    Creates all tables, indexes, triggers, and views needed
    by the application. Should be called once during deployment.

    Raises:
        Exception: If schema initialization fails.

    Example:
        >>> await initialize_schema()
    """
    pool = await get_pool()

    try:
        logger.info("Initializing database schema...")

        # Read schema from file if available, otherwise use embedded SQL
        migrations_file = MIGRATIONS_DIR / "001_initial_schema.sql"

        if migrations_file.exists():
            schema_sql = migrations_file.read_text(encoding="utf-8")
            logger.info(f"Loading schema from {migrations_file}")
        else:
            schema_sql = SCHEMA_SQL
            logger.info("Using embedded schema definition")

        # Execute schema creation
        async with pool.acquire() as conn:
            await conn.execute(schema_sql)
            logger.info("Database schema initialized successfully")

            # Verify tables were created
            tables = await conn.fetch("""
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = 'public'
                ORDER BY table_name
            """)

            logger.info(f"Created tables: {[t['table_name'] for t in tables]}")

    except Exception as e:
        logger.error(f"Failed to initialize schema: {e}")
        raise


async def run_migration(migration_name: str) -> None:
    """
    Run a specific migration by name.

    Args:
        migration_name: Name of migration file (without .sql extension).

    Example:
        >>> await run_migration("001_initial_schema")
    """
    migrations_file = MIGRATIONS_DIR / f"{migration_name}.sql"

    if not migrations_file.exists():
        raise FileNotFoundError(f"Migration not found: {migrations_file}")

    pool = await get_pool()
    migration_sql = migrations_file.read_text(encoding="utf-8")

    try:
        async with pool.acquire() as conn:
            await conn.execute(migration_sql)

        logger.info(f"Migration {migration_name} completed successfully")
    except Exception as e:
        logger.error(f"Migration {migration_name} failed: {e}")
        raise


async def verify_schema() -> dict[str, bool]:
    """
    Verify that all required schema objects exist.

    Returns:
        Dictionary mapping object type to existence status.

    Example:
        >>> await verify_schema()
        {
            'domains_table': True,
            'seed_urls_table': True,
            'idx_domains_domain': True,
            ...
        }
    """
    pool = await get_pool()

    checks = {}

    # Check tables
    tables = ["domains", "seed_urls", "url_queue", "discovery_log"]
    for table in tables:
        result = await pool.fetchrow("""
            SELECT EXISTS (
                SELECT FROM information_schema.tables
                WHERE table_schema = 'public'
                AND table_name = $1
            )
        """, table)
        checks[f"{table}_table"] = result["exists"]

    # Check indexes
    indexes = [
        "idx_domains_domain",
        "idx_domains_is_live",
        "idx_url_queue_status",
    ]
    for index in indexes:
        result = await pool.fetchrow("""
            SELECT EXISTS (
                SELECT FROM pg_indexes
                WHERE schemaname = 'public'
                AND indexname = $1
            )
        """, index)
        checks[f"{index}_index"] = result["exists"]

    return checks


def get_schema_version() -> str | None:
    """
    Get the current schema version.

    Returns:
        Version string or None if schema not found.
    """
    migrations_file = MIGRATIONS_DIR / "001_initial_schema.sql"

    if not migrations_file.exists():
        return None

    content = migrations_file.read_text(encoding="utf-8")

    # Look for version comment
    for line in content.split("\n"):
        if line.startswith("-- Version:"):
            return line.split(":", 1)[1].strip()

    return "1.0.0"
