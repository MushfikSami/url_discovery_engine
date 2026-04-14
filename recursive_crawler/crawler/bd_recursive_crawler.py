"""
Recursive BD Government Domain Crawler.

This module implements a high-performance async crawler for discovering
Bangladesh government (.gov.bd) domains through recursive URL exploration.

Features:
    - Asyncio-based concurrent crawling (configurable workers)
    - State persistence for resumable execution
    - Domain extraction and deduplication
    - Graceful shutdown with progress saving

Usage:
    >>> from recursive_crawler.crawler.bd_recursive_crawler import RecursiveBDCrawler
    >>> crawler = RecursiveBDCrawler(max_concurrent_requests=30)
    >>> crawler.run()

Author: URL Discovery Engine Team
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from typing import Any

import aiohttp
from bs4 import BeautifulSoup
from urllib.parse import urlparse, urljoin

# Import logger for structured logging
try:
    from src.url_discovery_engine.logger import get_logger

    logger = get_logger(__name__)
except ImportError:
    # Fallback logger if package not installed
    from logging import getLogger

    logger = getLogger(__name__)


class RecursiveBDCrawler:
    """
    Recursive crawler for discovering .gov.bd domains.

    This crawler performs async HTTP requests to explore government
    websites and extract all .gov.bd domains found. It maintains state
    to allow resumption after interruption.

    Attributes:
        max_concurrent_requests: Maximum simultaneous HTTP requests (default: 30)
        state_file: Path to save/load crawler state (default: "crawler_state.json")
        output_file: Path to save discovered domains (default: "recursive_gov_bd_domains.txt")
        seed_urls: Initial URLs to start crawling from

    Example:
        >>> crawler = RecursiveBDCrawler(max_concurrent_requests=50)
        >>> asyncio.run(crawler.run())
    """

    def __init__(
        self,
        max_concurrent_requests: int = 30,
        state_file: str = "crawler_state.json",
        output_file: str = "recursive_gov_bd_domains.txt",
    ) -> None:
        """
        Initialize the RecursiveBDCrawler.

        Args:
            max_concurrent_requests: Maximum number of concurrent HTTP requests.
                Must be between 1 and 1000. Defaults to 30.
            state_file: Path to the file used for saving/loading crawler state.
                Used to resume interrupted crawls. Defaults to "crawler_state.json".
            output_file: Path to the file where discovered domains are saved.
                Each domain is written on a new line. Defaults to
                "recursive_gov_bd_domains.txt".

        Raises:
            ValueError: If max_concurrent_requests is not between 1 and 1000.
        """
        if not 1 <= max_concurrent_requests <= 1000:
            raise ValueError("max_concurrent_requests must be between 1 and 1000")

        self.state_file: str = state_file
        self.output_file: str = output_file

        # Seed URLs from Bangladesh government portal
        self.seed_urls: list[str] = [
            "https://bangladesh.gov.bd",
            "https://bangladesh.gov.bd/views/ministry-and-directorate-list",
            "https://bangladesh.gov.bd/views/union-list",
        ]

        # State tracking
        self.found_domains: set[str] = set()
        self.visited_urls: set[str] = set()
        self.queue: asyncio.Queue = asyncio.Queue()

        # Concurrency control
        self.semaphore: asyncio.Semaphore = asyncio.Semaphore(max_concurrent_requests)

        # HTTP configuration
        self.headers: dict[str, str] = {
            "User-Agent": "BD-Gov-Ecosystem-Mapper/3.0 (Research)"
        }

        logger.info(
            f"Initialized RecursiveBDCrawler with {max_concurrent_requests} workers"
        )

    def load_state(self) -> bool:
        """
        Load previous crawler state from file if it exists.

        This method enables resuming an interrupted crawl by restoring
        the list of visited URLs, remaining queue items, and discovered domains.

        Returns:
            True if state was loaded successfully, False if no state file exists.

        Side Effects:
            Populates found_domains, visited_urls, and queue with saved data.
        """
        if not os.path.exists(self.state_file):
            logger.debug("No previous state file found. Starting fresh.")
            return False

        logger.info(f"Found state file '{self.state_file}'. Resuming progress...")

        try:
            with open(self.state_file, "r", encoding="utf-8") as f:
                data: dict[str, Any] = json.load(f)

            # Restore visited URLs
            self.visited_urls = set(data.get("visited_urls", []))

            # Restore queue
            saved_queue: list[str] = data.get("queue", [])
            for url in saved_queue:
                self.queue.put_nowait(url)

            # Restore found domains from output file
            if os.path.exists(self.output_file):
                with open(self.output_file, "r", encoding="utf-8") as f:
                    self.found_domains = {
                        line.strip() for line in f if line.strip()
                    }

            logger.info(
                f"Resumed with {len(self.found_domains)} domains, "
                f"{self.queue.qsize()} URLs in queue"
            )
            return True

        except (json.JSONDecodeError, IOError) as e:
            logger.error(f"Failed to load state: {e}")
            return False

    def save_state(self) -> None:
        """
        Save current crawler state to file.

        This method saves the current state including:
        - Visited URLs (to avoid reprocessing)
        - Queue contents (remaining URLs to process)

        Should be called before exiting to allow resume capability.
        """
        logger.info("Saving current state... Please wait.")

        # Extract current queue contents
        current_queue: list[str] = []
        while not self.queue.empty():
            current_queue.append(self.queue.get_nowait())

        # Build state data
        state_data: dict[str, Any] = {
            "visited_urls": list(self.visited_urls),
            "queue": current_queue,
        }

        try:
            with open(self.state_file, "w", encoding="utf-8") as f:
                json.dump(state_data, f, indent=2)

            logger.info(f"State saved to '{self.state_file}'. You can safely exit.")

        except IOError as e:
            logger.error(f"Failed to save state: {e}")

    def get_gov_bd_domain(self, url: str) -> str | None:
        """
        Extract .gov.bd domain from URL.

        Parses the URL and extracts the domain, ensuring it ends with
        ".gov.bd". Handles common URL variations like www prefix and ports.

        Args:
            url: The URL to extract domain from.

        Returns:
            The extracted domain if it ends with ".gov.bd", None otherwise.

        Example:
            >>> crawler = RecursiveBDCrawler()
            >>> crawler.get_gov_bd_domain("https://example.gov.bd/path")
            'example.gov.bd'
            >>> crawler.get_gov_bd_domain("https://other.com")
            None
        """
        try:
            parsed = urlparse(url)
            domain: str = parsed.netloc.lower().split(":")[0]

            # Remove www. prefix if present
            if domain.startswith("www."):
                domain = domain[4:]

            # Only return if it's a .gov.bd domain
            if domain.endswith(".gov.bd"):
                return domain

        except Exception as e:
            logger.debug(f"Failed to extract domain from {url}: {e}")

        return None

    async def fetch_and_parse(
        self, session: aiohttp.ClientSession, url: str
    ) -> tuple[str | None, str]:
        """
        Fetch and parse HTML content from URL.

        Makes an async HTTP request to the specified URL and returns
        the HTML content if the request succeeds with status 200.

        Args:
            session: Active aiohttp ClientSession.
            url: URL to fetch.

        Returns:
            Tuple of (html_content, url). html_content is None if request fails.
        """
        async with self.semaphore:
            try:
                async with session.get(
                    url,
                    headers=self.headers,
                    timeout=15,
                    ssl=False,
                    allow_redirects=True,
                ) as response:
                    if response.status == 200:
                        html = await response.text()
                        logger.debug(f"Successfully fetched: {url}")
                        return html, url

            except asyncio.TimeoutError:
                logger.debug(f"Timeout fetching: {url}")
            except aiohttp.ClientError as e:
                logger.debug(f"Client error fetching {url}: {e}")
            except Exception as e:
                logger.debug(f"Unexpected error fetching {url}: {e}")

        return None, url

    async def worker(
        self, session: aiohttp.ClientSession, worker_id: int
    ) -> None:
        """
        Async worker coroutine that processes URLs from the queue.

        This is the main work loop for each crawler worker. It continuously
        fetches URLs, extracts links, and adds new .gov.bd URLs to the queue.

        Args:
            session: Active aiohttp ClientSession for HTTP requests.
            worker_id: Unique identifier for this worker (for logging).
        """
        while True:
            try:
                current_url: str = await self.queue.get()

                # Skip already visited URLs
                if current_url in self.visited_urls:
                    self.queue.task_done()
                    continue

                self.visited_urls.add(current_url)
                html, _ = await self.fetch_and_parse(session, current_url)

                if html:
                    soup: BeautifulSoup = BeautifulSoup(html, "html.parser")

                    for link in soup.find_all("a", href=True):
                        raw_href: str = link["href"].strip()
                        full_url: str = urljoin(url, raw_href).split("#")[0]
                        domain: str | None = self.get_gov_bd_domain(full_url)

                        # Add new .gov.bd domains
                        if domain and domain not in self.found_domains:
                            self.found_domains.add(domain)
                            print(
                                f"[Worker-{worker_id}] [+] New: {domain} (Total: {len(self.found_domains)})"
                            )

                            # Append to output file
                            with open(self.output_file, "a", encoding="utf-8") as f:
                                f.write(f"{domain}\n")

                        # Add URL to queue if it's a .gov.bd domain and not visited
                        if domain and full_url not in self.visited_urls:
                            await self.queue.put(full_url)

                self.queue.task_done()

            except asyncio.CancelledError:
                logger.info(f"Worker {worker_id} cancelled")
                break
            except Exception as e:
                logger.error(f"Worker {worker_id} error: {e}")
                self.queue.task_done()

    async def run(self) -> None:
        """
        Execute the recursive crawling process.

        Main entry point for the crawler. Loads previous state if available,
        initializes workers, and processes all URLs in the queue.

        The method handles KeyboardInterrupt for graceful shutdown,
        saving state before exiting.
        """
        logger.info("Initializing Resumable Recursive Crawler...")

        # Load state or initialize with seed URLs
        if not self.load_state():
            # Clear output file on fresh start
            open(self.output_file, "w", encoding="utf-8").close()

            # Add seed URLs to queue
            for url in self.seed_urls:
                self.queue.put_nowait(url)

            logger.info(
                f"Started fresh with {len(self.seed_urls)} seed URLs"
            )

        # Create worker tasks
        num_workers: int = 30
        logger.info(f"Starting {num_workers} worker tasks...")

        workers: list[asyncio.Task] = []
        for i in range(num_workers):
            task: asyncio.Task = asyncio.create_task(
                self.worker(session=None, worker_id=i)
            )
            workers.append(task)

        # Use a real session for actual HTTP requests
        async with aiohttp.ClientSession(headers=self.headers) as session:
            # Re-create workers with actual session
            for w in workers:
                w.cancel()

            workers = []
            for i in range(num_workers):
                task = asyncio.create_task(
                    self.worker(session, i)
                )
                workers.append(task)

            try:
                await self.queue.join()
                logger.info("Queue processing complete.")
            except asyncio.CancelledError:
                logger.info("Queue processing cancelled.")
            finally:
                for w in workers:
                    w.cancel()

    def __del__(self) -> None:
        """Destructor that saves state if object is garbage collected."""
        if hasattr(self, "found_domains") and hasattr(self, "state_file"):
            try:
                self.save_state()
            except Exception:
                pass  # Ignore errors during cleanup


if __name__ == "__main__":
    # Create and run crawler
    crawler: RecursiveBDCrawler = RecursiveBDCrawler(max_concurrent_requests=30)

    # Set up signal handling for Ctrl+C
    loop: asyncio.AbstractEventLoop = asyncio.get_event_loop()
    main_task: asyncio.Task = loop.create_task(crawler.run())

    try:
        loop.run_until_complete(main_task)
    except KeyboardInterrupt:
        print("\n[!] Crawler stopped via Ctrl+C.")
        main_task.cancel()

        # Wait for clean cancellation
        loop.run_until_complete(asyncio.sleep(0.5))

        # Save progress
        crawler.save_state()
        sys.exit(0)
