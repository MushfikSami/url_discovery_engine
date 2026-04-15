"""
Configuration package for the Website Discovery Service.

This package provides centralized configuration management using
Pydantic v2 models with environment variable support.

Configuration Sources (in order of precedence):
    1. Hardcoded defaults in settings.py
    2. Environment variables (prefixed appropriately)
    3. config.yaml file
    4. .env file (via python-dotenv)

Usage:
    >>> from src.config.settings import settings
    >>> print(settings.database.host)
    >>> print(settings.crawler.max_concurrent_requests)
"""

from __future__ import annotations

from src.config.settings import (
    AppConfig,
    CrawlerSettings,
    DatabaseSettings,
    LivenessSettings,
    LoggingSettings,
    MetricsSettings,
    SchedulerSettings,
    settings,
)

__all__ = [
    "AppConfig",
    "CrawlerSettings",
    "DatabaseSettings",
    "LivenessSettings",
    "LoggingSettings",
    "MetricsSettings",
    "SchedulerSettings",
    "settings",
]
