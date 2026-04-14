"""
URL Discovery Engine - Bangladesh Government Website Discovery & Search System

A comprehensive system for discovering, crawling, indexing, and querying
Bangladesh government websites (.gov.bd) with AI-powered content analysis
and dual search system support.

Main Features:
    - Recursive domain discovery of .gov.bd websites
    - Async web crawling with content extraction
    - AI-powered summary and keyword generation
    - Tree Index (BM25) and Elasticsearch (Hybrid) search systems
    - Formal Bengali language support throughout
    - Configurable via environment variables and YAML

Package Structure:
    config/           - Configuration management with Pydantic validation
    logger/           - Logging setup with Loguru
    crawler/          - Web crawling and URL discovery
    agent/            - Tree Index ReAct Agent
    elasticsearch/    - Elasticsearch search engine
    eval/             - DeepEval evaluation framework

Quick Start:
    >>> from src.url_discovery_engine import settings
    >>> print(f"Running {settings.name} v{settings.version}")

    >>> from src.url_discovery_engine.logger import get_logger
    >>> logger = get_logger(__name__)
    >>> logger.info("Starting discovery process")

Author: URL Discovery Engine Team
Version: 1.0.0
License: Internal - Government of Bangladesh
"""

__version__ = "1.0.0"
__author__ = "URL Discovery Engine Team"
__license__ = "Internal - Government of Bangladesh"

# Export main components for convenient imports
from .config import (
    settings,
    AppConfig,
    DatabaseSettings,
    LLMSettings,
    TritonSettings,
    ElasticsearchSettings,
    CrawlerSettings,
)
from .logger import get_logger, configure_logger

__all__ = [
    # Version info
    "__version__",
    "__author__",
    "__license__",
    # Settings
    "settings",
    "AppConfig",
    "DatabaseSettings",
    "LLMSettings",
    "TritonSettings",
    "ElasticsearchSettings",
    "CrawlerSettings",
    # Logging
    "get_logger",
    "configure_logger",
]
