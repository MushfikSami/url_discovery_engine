"""
Configuration settings for the Website Discovery Service.

This module defines all configuration using Pydantic v2 models with
automatic environment variable loading and validation.

Configuration is organized into nested settings classes:
    - AppConfig: Top-level application settings
    - DatabaseSettings: PostgreSQL connection and pool configuration
    - CrawlerSettings: Discovery engine parameters
    - SchedulerSettings: Task scheduling and queue management
    - LivenessSettings: Domain status check configuration
    - LoggingSettings: Loguru logging setup
    - MetricsSettings: Optional metrics collection

Environment variables are automatically loaded from .env file via
python-dotenv and can also be set externally.

Example:
    >>> from src.config.settings import settings
    >>> settings.database.host
    'localhost'
    >>> settings.crawler.max_concurrent_requests
    50
"""

from __future__ import annotations

from datetime import datetime
from functools import lru_cache
from typing import Any, Literal

from dateutil import tz  # type: ignore[import-untyped]
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class DatabaseSettings(BaseSettings):
    """
    PostgreSQL database connection settings.

    Attributes:
        host: Database server hostname or IP address.
            Defaults to 'localhost'.
        port: Database server port. Defaults to 5432.
        user: Database username. Defaults to 'url_discovery'.
        password: Database password. Defaults to 'password'.
        name: Database name. Defaults to 'url_discovery_db'.
        pool_size: Number of connections in the pool.
            Defaults to 10.
        max_overflow: Maximum additional connections beyond pool_size.
            Defaults to 20.
        pool_timeout: Seconds to wait for a connection from pool.
            Defaults to 30.
        pool_recycle: Seconds after which to recycle connections.
            Defaults to 1800 (30 minutes).

    Example:
        >>> db = DatabaseSettings()
        >>> db.connection_string
        'postgresql://url_discovery:password@localhost:5432/url_discovery_db'
    """

    model_config = SettingsConfigDict(
        env_prefix="DB_",
        env_file=".env",
        extra="ignore",
    )

    host: str = Field(default="localhost", description="Database host")
    port: int = Field(default=5432, ge=1, le=65535, description="Database port")
    user: str = Field(default="url_discovery", description="Database user")
    password: str = Field(default="password", description="Database password")
    name: str = Field(default="url_discovery_db", description="Database name")
    pool_size: int = Field(default=10, ge=1, description="Connection pool size")
    max_overflow: int = Field(default=20, ge=0, description="Max overflow connections")
    pool_timeout: int = Field(default=30, ge=1, description="Pool timeout seconds")
    pool_recycle: int = Field(default=1800, ge=1, description="Connection recycle seconds")

    @property
    def connection_string(self) -> str:
        """
        Generate PostgreSQL connection string.

        Returns:
            Connection string in format:
            postgresql://user:password@host:port/database
        """
        return (
            f"postgresql://{self.user}:{self.password}"
            f"@{self.host}:{self.port}/{self.name}"
        )

    def __repr__(self) -> str:
        """Return safe representation (masked password)."""
        return (
            f"DatabaseSettings(host={self.host!r}, port={self.port}, "
            f"user={self.user!r}, name={self.name!r}, pool_size={self.pool_size})"
        )


class CrawlerSettings(BaseSettings):
    """
    Crawler discovery engine settings.

    Attributes:
        seed_file: Path to seed URLs file (.txt format).
            Defaults to 'seeds/input.txt'.
        max_concurrent_requests: Maximum concurrent HTTP requests.
            Must be between 1 and 500. Defaults to 50.
        timeout: HTTP request timeout in seconds.
            Must be between 1 and 120. Defaults to 15.
        politeness_delay: Delay between requests to same domain.
            In seconds, must be >= 0. Defaults to 0.2.
        user_agent: HTTP User-Agent header. Defaults to
            'BD-Gov-Discovery-Service/1.0'.

    Example:
        >>> crawler = CrawlerSettings()
        >>> crawler.max_concurrent_requests
        50
    """

    model_config = SettingsConfigDict(
        env_prefix="CRAWLER_",
        env_file=".env",
        extra="ignore",
    )

    seed_file: str = Field(default="seeds/input.txt", description="Seed file path")
    max_concurrent_requests: int = Field(
        default=50, ge=1, le=500, description="Max concurrent requests"
    )
    timeout: int = Field(
        default=15, ge=1, le=120, description="Request timeout seconds"
    )
    politeness_delay: float = Field(
        default=0.2, ge=0, description="Politeness delay seconds"
    )
    user_agent: str = Field(
        default="BD-Gov-Discovery-Service/1.0", description="User-Agent string"
    )

    # Domain filtering
    allowed_tlds: list[str] = Field(
        default=[".gov.bd"], description="Allowed TLDs"
    )

    excluded_tags: list[str] = Field(
        default=["nav", "footer", "header", "aside"], description="HTML tags to skip"
    )

    # URL normalization
    normalize_urls: bool = Field(default=True, description="Normalize URLs")
    strip_fragment: bool = Field(default=True, description="Strip URL fragments")
    lowercase_domains: bool = Field(default=True, description="Lowercase domains")

    @field_validator("max_concurrent_requests")
    @classmethod
    def validate_concurrency(cls, value: int) -> int:
        """Validate concurrency is positive."""
        if value < 1:
            raise ValueError("max_concurrent_requests must be >= 1")
        return value

    def __repr__(self) -> str:
        """Return representation."""
        return (
            f"CrawlerSettings(max_concurrent_requests={self.max_concurrent_requests}, "
            f"timeout={self.timeout})"
        )


