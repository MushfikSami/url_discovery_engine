"""
Configuration package for URL Discovery Engine.

This package provides centralized configuration management with:
- Pydantic v2 models for type-safe settings
- Environment variable support via python-dotenv
- YAML configuration file for parameterized values
- Automatic validation of all configuration values

Submodules:
    settings: Main settings classes with Pydantic validation
"""

from .settings import (
    settings,
    AppConfig,
    DatabaseSettings,
    LLMSettings,
    TritonSettings,
    ElasticsearchSettings,
    GradioSettings,
    CrawlerSettings,
    BanglapediaSettings,
    AgentSettings,
    ElasticsearchEngineSettings,
    EvaluationSettings,
    LoggingSettings,
)

__all__ = [
    # Main settings instance
    "settings",
    # Config classes
    "AppConfig",
    "DatabaseSettings",
    "LLMSettings",
    "TritonSettings",
    "ElasticsearchSettings",
    "GradioSettings",
    "CrawlerSettings",
    "BanglapediaSettings",
    "AgentSettings",
    "ElasticsearchEngineSettings",
    "EvaluationSettings",
    "LoggingSettings",
]
