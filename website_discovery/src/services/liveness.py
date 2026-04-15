"""
Liveness Service for domain status checking.

This module provides functionality to:
    - Check if a domain is currently live (responding to HTTP requests)
    - Update domain status in database
    - Batch check multiple domains
    - Schedule liveness check retries

Usage:
    >>> from src.services.liveness import LivenessService
    >>> service = LivenessService()
    >>> result = await service.check_domain("example.gov.bd")
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

import aiohttp
from loguru import logger

from src.config.settings import settings
from src.database.connection import get_pool


class LivenessCheckResult:
    """
    Result of a liveness check.

    Attributes:
        domain: Domain that was checked.
        is_live: Whether domain is live.
        status_code: HTTP status code (if available).
        response_time: Response time in milliseconds.
        error: Error message if check failed.
        checked_at: When the check was performed.
    """

    def __init__(
        self,
        domain: str,
        is_live: bool,
        status_code: int | None = None,
        response_time: int | None = None,
        error: str | None = None,
        checked_at: datetime | None = None,
    ) -> None:
        """Initialize result."""
        self.domain = domain
        self.is_live = is_live
        self.status_code = status_code
        self.response_time = response_time
        self.error = error
        self.checked_at = checked_at or datetime.now(timezone.utc)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "domain": self.domain,
            "is_live": self.is_live,
            "status_code": self.status_code,
            "response_time": self.response_time,
            "error": self.error,
            "checked_at": self.checked_at.isoformat(),
        }

    def __repr__(self) -> str:
        """String representation."""
        status = "LIVE" if self.is_live else "DEAD"
        return f"LivenessCheckResult(domain={self.domain}, status={status})"


class LivenessService:
    """
    Service for checking domain liveness.

    This service:
    - Makes HTTP requests to domains
    - Determines live/dead status
    - Updates database with results
    - Schedules retries for dead domains

    Attributes:
        http_check: Enable HTTP checking.
        https_check: Enable HTTPS checking.
        timeout: Request timeout in seconds.
        live_status_codes: Status codes considered "live".

    Example:
        >>> service = LivenessService()
        >>> await service.check_batch(domains)
    """

    def __init__(
        self,
        http_check: bool | None = None,
        https_check: bool | None = None,
        timeout: int | None = None,
    ) -> None:
        """
        Initialize LivenessService.

        Args:
            http_check: Enable HTTP checks.
            https_check: Enable HTTPS checks.
            timeout: Request timeout.
        """
        self.http_check: bool = http_check if http_check is not None else settings.liveness.http_check
        self.https_check: bool = https_check if https_check is not None else settings.liveness.https_check
        self.timeout: int = timeout if timeout is not None else settings.liveness.timeout
        self.live_status_codes: list[int] = settings.liveness.live_status_codes
        self.follow_redirects: bool = settings.liveness.follow_redirects

        logger.info(
            f"LivenessService initialized: "
            f"http={self.http_check}, https={self.https_check}, timeout={self.timeout}s"
        )

    async def check_domain(self, domain: str) -> LivenessCheckResult:
        """
        Check if a single domain is live.

        Args:
            domain: Domain to check.

        Returns:
            LivenessCheckResult with check outcome.
        """
        # Try HTTPS first if enabled
        if self.https_check:
            result = await self._check_url(f"https://{domain}")
            if result.is_live:
                return result

        # Try HTTP if HTTPS failed or disabled
        if self.http_check:
            result = await self._check_url(f"http://{domain}")
            return result

        # Neither protocol enabled
        return LivenessCheckResult(
            domain=domain,
            is_live=False,
            error="Both HTTP and HTTPS checks disabled",
        )

    async def _check_url(self, url: str) -> LivenessCheckResult:
        """
        Check a specific URL.

        Args:
            url: Full URL to check.

        Returns:
            LivenessCheckResult.
        """
        start_time = datetime.now(timezone.utc)

        try:
            connector = aiohttp.TCPConnector(ssl=False)

            async with aiohttp.ClientSession(connector=connector) as session:
                async with session.get(
                    url,
                    timeout=aiohttp.ClientTimeout(total=self.timeout),
                    allow_redirects=self.follow_redirects,
                    ssl=False,
                ) as response:
                    status_code = response.status
                    response_time = int((datetime.now(timezone.utc) - start_time).total_seconds() * 1000)

                    is_live = status_code in self.live_status_codes

                    return LivenessCheckResult(
                        domain=url.replace("https://", "").replace("http://", "").split("/")[0],
                        is_live=is_live,
                        status_code=status_code,
                        response_time=response_time,
                    )

        except asyncio.TimeoutError:
            response_time = int((datetime.now(timezone.utc) - start_time).total_seconds() * 1000)
            return LivenessCheckResult(
                domain=url.replace("https://", "").replace("http://", "").split("/")[0],
                is_live=False,
                error=f"Timeout after {self.timeout}s",
                response_time=response_time,
            )

        except aiohttp.ClientError as e:
            response_time = int((datetime.now(timezone.utc) - start_time).total_seconds() * 1000)
            return LivenessCheckResult(
                domain=url.replace("https://", "").replace("http://", "").split("/")[0],
                is_live=False,
                error=str(e),
                response_time=response_time,
            )

        except Exception as e:
            response_time = int((datetime.now(timezone.utc) - start_time).total_seconds() * 1000)
            return LivenessCheckResult(
                domain=url.replace("https://", "").replace("http://", "").split("/")[0],
                is_live=False,
                error=str(e),
                response_time=response_time,
            )

    async def check_batch(self, domains: list[str]) -> list[LivenessCheckResult]:
        """
        Check multiple domains concurrently.

        Args:
            domains: List of domain names to check.

        Returns:
            List of LivenessCheckResult.
        """
        logger.info(f"Checking liveness of {len(domains)} domains")

        # Run concurrently with semaphore
        semaphore = asyncio.Semaphore(50)

        async def check_with_semaphore(domain: str) -> LivenessCheckResult:
            async with semaphore:
                return await self.check_domain(domain)

        results = await asyncio.gather(
            *[check_with_semaphore(d) for d in domains],
            return_exceptions=True,
        )

        # Handle any exceptions in results
        processed: list[LivenessCheckResult] = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                processed.append(
                    LivenessCheckResult(
                        domain=domains[i],
                        is_live=False,
                        error=f"Task exception: {result}",
                    )
                )
            else:
                assert isinstance(result, LivenessCheckResult)
                processed.append(result)

        return processed

    async def update_database(
        self,
        domain: str,
        result: LivenessCheckResult,
    ) -> None:
        """
        Update database with liveness check result.

        Args:
            domain: Domain name.
            result: Check result.
        """
        pool = await get_pool()

        try:
            # Update domain status
            await pool.execute("""
                UPDATE domains SET
                    is_live = $1,
                    status_code = $2,
                    response_time = $3,
                    last_checked = CURRENT_TIMESTAMP
                WHERE domain = $4
                """,
                result.is_live,
                result.status_code,
                result.response_time,
                domain,
            )

            # Log the check
            await pool.execute("""
                INSERT INTO discovery_log (action, domain, details, error_message)
                VALUES ($1, $2, $3, $4)
                """,
                "checked" if not result.error else "failed",
                domain,
                {
                    "is_live": result.is_live,
                    "status_code": result.status_code,
                    "response_time": result.response_time,
                },
                result.error,
            )

            logger.debug(
                f"Updated domain {domain}: "
                f"is_live={result.is_live}, status={result.status_code}"
            )

        except Exception as e:
            logger.error(f"Failed to update database for {domain}: {e}")

    async def update_batch(
        self,
        results: list[LivenessCheckResult],
    ) -> None:
        """
        Update database with multiple liveness check results.

        Args:
            results: List of check results.
        """
        tasks = [self.update_database(r.domain, r) for r in results]
        await asyncio.gather(*tasks, return_exceptions=True)
        logger.info(f"Updated {len(results)} domains in database")

    async def check_dead_domains(self, limit: int = 50) -> int:
        """
        Check all dead domains in database.

        Args:
            limit: Maximum domains to check.

        Returns:
            Number of domains checked.
        """
        pool = await get_pool()

        try:
            # Get dead domains
            rows = await pool.fetch("""
                SELECT domain FROM domains
                WHERE is_live = FALSE
                ORDER BY last_checked ASC
                LIMIT $1
                """,
                limit,
            )

            if not rows:
                logger.info("No dead domains to check")
                return 0

            domains = [row["domain"] for row in rows]
            results = await self.check_batch(domains)

            # Update database with results
            live_count = sum(1 for r in results if r.is_live)
            await self.update_batch(results)

            if live_count > 0:
                logger.info(f"Rediscovered {live_count} domains!")

            return len(domains)

        except Exception as e:
            logger.error(f"Failed to check dead domains: {e}")
            return 0

    def calculate_retry_delay(self, last_checked: datetime, is_live: bool) -> int:
        """
        Calculate retry delay based on status and last check time.

        Args:
            last_checked: When domain was last checked.
            is_live: Current liveness status.

        Returns:
            Seconds until next check.
        """
        from datetime import timezone

        if not last_checked.tzinfo:
            last_checked = last_checked.replace(tzinfo=timezone.utc)

        age = (datetime.now(timezone.utc) - last_checked).total_seconds()

        if is_live:
            # Live domains: check less frequently
            if age < 3600:  # Less than 1 hour
                return 1800  # 30 minutes
            elif age < 86400:  # Less than 24 hours
                return 21600  # 6 hours
            else:
                return 86400  # 24 hours
        else:
            # Dead domains: check more frequently
            if age < 3600:
                return 300  # 5 minutes
            elif age < 86400:
                return 1800  # 30 minutes
            else:
                return 7200  # 2 hours


# Convenience function for quick checks
async def check_domain_liveness(domain: str) -> LivenessCheckResult:
    """
    Check if a domain is live.

    Convenience wrapper for LivenessService.check_domain().

    Args:
        domain: Domain to check.

    Returns:
        LivenessCheckResult.
    """
    service = LivenessService()
    return await service.check_domain(domain)
