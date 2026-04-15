"""
Database package for the Website Discovery Service.

This package provides PostgreSQL database interaction including:
    - Connection pooling via asyncpg
    - Schema initialization and migrations
    - Pydantic ORM models for type-safe data access
    - Async context managers for connection handling

Package Structure:
    src/database/
        connection.py   - PostgreSQL connection pooling
        schema.py       - Database schema and migrations
        models.py       - Pydantic ORM models

Usage:
    >>> from src.database.connection import get_pool
    >>> from src.database.models import Domain

    >>> # Get connection pool
    >>> pool = await get_pool()

    >>> # Use async context manager
    >>> async with pool.acquire() as conn:
    ...     await conn.fetch("SELECT * FROM domains")
"""

from __future__ import annotations

from src.database.connection import close_pool, get_pool
from src.database.models import (
    DiscoveryLog,
    Domain,
    SeedUrl,
    UrlQueue,
)
from src.database.schema import initialize_schema

__all__ = [
    "get_pool",
    "close_pool",
    "initialize_schema",
    "Domain",
    "SeedUrl",
    "UrlQueue",
    "DiscoveryLog",
]
