"""
Pytest fixtures for the Website Discovery Service.

This module provides shared fixtures for testing:
    - Mock database connections
    - Test configuration settings
    - Sample data for testing
    - Async test helpers

Usage:
    >>> @pytest.fixture
    >>> async def test_db():
    ...     async with create_test_pool() as pool:
    ...         yield pool
"""

from __future__ import annotations

import asyncio
from collections.abc import Generator
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.config.settings import (
    CrawlerSettings,
    DatabaseSettings,
    LivenessSettings,
    SchedulerSettings,
)
from src.database.models import Domain, SeedUrl, UrlQueue

# ============================================
# Configuration Fixtures
# ============================================

@pytest.fixture
def test_database_settings() -> DatabaseSettings:
    """Provide test database settings."""
    return DatabaseSettings(
        host="localhost",
        port=5432,
        user="test_user",
        password="test_password",
        name="test_db",
    )


@pytest.fixture
def test_crawler_settings() -> CrawlerSettings:
    """Provide test crawler settings."""
    return CrawlerSettings(
        max_concurrent_requests=10,
        timeout=5,
        politeness_delay=0.1,
    )


@pytest.fixture
def test_scheduler_settings() -> SchedulerSettings:
    """Provide test scheduler settings."""
    return SchedulerSettings(
        check_interval=60,
        max_retries=2,
        retry_delay=30,
    )


@pytest.fixture
def test_liveness_settings() -> LivenessSettings:
    """Provide test liveness settings."""
    return LivenessSettings(
        timeout=5,
        verify_ssl=False,
    )


# ============================================
# Database Fixtures
# ============================================

@pytest.fixture
def mock_pool() -> AsyncMock:
    """Provide a mock asyncpg pool."""
    pool = AsyncMock()
    pool.acquire = AsyncMock()
    return pool


@pytest.fixture
def mock_connection() -> AsyncMock:
    """Provide a mock database connection."""
    conn = AsyncMock()
    conn.fetch = AsyncMock(return_value=[])
    conn.fetchone = AsyncMock(return_value=None)
    conn.execute = AsyncMock(return_value=None)
    return conn


# ============================================
# Sample Data Fixtures
# ============================================

@pytest.fixture
def sample_domain() -> Domain:
    """Provide a sample Domain instance."""
    return Domain(
        domain="example.gov.bd",
        protocol="https",
        is_live=True,
        status_code=200,
        response_time=150,
    )


@pytest.fixture
def sample_domains() -> list[Domain]:
    """Provide sample domains for testing."""
    return [
        Domain(domain="moef.gov.bd", protocol="https", is_live=True),
        Domain(domain="dps.gov.bd", protocol="https", is_live=True),
        Domain(domain="old-site.gov.bd", protocol="https", is_live=False),
    ]


@pytest.fixture
def sample_seed_url() -> SeedUrl:
    """Provide a sample SeedUrl instance."""
    return SeedUrl(
        url="https://bangladesh.gov.bd",
        source="manual",
    )


@pytest.fixture
def sample_seed_urls() -> list[SeedUrl]:
    """Provide sample seed URLs."""
    return [
        SeedUrl(url="https://bangladesh.gov.bd", source="manual"),
        SeedUrl(url="https://ministry.gov.bd", source="batch"),
    ]


@pytest.fixture
def sample_queue_item() -> UrlQueue:
    """Provide a sample UrlQueue instance."""
    return UrlQueue(
        url="https://example.gov.bd/about",
        priority=2,
        status="pending",
    )


# ============================================
# Mock Objects Fixtures
# ============================================

@pytest.fixture
def mock_http_response() -> MagicMock:
    """Provide a mock HTTP response object."""
    response = MagicMock()
    response.status = 200
    response.text = AsyncMock(return_value="<html><body>Test</body></html>")
    return response


@pytest.fixture
def mock_aiohttp_session() -> AsyncMock:
    """Provide a mock aiohttp ClientSession."""
    session = AsyncMock()
    session.get = AsyncMock()
    return session


@pytest.fixture
def mock_beautifulsoup() -> MagicMock:
    """Provide a mock BeautifulSoup object."""
    soup = MagicMock()
    soup.find_all = MagicMock(return_value=[MagicMock(href="/link")])
    return soup


# ============================================
# Async Test Helpers
# ============================================

@pytest.fixture
def event_loop() -> Generator[Any, Any, Any]:
    """Create an event loop for async tests."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


# ============================================
# Context Manager Fixtures
# ============================================

@pytest.fixture
def patch_settings(test_database_settings: DatabaseSettings) -> Generator[Any, Any, Any]:
    """Patch settings with test configuration."""
    with patch("src.config.settings.settings", test_database_settings):
        with patch("src.database.settings.settings", test_database_settings):
            yield


@pytest.fixture
def patch_asyncpg(mock_pool: AsyncMock) -> Generator[Any, Any, Any]:
    """Patch asyncpg.create_pool with mock."""
    with patch("asyncpg.create_pool", AsyncMock(return_value=mock_pool)):
        yield mock_pool
