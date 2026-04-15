"""
Website Discovery Service for Bangladeshi Government Websites.

This service provides persistent, 24x7 URL discovery capabilities
optimized for discovering .gov.bd domains through recursive exploration.

Key Features:
    - Persistent database-backed state
    - Seed URL ingestion from .txt files
    - Domain-only discovery (not webpage crawling)
    - Liveness tracking with status codes
    - systemd service integration for always-on operation
    - Comprehensive logging with loguru
    - Asyncio-based concurrent crawling

Package Structure:
    src/
        config/     - Configuration settings (Pydantic models)
        database/   - Database connection, schema, and models
        crawler/    - Discovery engine and URL processing
        services/   - Background services (liveness, health, metrics)
        tools/      - CLI tools for operations
    main.py         - Service entry point
    tests/          - Unit and integration tests

Example:
    >>> from src.config.settings import settings
    >>> from src.database.connection import get_pool
    >>> from src.crawler.engine import DiscoveryEngine

    >>> # Run discovery
    >>> engine = DiscoveryEngine()
    >>> asyncio.run(engine.run())
"""

__version__ = "1.0.0"
__author__ = "URL Discovery Engine Team"
