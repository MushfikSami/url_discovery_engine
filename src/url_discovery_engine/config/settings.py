"""
Configuration settings for URL Discovery Engine.

This module provides centralized configuration management using:
- Pydantic v2 models for type validation
- Environment variable loading via python-dotenv
- YAML configuration file for overridable parameters

Usage:
    from src.url_discovery_engine.config.settings import settings
    print(settings.database.host)
"""

import os
from functools import lru_cache
from typing import Any

import yaml
from dotenv import load_dotenv
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class DatabaseSettings(BaseSettings):
    """Database connection settings with validation."""

    model_config = SettingsConfigDict(
        env_prefix="DB_",
        env_nested_delimiter="__",
        extra="ignore"
    )

    host: str = Field(default="localhost", description="Database host")
    port: int = Field(default=5432, gt=0, lt=65535, description="Database port")
    user: str = Field(default="postgres", description="Database username")
    password: str = Field(default="password", description="Database password")

    # Database names for different modules
    bd_gov_db: str = Field(default="bd_gov_db", description="BD Gov database name")
    gov_bd_db: str = Field(default="gov_bd_db", description="Gov BD database name")
    banglapedia_db: str = Field(default="banglapedia_db", description="Banglapedia database name")

    @property
    def bd_gov_connection_string(self) -> str:
        """Get PostgreSQL connection string for BD Gov DB."""
        return f"postgresql://{self.user}:{self.password}@{self.host}:{self.port}/{self.bd_gov_db}"

    @property
    def gov_bd_connection_string(self) -> str:
        """Get PostgreSQL connection string for Gov BD DB."""
        return f"postgresql://{self.user}:{self.password}@{self.host}:{self.port}/{self.gov_bd_db}"

    @property
    def banglapedia_connection_string(self) -> str:
        """Get PostgreSQL connection string for Banglapedia DB."""
        return f"postgresql://{self.user}:{self.password}@{self.host}:{self.port}/{self.banglapedia_db}"


class LLMSettings(BaseSettings):
    """LLM service settings for vLLM."""

    model_config = SettingsConfigDict(
        env_prefix="LLM_",
        extra="ignore"
    )

    base_url: str = Field(
        default="http://localhost:5000/v1",
        description="vLLM server URL"
    )
    api_key: str = Field(
        default="no-key",
        description="API key for vLLM (empty for local)"
    )
    model_name: str = Field(
        default="qwen35",
        description="LLM model name"
    )


class TritonSettings(BaseSettings):
    """Triton Inference Server settings for embeddings."""

    model_config = SettingsConfigDict(
        env_prefix="TRITON_",
        extra="ignore"
    )

    url: str = Field(
        default="localhost:7000",
        description="Triton server URL"
    )


class ElasticsearchSettings(BaseSettings):
    """Elasticsearch connection settings."""

    model_config = SettingsConfigDict(
        env_prefix="ES_",
        extra="ignore"
    )

    host: str = Field(
        default="http://localhost:9200",
        description="Elasticsearch host URL"
    )
    index_name: str = Field(
        default="bd_gov_chunks",
        description="Default index name"
    )


class GradioSettings(BaseSettings):
    """Gradio UI server settings."""

    model_config = SettingsConfigDict(
        extra="ignore"
    )

    server_name: str = Field(
        default="0.0.0.0",
        description="Server bind address"
    )
    server_port: int = Field(
        default=7860,
        gt=1024,
        lt=65535,
        description="Server port"
    )


class CrawlerSettings(BaseSettings):
    """Web crawler configuration settings."""

    model_config = SettingsConfigDict(
        extra="ignore"
    )

    # Concurrency
    max_concurrent_requests: int = Field(
        default=30,
        gt=0,
        lt=1000,
        description="Maximum concurrent HTTP requests"
    )
    liveness_max_concurrent: int = Field(
        default=100,
        gt=0,
        lt=1000,
        description="Maximum concurrent liveness checks"
    )

    # Timeouts (seconds)
    timeout: int = Field(
        default=15,
        gt=0,
        description="HTTP request timeout"
    )
    liveness_timeout: int = Field(
        default=7,
        gt=0,
        description="Liveness check timeout"
    )

    # Politeness
    politeness_delay: float = Field(
        default=0.5,
        gt=0,
        description="Delay between crawls (seconds)"
    )

    # User-Agent
    user_agent: str = Field(
        default="BD-Gov-Ecosystem-Mapper/3.0 (Research)",
        description="HTTP User-Agent header"
    )

    # Content extraction
    word_count_threshold: int = Field(
        default=20,
        ge=0,
        description="Minimum word count threshold"
    )

    # Excluded HTML tags
    excluded_tags: list[str] = Field(
        default_factory=lambda: [
            "nav", "footer", "header", "aside",
            "form", "script", "style", "noscript"
        ],
        description="HTML tags to exclude during crawling"
    )


class BanglapediaSettings(BaseSettings):
    """Banglapedia crawler settings."""

    model_config = SettingsConfigDict(
        extra="ignore"
    )

    language: str = Field(
        default="bn",
        pattern="^(bn|en)$",
        description="Language code (bn or en)"
    )
    css_selector: str = Field(
        default="#mw-content-text",
        description="CSS selector for content extraction"
    )
    word_count_threshold: int = Field(
        default=15,
        ge=0,
        description="Minimum word count threshold"
    )
    api_limit: int = Field(
        default=500,
        gt=0,
        lt=1000,
        description="MediaWiki API pagination limit"
    )