class SchedulerSettings(BaseSettings):
    """
    Task scheduler and queue management settings.

    Attributes:
        check_interval: Seconds between queue processing cycles.
            Must be >= 10. Defaults to 300 (5 minutes).
        max_retries: Maximum retry attempts for failed URLs.
            Defaults to 3.
        retry_delay: Seconds between retries. Defaults to 60.

    Example:
        >>> scheduler = SchedulerSettings()
        >>> scheduler.check_interval
        300
    """

    model_config = SettingsConfigDict(
        env_prefix="SCHEDULER_",
        env_file=".env",
        extra="ignore",
    )

    check_interval: int = Field(
        default=300, ge=10, description="Queue check interval seconds"
    )
    max_retries: int = Field(default=3, ge=1, description="Max retry attempts")
    retry_delay: int = Field(default=60, ge=1, description="Retry delay seconds")

    # Queue management
    queue_batch_size: int = Field(default=100, ge=1, description="Batch size")
    queue_cleanup_interval: int = Field(default=3600, ge=60, description="Cleanup interval")
    max_queue_size: int = Field(default=50000, ge=1000, description="Maximum queue size")

    # Priority weights
    priority_seed: int = Field(default=1, ge=1, le=5, description="Seed priority")
    priority_rediscovered: int = Field(default=2, ge=1, le=5, description="Rediscovered priority")
    priority_regular: int = Field(default=3, ge=1, le=5, description="Regular priority")
    priority_liveness_check: int = Field(default=4, ge=1, le=5, description="Liveness priority")

    def __repr__(self) -> str:
        """Return representation."""
        return f"SchedulerSettings(check_interval={self.check_interval})"


class LivenessSettings(BaseSettings):
    """
    Domain liveness check settings.

    Attributes:
        http_check: Whether to check HTTP domains. Defaults to True.
        https_check: Whether to check HTTPS domains. Defaults to True.
        timeout: Liveness check timeout in seconds.
            Defaults to 7.

    Example:
        >>> liveness = LivenessSettings()
        >>> liveness.http_check
        True
    """

    model_config = SettingsConfigDict(
        env_prefix="LIVENESS_",
        env_file=".env",
        extra="ignore",
    )

    http_check: bool = Field(default=True, description="Enable HTTP checks")
    https_check: bool = Field(default=True, description="Enable HTTPS checks")
    timeout: int = Field(default=7, ge=1, le=30, description="Check timeout seconds")

    # Status code interpretation
    live_status_codes: list[int] = Field(
        default=[200, 201, 202, 204], description="HTTP codes considered live"
    )

    # Redirect handling
    follow_redirects: bool = Field(default=True, description="Follow redirects")
    max_redirects: int = Field(default=5, ge=1, le=10, description="Max redirects")

    # SSL verification
    verify_ssl: bool = Field(default=True, description="Verify SSL certificates")

    def __repr__(self) -> str:
        """Return representation."""
        return (
            f"LivenessSettings(http_check={self.http_check}, "
            f"https_check={self.https_check}, timeout={self.timeout})"
        )


