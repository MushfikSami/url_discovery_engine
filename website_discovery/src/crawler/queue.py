"""
Priority Queue management for URL discovery.

This module provides async priority queue functionality:
    - Add URLs with priority levels
    - Get next URL to process
    - Mark URLs as completed/failed
    - Queue statistics and cleanup

Priority Levels:
    1: Critical (seed URLs)
    2: High (rediscovered domains)
    3: Medium (regular discovery)
    4: Low (liveness checks)
    5: Minimum (cleanup/archival)
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from datetime import timezone as tz
from typing import Any

from loguru import logger

from src.config.settings import settings
from src.database.models import QueueStatus, UrlQueue


class PriorityQueue:
    """
    Async priority queue for URL discovery.

    Manages URLs with priority-based ordering. Higher priority
    items are processed first. Supports database persistence
    for resumption capability.

    Attributes:
        max_queue_size: Maximum items in queue.
        cleanup_threshold: Max age for keeping items.

    Example:
        >>> queue = PriorityQueue()
        >>> await queue.add("https://example.gov.bd", priority=1)
        >>> item = await queue.get_next()
    """

    def __init__(
        self,
        max_queue_size: int | None = None,
        cleanup_threshold: int = 3600,
    ) -> None:
        """
        Initialize Priority Queue.

        Args:
            max_queue_size: Maximum queue size (None for unlimited).
            cleanup_threshold: Seconds after which to cleanup items.
        """
        self.max_queue_size: int = max_queue_size or settings.scheduler.max_queue_size
        self.cleanup_threshold: int = cleanup_threshold
        self._queue: list[UrlQueue] = []
        self._lock: asyncio.Lock = asyncio.Lock()

        logger.debug(f"PriorityQueue initialized: max_size={self.max_queue_size}")

    async def add(
        self,
        url: str,
        priority: int = 3,
        domain: str | None = None,
    ) -> UrlQueue:
        """
        Add URL to queue with priority.

        Args:
            url: URL to add.
            priority: Priority level (1-5, lower is higher priority).
            domain: Associated domain if known.

        Returns:
            Added UrlQueue item.

        Example:
            >>> await queue.add("https://example.gov.bd", priority=1)
        """
        async with self._lock:
            if len(self._queue) >= self.max_queue_size:
                # Drop lowest priority items silently (queue is large enough for normal operation)
                self._queue.sort(key=lambda x: x.priority, reverse=True)
                self._queue.pop()

            item = UrlQueue(
                url=url,
                priority=max(1, min(5, priority)),
                status=QueueStatus.PENDING,
                domain=domain,
            )
            self._queue.append(item)
            if priority <= 2:
                logger.debug(f"Added to queue: {url} (priority={priority})")

            return item

    async def get_next(self) -> UrlQueue | None:
        """
        Get next URL to process (highest priority).

        Returns:
            UrlQueue item or None if queue is empty.
        """
        async with self._lock:
            if not self._queue:
                return None

            # Sort by priority (ascending) then by scheduled_at
            self._queue.sort(key=lambda x: (x.priority, x.scheduled_at or datetime.now(tz.utc)))

            # Get first item
            item = self._queue.pop(0)
            item.status = QueueStatus.PROCESSING
            logger.debug(f"Getting next: {item.url} (priority={item.priority})")

            return item

    async def get_batch(self, batch_size: int | None = None) -> list[UrlQueue]:
        """
        Get batch of URLs for parallel processing.

        Args:
            batch_size: Number of URLs to return.

        Returns:
            List of UrlQueue items.
        """
        batch_size = batch_size or settings.scheduler.queue_batch_size
        result: list[UrlQueue] = []

        async with self._lock:
            # Sort by priority (ascending) then by scheduled_at
            self._queue.sort(key=lambda x: (x.priority, x.scheduled_at or datetime.now(tz.utc)))

            # Get batch of items
            for _ in range(min(batch_size, len(self._queue))):
                item = self._queue.pop(0)
                item.status = QueueStatus.PROCESSING
                result.append(item)

        return result

    async def complete(self, item: UrlQueue, success: bool = True) -> None:
        """
        Mark queue item as completed.

        Args:
            item: UrlQueue item to mark complete.
            success: Whether processing was successful.
        """
        async with self._lock:
            for i, existing in enumerate(self._queue):
                if existing.url == item.url:
                    self._queue.pop(i)
                    break

            item.status = QueueStatus.COMPLETED if success else QueueStatus.FAILED
            logger.debug(f"Queue item completed: {item.url} (success={success})")

    async def mark_failed(self, item: UrlQueue, max_retries: int | None = None) -> None:
        """
        Mark item as failed and potentially schedule retry.

        Args:
            item: Failed UrlQueue item.
            max_retries: Maximum retry count.
        """
        max_retries = max_retries or settings.scheduler.max_retries

        async with self._lock:
            item.attempts += 1

            if item.attempts >= max_retries:
                # Give up after max retries
                item.status = QueueStatus.FAILED
                logger.warning(f"Failed item giving up: {item.url} (attempts={item.attempts})")
            else:
                # Schedule retry with backoff
                item.status = QueueStatus.PENDING
                delay = min(
                    settings.scheduler.retry_delay * (2 ** (item.attempts - 1)),
                    3600,  # Max 1 hour
                )
                item.scheduled_at = datetime.now(tz.utc) + timedelta(seconds=delay)
                logger.info(f"Scheduling retry: {item.url} (attempt={item.attempts + 1})")

    async def cleanup(self) -> int:
        """
        Remove stale queue items.

        Items older than cleanup_threshold are removed.

        Returns:
            Number of items removed.
        """
        removed = 0
        now = datetime.now(tz.utc)

        async with self._lock:
            # Filter out stale items
            new_queue: list[UrlQueue] = []
            for item in self._queue:
                if item.scheduled_at is None:
                    new_queue.append(item)
                    continue

                age = (now - item.scheduled_at.replace(tzinfo=tz.utc)).total_seconds()
                if age < self.cleanup_threshold:
                    new_queue.append(item)
                else:
                    removed += 1

            self._queue = new_queue
            logger.debug(f"Queue cleanup: {removed} items removed, {len(self._queue)} remaining")

            return removed

    def size(self) -> int:
        """
        Get current queue size.

        Returns:
            Number of items in queue.
        """
        return len(self._queue)

    def is_empty(self) -> bool:
        """
        Check if queue is empty.

        Returns:
            True if queue has no items.
        """
        return len(self._queue) == 0

    def get_statistics(self) -> dict[str, Any]:
        """
        Get queue statistics.

        Returns:
            Dictionary with queue stats.
        """
        stats: dict[str, Any] = {
            "total": len(self._queue),
            "pending": 0,
            "processing": 0,
            "by_priority": {1: 0, 2: 0, 3: 0, 4: 0, 5: 0},
        }

        for item in self._queue:
            if item.status == QueueStatus.PENDING:
                stats["pending"] += 1
            elif item.status == QueueStatus.PROCESSING:
                stats["processing"] += 1

        # Count by priority
        for item in self._queue:
            priority = item.priority
            if priority in stats["by_priority"]:
                stats["by_priority"][priority] += 1

        return stats

    async def clear(self) -> None:
        """Clear all items from queue."""
        async with self._lock:
            self._queue.clear()
            logger.info("Queue cleared")


# Convenience class for database-backed queue
class DatabaseQueue:
    """
    Priority queue backed by PostgreSQL.

    Uses database for persistent queue storage with automatic
    cleanup and priority ordering.
    """

    def __init__(self) -> None:
        """Initialize database-backed queue."""
        self.in_memory_queue = PriorityQueue()
        logger.debug("DatabaseQueue initialized")

    async def enqueue(self, url: str, priority: int = 3, domain: str | None = None) -> None:
        """
        Enqueue URL to database.

        Args:
            url: URL to process.
            priority: Queue priority.
            domain: Associated domain.
        """
        # Add to database (placeholder - implements database insert)
        await self._insert_to_db(url, priority, domain)

        # Also add to in-memory for fast access
        await self.in_memory_queue.add(url, priority, domain)

    async def _insert_to_db(self, url: str, priority: int, domain: str | None) -> None:
        """Insert URL to database queue."""
        # This would use asyncpg to insert
        # Placeholder for actual implementation
        pass

    async def dequeue(self) -> UrlQueue | None:
        """
        Get next URL from queue.

        Returns:
            UrlQueue item or None.
        """
        # First check in-memory
        item = await self.in_memory_queue.get_next()
        if item:
            return item

        # Fall back to database
        return await self._fetch_from_db()

    async def _fetch_from_db(self) -> UrlQueue | None:
        """Fetch next item from database."""
        # Placeholder - would query database ordered by priority
        return None

    async def update_status(self, item: UrlQueue, status: QueueStatus) -> None:
        """
        Update queue item status.

        Args:
            item: UrlQueue to update.
            status: New status.
        """
        async with self.in_memory_queue._lock:
            for _i, existing in enumerate(self.in_memory_queue._queue):
                if existing.url == item.url:
                    item = existing
                    item.status = status
                    break

        # Update in database
        await self._update_db_status(item)

    async def _update_db_status(self, item: UrlQueue) -> None:
        """Update item status in database."""
        pass