class AgentSettings(BaseSettings):
    """Tree Index Agent settings."""

    model_config = SettingsConfigDict(
        extra="ignore"
    )

    max_hops: int = Field(default=5, gt=0, description="Maximum reasoning hops")
    safety_breaker: int = Field(default=15, gt=0, description="Maximum loop iterations")
    tree_search_top_n: int = Field(default=5, gt=0, description="Top N results for tree search")
    chunk_size: int = Field(default=2000, gt=0, description="Text chunk size")
    chunk_overlap: int = Field(default=300, gt=0, description="Text chunk overlap")
    escape_hatch_threshold: int = Field(default=3, gt=0, description="Search attempts before escape hatch")


class ElasticsearchEngineSettings(BaseSettings):
    """Elasticsearch Engine search settings."""

    model_config = SettingsConfigDict(
        extra="ignore"
    )

    top_k: int = Field(default=4, gt=0, description="Number of results to return")
    num_candidates: int = Field(default=50, gt=0, description="KNN num_candidates")
    vector_boost: float = Field(default=0.5, gt=0, lt=1, description="Vector search weight")

    # Field boosts for multi_match
    field_boosts: dict[str, float] = Field(
        default_factory=lambda: {
            "summary": 2.0,
            "keywords": 1.5,
            "raw_markdown": 1.0
        },
        description="Field boosting weights"
    )

    # Chunking settings
    chunk_size: int = Field(default=1500, gt=0, description="Ingestion chunk size")
    chunk_overlap: int = Field(default=200, gt=0, description="Ingestion chunk overlap")
    batch_size: int = Field(default=250, gt=0, description="Ingestion batch size")


class EvaluationSettings(BaseSettings):
    """DeepEval evaluation settings."""

    model_config = SettingsConfigDict(
        extra="ignore"
    )

    threshold: float = Field(default=0.7, ge=0, le=1, description="Metric threshold")
    queries_file: str = Field(default="DeepEval/queries.csv", description="Test queries file")
    output_file: str = Field(default="DeepEval/evaluated_queries.csv", description="Results output file")


class LoggingSettings(BaseSettings):
    """Logging configuration settings."""

    model_config = SettingsConfigDict(
        extra="ignore"
    )

    level: str = Field(default="INFO", description="Logging level")
    file: str = Field(default="logs/app.log", description="Log file path")


class AppConfig(BaseSettings):
    """
    Main application configuration that aggregates all settings.

    This class loads the YAML configuration file and merges it with
    environment variables for a complete configuration setup.

    Example:
        >>> config = AppConfig()
        >>> print(config.llm.model_name)
        >>> print(config.crawler.max_concurrent_requests)
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

    # Application metadata
    name: str = "url_discovery_engine"
    version: str = "1.0.0"
    debug: bool = False

    # Load settings from environment variables
    database: DatabaseSettings = Field(default_factory=DatabaseSettings)
    llm: LLMSettings = Field(default_factory=LLMSettings)
    triton: TritonSettings = Field(default_factory=TritonSettings)
    elasticsearch: ElasticsearchSettings = Field(default_factory=ElasticsearchSettings)
    gradio: GradioSettings = Field(default_factory=GradioSettings)
    crawler: CrawlerSettings = Field(default_factory=CrawlerSettings)
    banglapedia: BanglapediaSettings = Field(default_factory=BanglapediaSettings)
    agent: AgentSettings = Field(default_factory=AgentSettings)
    es_engine: ElasticsearchEngineSettings = Field(default_factory=ElasticsearchEngineSettings)
    evaluation: EvaluationSettings = Field(default_factory=EvaluationSettings)
    logging: LoggingSettings = Field(default_factory=LoggingSettings)

    # Bloat keywords for Bengali text cleaning
    bloat_keywords: list[str] = Field(
        default_factory=lambda: [
            "অফিসের ধরণ নির্বাচন করুন",
            "এক্সেসিবিলিটি মেনুতে যান",
            "বাংলাদেশ জাতীয় তথ্য বাতায়ন",
            "অফিস স্তর নির্বাচন করুন",
            "বিভাগ নির্বাচন করুন",
            "জেলা নির্বাচন করুন",
            "উপজেলা নির্বাচন করুন",
            "হটলাইন",
            "মেনু নির্বাচন করুন",
            "জরুরি সেবা নম্বরসমূহ",
            "ফন্ট বৃদ্ধি ফন্ট হ্রাস",
            "স্ক্রিন রিডার ডাউনলোড করুন",
            "© 2026 সর্বস্বত্ব সংরক্ষিত",
            "পরিকল্পনা এবং বাস্তবায়ন"
        ]
    )

    @field_validator("debug", mode="before")
    @classmethod
    def parse_debug(cls, v: Any) -> bool:
        """Parse debug flag from various input types."""
        if isinstance(v, bool):
            return v
        if isinstance(v, str):
            return v.lower() in ("true", "1", "yes", "on")
        return bool(v)


# Global settings instance
settings: AppConfig = AppConfig()