class LoggingSettings(BaseSettings):
    """
    Loguru logging configuration.

    Attributes:
        level: Log level (DEBUG, INFO, WARNING, ERROR, CRITICAL).
            Defaults to INFO.
        file: Log file path. Defaults to 'logs/discovery.log'.
        rotation: File rotation size. Defaults to '10 MB'.
        retention: Days to keep log files. Defaults to '10 days'.

    Example:
        >>> logging_config = LoggingSettings()
        >>> logging_config.level
        'INFO'
    """

    model_config = SettingsConfigDict(
        env_prefix="LOG_",
        env_file=".env",
        extra="ignore",
    )

    level: str = Field(default="INFO", description="Log level")
    file: str = Field(default="logs/discovery.log", description="Log file path")
    rotation: str = Field(default="10 MB", description="File rotation")
    retention: str = Field(default="10 days", description="Log retention")

    # Console output
    console_enabled: bool = Field(default=True, description="Enable console output")
    console_level: str = Field(default="INFO", description="Console log level")

    def __repr__(self) -> str:
        """Return representation."""
        return f"LoggingSettings(level={self.level!r}, file={self.file!r})"


class MetricsSettings(BaseSettings):
    """
    Optional metrics collection settings.

    Attributes:
        enabled: Whether to collect metrics. Defaults to False.
        port: HTTP port for metrics endpoint. Defaults to 8080.

    Example:
        >>> metrics = MetricsSettings()
        >>> metrics.enabled
        False
    """

    model_config = SettingsConfigDict(
        env_prefix="METRICS_",
        env_file=".env",
        extra="ignore",
    )

    enabled: bool = Field(default=False, description="Enable metrics")
    port: int = Field(default=8080, ge=1, le=65535, description="Metrics port")

    # Collection interval
    collection_interval: int = Field(default=60, ge=10, description="Collection interval")

    # Export format
    export_format: Literal["prometheus", "json", "none"] = Field(
        default="prometheus", description="Export format"
    )

    # Metrics to collect
    collect_discovery_count: bool = Field(default=True, description="Collect discovery count")
    collect_liveness_checks: bool = Field(default=True, description="Collect liveness checks")
    collect_queue_size: bool = Field(default=True, description="Collect queue size")
    collect_error_rate: bool = Field(default=True, description="Collect error rate")
    collect_response_times: bool = Field(default=True, description="Collect response times")

    def __repr__(self) -> str:
        """Return representation."""
        return f"MetricsSettings(enabled={self.enabled}, port={self.port})"


class AppConfig(BaseSettings):
    """
    Top-level application configuration.

    This class aggregates all nested settings and provides
    centralized access to configuration.

    Attributes:
        database: PostgreSQL database settings.
        crawler: Crawler discovery settings.
        scheduler: Task scheduler settings.
        liveness: Liveness check settings.
        logging: Logging configuration.
        metrics: Metrics collection settings.

    Example:
        >>> config = AppConfig()
        >>> config.database.host
        'localhost'
        >>> config.crawler.max_concurrent_requests
        50
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="",
        extra="ignore",
    )

    database: DatabaseSettings = Field(default_factory=DatabaseSettings)
    crawler: CrawlerSettings = Field(default_factory=CrawlerSettings)
    scheduler: SchedulerSettings = Field(default_factory=SchedulerSettings)
    liveness: LivenessSettings = Field(default_factory=LivenessSettings)
    logging: LoggingSettings = Field(default_factory=LoggingSettings)
    metrics: MetricsSettings = Field(default_factory=MetricsSettings)

    # Application metadata
    name: str = Field(default="website_discovery", description="Application name")
    version: str = Field(default="1.0.0", description="Application version")
    debug: bool = Field(default=False, description="Debug mode")

    # Timezone settings - Bangladesh Standard Time (UTC+6)
    timezone: str = Field(
        default="Asia/Dhaka", description="Application timezone"
    )

    @property
    def tz(self) -> tz.tzfile:
        """
        Get timezone object for Bangladesh timezone.

        Returns:
            Dateutil tzfile object for configured timezone.
        """
        return tz.gettz(self.timezone)

    def now(self) -> datetime:
        """
        Get current time in configured timezone.

        Returns:
            datetime with timezone info.
        """
        from datetime import datetime

        return datetime.now(self.tz)

    @field_validator("debug", mode="before")
    @classmethod
    def parse_debug(cls, value: Any) -> bool:
        """Parse debug flag from various input types."""
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.lower() in ("true", "1", "yes")
        return bool(value)

    def __repr__(self) -> str:
        """Return representation."""
        return f"AppConfig(name={self.name!r}, version={self.version!r}, debug={self.debug})"


# Global settings instance (lazy-loaded)
@lru_cache(maxsize=1)
def get_settings() -> AppConfig:
    """
    Get the global settings instance.

    Uses lru_cache to ensure only one settings instance exists
    per application, preventing duplicate loading.

    Returns:
        AppConfig instance with all configuration.

    Example:
        >>> settings = get_settings()
        >>> settings.database.connection_string
    """
    return AppConfig()


# Convenience import for module-level access
settings = get_settings()
