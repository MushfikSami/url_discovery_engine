"""
Discovery Engine - Main URL discovery orchestration.

This module provides the main discovery engine that:
    - Orchestrates the discovery process
    - Manages worker tasks
    - Handles state persistence
    - Coordinates with database and queue

Usage:
    >>> from src.crawler.engine import DiscoveryEngine
    >>> engine = DiscoveryEngine()
    >>> await engine.run()
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

import aiohttp
from loguru import logger

from src.config.settings import settings
from src.crawler.finder import DomainFinder
from src.crawler.queue import DatabaseQueue, PriorityQueue
from src.database.connection import get_pool
from src.database.models import Domain, UrlQueue

import threading
import json
class DiscoveryEngine:
    """
    Main discovery engine for URL discovery service.

    This class orchestrates the entire discovery process:
    1. Loads seed URLs from database
    2. Initializes queue with seeds
    3. Creates worker tasks
    4. Processes URLs concurrently
    5. Saves progress on shutdown

    Attributes:
        max_concurrent: Maximum concurrent HTTP requests.
        semaphore: For rate limiting concurrent requests.
        queue: URL processing queue.
        finder: Domain extraction utility.

    Example:
        >>> engine = DiscoveryEngine(max_workers=50)
        >>> asyncio.run(engine.run())
    """

    def __init__(
        self,
        max_workers: int | None = None,
        discovery_mode: str = "continuous",
        shutdown_event: threading.Event | None = None,  # Add this!
    ) -> None:
        self.max_workers: int = max_workers or settings.crawler.max_concurrent_requests
        self.discovery_mode: str = discovery_mode
        self.semaphore: asyncio.Semaphore = asyncio.Semaphore(self.max_workers)
        self.shutdown_event = shutdown_event  # Store it here

        # Initialize queue and finder
        self.queue: DatabaseQueue = DatabaseQueue()
        self.in_memory_queue: PriorityQueue = PriorityQueue()
        self.finder: DomainFinder = DomainFinder()

        # State tracking
        self.visited_urls: set[str] = set()
        self.discovered_domains: set[str] = set()
        self._running: bool = False
        self._workers: list[asyncio.Task] = []

        # HTTP session
        self._session: aiohttp.ClientSession | None = None

        logger.info(
            f"DiscoveryEngine initialized: "
            f"max_workers={self.max_workers}, mode={discovery_mode}"
        )

    async def start(self) -> None:
        """Start the discovery engine and load seeds."""
        logger.info("Starting discovery engine...")
        self._running = True
        
        # Load seed URLs (Uses DB pool, doesn't need HTTP session yet)
        await self._load_seed_urls()
        logger.info("Discovery engine started")
    
    async def stop(self) -> None:
        """
        Stop the discovery engine.

        Cancels workers, closes HTTP session, and saves state.
        """
        logger.info("Stopping discovery engine...")
        self._running = False

        # Cancel workers
        for worker in self._workers:
            worker.cancel()

        await asyncio.gather(*self._workers, return_exceptions=True)
        self._workers.clear()

        # Close session
        if self._session:
            await self._session.close()
            self._session = None

        # Save state
        await self._save_state()

        logger.info("Discovery engine stopped")

    async def run(self) -> None:
        """Run the discovery engine safely."""
        await self.start()

        try:
            # THIS block fixes the memory leak. The session is guaranteed to close!
            connector = aiohttp.TCPConnector(
                limit=self.max_workers * 2, limit_per_host=100, ssl=False
            )
            timeout = aiohttp.ClientTimeout(total=settings.crawler.timeout)
            
            async with aiohttp.ClientSession(
                connector=connector, 
                timeout=timeout, 
                headers={"User-Agent": settings.crawler.user_agent}
            ) as session:
                self._session = session
                
                if self.discovery_mode == "continuous":
                    await self._continuous_loop()
                else:
                    await self._one_time_run()
                    
        except asyncio.CancelledError:
            logger.info("Discovery engine cancelled")
        finally:
            await self.stop()

    async def _continuous_loop(self) -> None:
        """Run continuous discovery loop."""
        logger.info("Running in continuous mode...")

        # 1. Check the shutdown event
        while self._running and not (self.shutdown_event and self.shutdown_event.is_set()):
            batch = await self.in_memory_queue.get_batch(50)
            if batch:
                tasks = [
                    asyncio.create_task(self._process_url(item))
                    for item in batch
                ]
                self._workers.extend(tasks)

                done, pending = await asyncio.wait(
                    tasks,
                    return_when=asyncio.FIRST_COMPLETED,
                )

                # 2. Fix the Orphan Tasks! Cancel them AND await their death.
                for p in pending:
                    p.cancel()
                if pending:
                    await asyncio.gather(*pending, return_exceptions=True)

            # 3. Sleep in chunks to allow instant shutdown
            for _ in range(settings.scheduler.check_interval):
                if self.shutdown_event and self.shutdown_event.is_set():
                    break
                await asyncio.sleep(1)

    async def _one_time_run(self) -> None:
        """Run single discovery cycle and exit."""
        logger.info("Running in one-time mode...")

        # Check the shutdown event
        while not self.in_memory_queue.is_empty() and self._running and not (self.shutdown_event and self.shutdown_event.is_set()):
            batch = await self.in_memory_queue.get_batch(100)
            if not batch:
                break

            tasks = [asyncio.create_task(self._process_url(item)) for item in batch]
            
            try:
                await asyncio.gather(*tasks, return_exceptions=True)
            except asyncio.CancelledError:
                # Catch shutdown interruptions and kill tasks cleanly
                for task in tasks:
                    if not task.done():
                        task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
                raise
    
    async def _load_seed_urls(self) -> int:
        """
        Load seed URLs from database.

        Returns:
            Number of seeds loaded.
        """
        pool = await get_pool()

        try:
            # Get seed URLs from database
            rows = await pool.fetch(
                "SELECT url, source FROM seed_urls ORDER BY added_at"
            )

            count = 0
            for row in rows:
                url = row["url"]
                await self.in_memory_queue.add(url, priority=1, domain=None)
                count += 1

            logger.info(f"Loaded {count} seed URLs into queue")
            return count

        except Exception as e:
            logger.error(f"Failed to load seed URLs: {e}", exc_info=True)
            return 0

    async def _process_url(self, item: UrlQueue) -> None:
        """
        Process a single URL from the queue.

        Args:
            item: UrlQueue item to process.
        """
        url = item.url

        # Skip if already visited
        if url in self.visited_urls:
            await self.in_memory_queue.complete(item, success=True)
            return

        self.visited_urls.add(url)

        async with self.semaphore:
            try:
                # Fetch and parse
                domains = await self.finder.find_domains_from_url(url, self._session)  # type: ignore

                if domains:
                    # Add new domains to queue
                    for domain in domains:
                        if domain.domain not in self.discovered_domains:
                            self.discovered_domains.add(domain.domain)

                            # Add to queue with lower priority (discovery URLs)
                            await self.in_memory_queue.add(
                                f"https://{domain.domain}",
                                priority=3,
                                domain=domain.domain,
                            )

                            # Save to database
                            await self._save_domain(domain)

                    if len(self.discovered_domains) % 100 == 0:
                        logger.info(f"Discovered {len(domains)} domains from {url}")

                await self.in_memory_queue.complete(item, success=True)

            except KeyError as e:
                import traceback
                tb_str = traceback.format_exc()
                logger.error(f"KeyError processing {url}: {e}\n{tb_str}")
                await self.in_memory_queue.mark_failed(item)
            except Exception as e:
                logger.error(f"Error processing {url}: {type(e).__name__}: {str(e)}")
                await self.in_memory_queue.mark_failed(item)

    async def _save_domain(self, domain: Domain) -> None:
        """
        Save domain to database.

        Args:
            domain: Domain to save.
        """
        pool = await get_pool()

        try:
            # Use upsert to avoid duplicates
            await pool.execute("""
                INSERT INTO domains (domain, protocol, is_live, discovered_at)
                VALUES ($1, $2, $3, $4)
                ON CONFLICT (domain) DO UPDATE SET
                    last_checked = CURRENT_TIMESTAMP,
                    is_live = EXCLUDED.is_live
                """,
                str(domain.domain),
                str(domain.protocol),
                bool(domain.is_live),
                domain.discovered_at or datetime.now(timezone.utc),
            )

            # Log discovery
            import json
            await pool.execute("""
                INSERT INTO discovery_log (action, domain, details)
                VALUES ($1, $2, $3)
                """,
                "discovered",
                str(domain.domain),
                json.dumps({"protocol": str(domain.protocol)}),
            )

        except Exception as e:
            logger.error(f"Failed to save domain {domain.domain}: {type(e).__name__}: {str(e)}")

    async def _save_state(self) -> None:
        """
        Save current state to database.

        Called on shutdown for resume capability.
        """
        logger.info("Saving state...")

        state_data: dict[str, Any] = {
            "visited_count": len(self.visited_urls),
            "domains_count": len(self.discovered_domains),
            "queue_size": self.in_memory_queue.size(),
            "stats": self.in_memory_queue.get_statistics(),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        # Save to database as progress marker
        pool = await get_pool()
        try:
            await pool.execute("""
                INSERT INTO discovery_log (action, details)
                VALUES ('state_save', $1)
                """,
                json.dumps(state_data),
            )
            logger.info("State saved")
        except Exception as e:
            logger.error(f"Failed to save state: {e}")

    def get_statistics(self) -> dict[str, Any]:
        """
        Get discovery statistics.

        Returns:
            Dictionary with discovery stats.
        """
        return {
            "visited_urls": len(self.visited_urls),
            "discovered_domains": len(self.discovered_domains),
            "queue_size": self.in_memory_queue.size(),
            "running": self._running,
            "workers": len(self._workers),
        }


# Async context manager for automatic startup/shutdown
class DiscoveryEngineContext:
    """
    Context manager for DiscoveryEngine.

    Usage:
        >>> async with DiscoveryEngineContext() as engine:
        ...     await engine.run()
    """

    def __init__(
        self,
        max_workers: int | None = None,
        discovery_mode: str = "continuous",
    ) -> None:
        """
        Initialize context manager.

        Args:
            max_workers: Number of concurrent workers.
            discovery_mode: 'continuous' or 'one-time'.
        """
        self.engine = DiscoveryEngine(max_workers, discovery_mode)

    async def __aenter__(self) -> DiscoveryEngine:
        """Enter context."""
        await self.engine.start()
        return self.engine

    async def __aexit__(
        self,
        exc_type: Any,
        exc_val: Any,
        exc_tb: Any,
    ) -> None:
        """Exit context."""
        await self.engine.stop()
