"""
PostgreSQL connection pooling for the Website Discovery Service.

This module provides async connection pooling using asyncpg with
configurable pool size, timeout, and recycling settings.

The connection pool is managed as a singleton instance throughout
the application lifecycle.

Features:
    - Async connection pooling via asyncpg
    - Automatic connection recycling
    - Graceful shutdown support
    - Connection timeout handling

Usage:
    >>> from src.database.connection import get_pool
    >>>
    >>> # Get pool and acquire connection
    >>> pool = await get_pool()
    >>> async with pool.acquire() as conn:
    ...     result = await conn.fetch("SELECT * FROM domains LIMIT 10")
"""

from __future__ import annotations

import asyncio
from typing import Any

import asyncpg
from loguru import logger

from src.config.settings import settings


class ConnectionPoolManager:
    """
    Singleton connection pool manager.

    Manages the lifecycle of the asyncpg connection pool
    including initialization and graceful shutdown.

    Attributes:
        _pool: The asyncpg pool instance (None until initialized).
    """

    _instance: ConnectionPoolManager | None = None
    _pool: asyncpg.Pool | None = None
    _lock: asyncio.Lock = asyncio.Lock()

    def __new__(cls) -> ConnectionPoolManager:
        """Ensure singleton instance."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    async def initialize(self) -> asyncpg.Pool:
        """
        Initialize the connection pool.

        Creates the pool using settings from config.
        If already initialized, returns existing pool.

        Returns:
            asyncpg.Pool instance.

        Raises:
            Exception: If pool initialization fails.
        """
        if self._pool is not None:
            logger.debug("Connection pool already initialized")
            return self._pool

        async with self._lock:
            if self._pool is None:
                try:
                    logger.info(
                        f"Initializing connection pool: {settings.database.host}:"
                        f"{settings.database.port}/{settings.database.name}"
                    )

                    self._pool = await asyncpg.create_pool(
                        host=settings.database.host,
                        port=settings.database.port,
                        user=settings.database.user,
                        password=settings.database.password,
                        database=settings.database.name,
                        min_size=settings.database.pool_size,
                        max_size=settings.database.max_overflow + settings.database.pool_size,
                        max_queries=settings.database.pool_size * 1000,
                        max_inactive_connection_lifetime=300.0,
                        timeout=settings.database.pool_timeout,
                    )

                    logger.info(
                        f"Connection pool initialized: {settings.database.pool_size} "
                        f"min connections, {self._pool.get_max_size()} max connections"
                    )

                except Exception as e:
                    logger.error(f"Failed to initialize connection pool: {e}")
                    raise

        return self._pool

    async def close(self) -> None:
        """
        Gracefully close the connection pool.

        Waits for all active connections to complete and
        releases all resources.
        """
        if self._pool is not None:
            logger.info("Closing connection pool...")
            await self._pool.close()
            self._pool = None
            logger.info("Connection pool closed")

    async def execute(
        self,
        query: str,
        *args: Any,
        **kwargs: Any,
    ) -> asyncpg.CommandRecord:
        """
        Execute a query using the connection pool.

        Convenience method for simple queries that don't
        require connection acquisition.

        Args:
            query: SQL query string.
            *args: Positional arguments for query.
            **kwargs: Keyword arguments for query.

        Returns:
            CommandRecord with query result.
        """
        pool = await self.initialize()
        async with pool.acquire() as conn:
            return await conn.execute(query, *args, **kwargs)

    async def fetch(
        self,
        query: str,
        *args: Any,
        **kwargs: Any,
    ) -> list[asyncpg.Record]:
        """
        Fetch rows using the connection pool.

        Convenience method for SELECT queries.

        Args:
            query: SQL SELECT query string.
            *args: Positional arguments for query.
            **kwargs: Keyword arguments for query.

        Returns:
            List of asyncpg.Record objects.
        """
        pool = await self.initialize()
        async with pool.acquire() as conn:
            result: list[asyncpg.Record] = await conn.fetch(query, *args, **kwargs)
            return result

    async def fetchone(
        self,
        query: str,
        *args: Any,
        **kwargs: Any,
    ) -> asyncpg.Record | None:
        """
        Fetch a single row using the connection pool.

        Args:
            query: SQL SELECT query string.
            *args: Positional arguments for query.
            **kwargs: Keyword arguments for query.

        Returns:
            Single asyncpg.Record or None if no rows.
        """
        pool = await self.initialize()
        async with pool.acquire() as conn:
            return await conn.fetchone(query, *args, **kwargs)


# Global pool manager instance
_pool_manager = ConnectionPoolManager()


async def get_pool() -> asyncpg.Pool:
    """
    Get the global connection pool instance.

    This is the primary way to access the connection pool.
    The pool is automatically initialized on first call.

    Returns:
        asyncpg.Pool instance.

    Example:
        >>> pool = await get_pool()
        >>> async with pool.acquire() as conn:
        ...     domains = await conn.fetch("SELECT * FROM domains")
    """
    return await _pool_manager.initialize()


async def close_pool() -> None:
    """
    Close the global connection pool.

    Should be called during application shutdown to
    ensure graceful cleanup of database connections.

    Example:
        >>> try:
        ...     await main()
        ... finally:
        ...     await close_pool()
    """
    await _pool_manager.close()


def acquire_connection() -> asyncpg.PoolAcquireContext:
    """
    Get a connection acquire context.

    Use this for more granular control over connection
    lifecycle when needed.

    Returns:
        asyncpg.PoolAcquireContext for use in async with.

    Example:
        >>> async with acquire_connection() as conn:
        ...     result = await conn.fetch("SELECT * FROM domains")
    """
    if _pool_manager._pool is None:
        raise RuntimeError("Connection pool not initialized")
    return _pool_manager._pool.acquire()
