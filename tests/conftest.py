"""
Pytest configuration and shared fixtures.

This file defines fixtures and configuration that are shared across
all test modules in the project.

Usage:
    The fixtures defined here are automatically available in all test files.
    pytest will discover and load this file automatically.
"""

from __future__ import annotations

from typing import Generator
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def mock_settings() -> MagicMock:
    """
    Provide a mock settings object for testing.

    Returns:
        MagicMock configured with common settings attributes.
    """
    mock = MagicMock()
    mock.database.host = "localhost"
    mock.database.port = 5432
    mock.database.user = "test_user"
    mock.database.password = "test_password"
    mock.database.bd_gov_db = "test_bd_gov_db"
    mock.database.gov_bd_db = "test_gov_bd_db"
    mock.database.banglapedia_db = "test_banglapedia_db"
    mock.llm.base_url = "http://localhost:5000/v1"
    mock.llm.api_key = "test-key"
    mock.llm.model_name = "qwen35"
    mock.triton.url = "localhost:7000"
    mock.elasticsearch.host = "http://localhost:9200"
    mock.elasticsearch.index_name = "test_index"
    mock.crawler.max_concurrent_requests = 10
    mock.crawler.timeout = 5
    mock.crawler.user_agent = "Test-Agent/1.0"
    mock.banglapedia.language = "bn"
    mock.agent.max_hops = 3
    mock.es_engine.top_k = 2
    mock.evaluation.threshold = 0.5
    mock.logging.level = "DEBUG"
    return mock


@pytest.fixture
def mock_async_crawler() -> Generator[MagicMock, None, None]:
    """
    Provide a mock async crawler for testing.

    Returns:
        MagicMock simulating AsyncWebCrawler behavior.
    """
    with patch("crawl4ai.AsyncWebCrawler") as mock_crawler:
        mock_instance = MagicMock()
        mock_instance.__aenter__.return_value = mock_instance
        mock_instance.__aexit__.return_value = None
        mock_instance.arun.return_value.success = True
        mock_instance.arun.return_value.markdown = "Test content"
        mock_instance.arun.return_value.title = "Test Title"
        mock_crawler.return_value = mock_instance
        yield mock_crawler


@pytest.fixture
def mock_database_connection() -> Generator[MagicMock, None, None]:
    """
    Provide a mock database connection for testing.

    Returns:
        MagicMock simulating psycopg2 connection.
    """
    with patch("psycopg2.connect") as mock_connect:
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = []
        mock_cursor.fetchone.return_value = (0,)
        mock_conn.cursor.return_value = mock_cursor
        mock_connect.return_value = mock_conn
        yield mock_connect


@pytest.fixture
def mock_triton_client() -> Generator[MagicMock, None, None]:
    """
    Provide a mock Triton client for testing.

    Returns:
        MagicMock simulating Triton HTTP client.
    """
    with patch("tritonclient.http.InferenceServerClient") as mock_client:
        mock_instance = MagicMock()
        mock_instance.is_server_ready.return_value = True
        mock_instance.infer.return_value.as_numpy.return_value = [[0.1] * 768]
        mock_client.return_value = mock_instance
        yield mock_client


@pytest.fixture
def mock_es_client() -> Generator[MagicMock, None, None]:
    """
    Provide a mock Elasticsearch client for testing.

    Returns:
        MagicMock simulating Elasticsearch client.
    """
    with patch("elasticsearch.Elasticsearch") as mock_es:
        mock_instance = MagicMock()
        mock_instance.indices.exists.return_value = False
        mock_instance.indices.create.return_value = True
        mock_es.return_value = mock_instance
        yield mock_es


@pytest.fixture
def sample_query() -> str:
    """
    Provide a sample Bengali query for testing.

    Returns:
        Sample government-related query in Bengali.
    """
    return "বয়স্ক ভাতা করার ক্ষেত্রে কি জন্ম নিবন্ধন আবশ্যক?"


@pytest.fixture
def sample_markdown() -> str:
    """
    Provide sample markdown content for testing.

    Returns:
        Sample Bengali markdown content.
    """
    return """
# Test Article

**সারসংক্ষেপ (Summary):** This is a test article.

**কিওয়ার্ড (Keywords):** test, sample, article

বিস্তারিত তথ্যের জন্য এখানে পড়ুন।
"""
