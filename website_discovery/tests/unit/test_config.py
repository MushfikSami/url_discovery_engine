"""
Unit tests for configuration settings.

This module tests the Pydantic configuration settings including:
    - Environment variable loading
    - Type validation
    - Default values
    - Connection string generation
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.config.settings import (
    CrawlerSettings,
    DatabaseSettings,
    LivenessSettings,
    SchedulerSettings,
)


class TestDatabaseSettings:
    """Tests for DatabaseSettings class."""

    @pytest.fixture
    def settings(self) -> DatabaseSettings:
        """Provide a DatabaseSettings instance."""
        return DatabaseSettings()

    def test_default_values(self, settings: DatabaseSettings) -> None:
        """Test that default values are correctly set."""
        assert settings.host == "localhost"
        assert settings.port == 5432
        # User may vary based on environment
        assert settings.port == 5432
        assert settings.name == "url_discovery_db"

    def test_connection_string(self, settings: DatabaseSettings) -> None:
        """Test connection string generation."""
        conn_string = settings.connection_string
        # Verify connection string contains expected components
        assert "postgresql://" in conn_string
        assert settings.host in conn_string
        assert str(settings.port) in conn_string
        assert settings.name in conn_string

    def test_port_validation(self) -> None:
        """Test that port must be between 1 and 65535."""
        with pytest.raises(ValidationError):
            DatabaseSettings(port=0)

        with pytest.raises(ValidationError):
            DatabaseSettings(port=70000)

    def test_custom_values(self) -> None:
        """Test custom configuration values."""
        settings = DatabaseSettings(
            host="db.example.com",
            port=5433,
            user="admin",
            password="secret123",
            name="custom_db",
        )
        assert settings.host == "db.example.com"
        assert settings.port == 5433
        assert settings.user == "admin"
        assert settings.name == "custom_db"

    def test_pool_settings(self) -> None:
        """Test connection pool settings."""
        settings = DatabaseSettings(
            pool_size=20,
            max_overflow=30,
            pool_timeout=60,
        )
        assert settings.pool_size == 20
        assert settings.max_overflow == 30
        assert settings.pool_timeout == 60


class TestCrawlerSettings:
    """Tests for CrawlerSettings class."""

    @pytest.fixture
    def settings(self) -> CrawlerSettings:
        """Provide a CrawlerSettings instance."""
        return CrawlerSettings()

    def test_default_values(self, settings: CrawlerSettings) -> None:
        """Test default crawler settings."""
        assert settings.max_concurrent_requests == 50
        assert settings.timeout == 15
        assert settings.politeness_delay == 0.2
        assert settings.user_agent == "BD-Gov-Discovery-Service/1.0"
        assert settings.seed_file == "seeds/input.txt"

    def test_concurrency_validation(self) -> None:
        """Test that concurrency values are positive."""
        with pytest.raises(ValidationError):
            CrawlerSettings(max_concurrent_requests=0)

        with pytest.raises(ValidationError):
            CrawlerSettings(max_concurrent_requests=-1)

    def test_max_concurrency_limit(self) -> None:
        """Test maximum concurrency limit."""
        with pytest.raises(ValidationError):
            CrawlerSettings(max_concurrent_requests=501)

    def test_timeout_validation(self) -> None:
        """Test timeout validation."""
        with pytest.raises(ValidationError):
            CrawlerSettings(timeout=0)

        with pytest.raises(ValidationError):
            CrawlerSettings(timeout=121)

    def test_custom_values(self) -> None:
        """Test custom crawler configuration."""
        settings = CrawlerSettings(
            max_concurrent_requests=100,
            timeout=30,
            politeness_delay=1.0,
        )
        assert settings.max_concurrent_requests == 100
        assert settings.timeout == 30
        assert settings.politeness_delay == 1.0

    def test_allowed_tlds(self) -> None:
        """Test allowed TLDs default and custom values."""
        settings = CrawlerSettings()
        assert ".gov.bd" in settings.allowed_tlds

        custom_settings = CrawlerSettings(allowed_tlds=[".edu.bd", ".org.bd"])
        assert custom_settings.allowed_tlds == [".edu.bd", ".org.bd"]

    def test_excluded_tags(self) -> None:
        """Test excluded HTML tags."""
        settings = CrawlerSettings()
        assert "nav" in settings.excluded_tags
        assert "footer" in settings.excluded_tags


class TestSchedulerSettings:
    """Tests for SchedulerSettings class."""

    @pytest.fixture
    def settings(self) -> SchedulerSettings:
        """Provide a SchedulerSettings instance."""
        return SchedulerSettings()

    def test_default_values(self, settings: SchedulerSettings) -> None:
        """Test default scheduler settings."""
        assert settings.check_interval == 300
        assert settings.max_retries == 3
        assert settings.retry_delay == 60

    def test_check_interval_validation(self) -> None:
        """Test minimum check interval."""
        with pytest.raises(ValidationError):
            SchedulerSettings(check_interval=5)

    def test_custom_values(self) -> None:
        """Test custom scheduler configuration."""
        settings = SchedulerSettings(
            check_interval=600,
            max_retries=5,
            retry_delay=120,
        )
        assert settings.check_interval == 600
        assert settings.max_retries == 5
        assert settings.retry_delay == 120

    def test_queue_settings(self) -> None:
        """Test queue management settings."""
        settings = SchedulerSettings(
            queue_batch_size=200,
            queue_cleanup_interval=7200,
        )
        assert settings.queue_batch_size == 200
        assert settings.queue_cleanup_interval == 7200

    def test_priority_values(self) -> None:
        """Test priority values are within range."""
        settings = SchedulerSettings()
        assert 1 <= settings.priority_seed <= 5
        assert 1 <= settings.priority_regular <= 5


class TestLivenessSettings:
    """Tests for LivenessSettings class."""

    @pytest.fixture
    def settings(self) -> LivenessSettings:
        """Provide a LivenessSettings instance."""
        return LivenessSettings()

    def test_default_values(self, settings: LivenessSettings) -> None:
        """Test default liveness settings."""
        assert settings.http_check is True
        assert settings.https_check is True
        assert settings.timeout == 7
        assert settings.verify_ssl is True

    def test_timeout_validation(self) -> None:
        """Test timeout validation."""
        with pytest.raises(ValidationError):
            LivenessSettings(timeout=0)

        with pytest.raises(ValidationError):
            LivenessSettings(timeout=31)

    def test_status_codes(self) -> None:
        """Test live status codes default."""
        settings = LivenessSettings()
        assert 200 in settings.live_status_codes
        assert 201 in settings.live_status_codes

    def test_redirect_settings(self) -> None:
        """Test redirect configuration."""
        settings = LivenessSettings(max_redirects=10)
        assert settings.max_redirects == 10

        with pytest.raises(ValidationError):
            LivenessSettings(max_redirects=11)


class TestEnvironmentVariableLoading:
    """Tests for environment variable loading."""

    def test_env_override_database(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that environment variables override defaults."""
        monkeypatch.setenv("DB_HOST", "custom.db.com")
        monkeypatch.setenv("DB_PORT", "5433")

        settings = DatabaseSettings()
        assert settings.host == "custom.db.com"
        assert settings.port == 5433

    def test_env_override_crawler(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test crawler environment variable override."""
        monkeypatch.setenv("CRAWLER_MAX_CONCURRENT_REQUESTS", "100")
        monkeypatch.setenv("CRAWLER_TIMEOUT", "30")

        settings = CrawlerSettings()
        assert settings.max_concurrent_requests == 100
        assert settings.timeout == 30

    def test_multiple_env_overrides(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test multiple environment variable overrides."""
        monkeypatch.setenv("DB_HOST", "test.com")
        monkeypatch.setenv("CRAWLER_MAX_CONCURRENT_REQUESTS", "75")
        monkeypatch.setenv("SCHEDULER_CHECK_INTERVAL", "600")

        db_settings = DatabaseSettings()
        crawler_settings = CrawlerSettings()
        scheduler_settings = SchedulerSettings()

        assert db_settings.host == "test.com"
        assert crawler_settings.max_concurrent_requests == 75
        assert scheduler_settings.check_interval == 600


class TestConfigurationValidation:
    """Tests for configuration validation logic."""

    def test_domain_validation(self) -> None:
        """Test that domain names are validated."""
        from src.database.models import Domain

        domain = Domain(
            domain="  EXAMPLE.GOV.BD  ",
            protocol="https",
        )
        # Should be normalized
        assert domain.domain == "example.gov.bd"

    def test_url_validation(self) -> None:
        """Test that URLs are normalized."""
        from src.database.models import SeedUrl

        seed = SeedUrl(url="example.gov.bd")
        # Should add https://
        assert seed.url == "https://example.gov.bd"

    def test_source_validation(self) -> None:
        """Test source field validation."""
        from src.database.models import SeedUrl

        with pytest.raises(ValidationError):
            SeedUrl(url="https://example.gov.bd", source="invalid_source")

        seed = SeedUrl(url="https://example.gov.bd", source="API")
        # Should be lowercased
        assert seed.source == "api"
