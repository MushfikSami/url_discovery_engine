"""
Unit tests for configuration settings.

This module tests the Pydantic configuration settings including:
- Environment variable loading
- Type validation
- Default values
- Connection string generation
"""

from __future__ import annotations

import os
from typing import Any

import pytest
from pydantic import ValidationError

from src.url_discovery_engine.config import (
    AppConfig,
    CrawlerSettings,
    DatabaseSettings,
    ElasticsearchSettings,
    LLMSettings,
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
        assert settings.user == "postgres"
        assert settings.password == "password"
        assert settings.bd_gov_db == "bd_gov_db"
        assert settings.gov_bd_db == "gov_bd_db"
        assert settings.banglapedia_db == "banglapedia_db"

    def test_connection_strings(self, settings: DatabaseSettings) -> None:
        """Test connection string generation."""
        bd_gov_conn = settings.bd_gov_connection_string
        assert "postgresql://" in bd_gov_conn
        assert settings.host in bd_gov_conn
        assert settings.port in bd_gov_conn
        assert settings.bd_gov_db in bd_gov_conn

        gov_bd_conn = settings.gov_bd_connection_string
        assert settings.gov_bd_db in gov_bd_conn

        banglapedia_conn = settings.banglapedia_connection_string
        assert settings.banglapedia_db in banglapedia_conn

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
            bd_gov_db="custom_gov_db",
        )
        assert settings.host == "db.example.com"
        assert settings.port == 5433
        assert settings.user == "admin"


class TestLLMSettings:
    """Tests for LLMSettings class."""

    @pytest.fixture
    def settings(self) -> LLMSettings:
        """Provide an LLMSettings instance."""
        return LLMSettings()

    def test_default_values(self, settings: LLMSettings) -> None:
        """Test default LLM settings."""
        assert settings.base_url == "http://localhost:5000/v1"
        assert settings.api_key == "no-key"
        assert settings.model_name == "qwen35"

    def test_custom_values(self) -> None:
        """Test custom LLM configuration."""
        settings = LLMSettings(
            base_url="http://api.example.com/v1",
            api_key="my-api-key",
            model_name="custom-model",
        )
        assert settings.base_url == "http://api.example.com/v1"
        assert settings.api_key == "my-api-key"
        assert settings.model_name == "custom-model"


class TestElasticsearchSettings:
    """Tests for ElasticsearchSettings class."""

    @pytest.fixture
    def settings(self) -> ElasticsearchSettings:
        """Provide an ElasticsearchSettings instance."""
        return ElasticsearchSettings()

    def test_default_values(self, settings: ElasticsearchSettings) -> None:
        """Test default Elasticsearch settings."""
        assert settings.host == "http://localhost:9200"
        assert settings.index_name == "bd_gov_chunks"

    def test_custom_values(self) -> None:
        """Test custom Elasticsearch configuration."""
        settings = ElasticsearchSettings(
            host="http://es.example.com:9200",
            index_name="custom_index",
        )
        assert settings.host == "http://es.example.com:9200"
        assert settings.index_name == "custom_index"


class TestCrawlerSettings:
    """Tests for CrawlerSettings class."""

    @pytest.fixture
    def settings(self) -> CrawlerSettings:
        """Provide a CrawlerSettings instance."""
        return CrawlerSettings()

    def test_default_values(self, settings: CrawlerSettings) -> None:
        """Test default crawler settings."""
        assert settings.max_concurrent_requests == 30
        assert settings.liveness_max_concurrent == 100
        assert settings.timeout == 15
        assert settings.liveness_timeout == 7
        assert settings.politeness_delay == 0.5
        assert settings.user_agent == "BD-Gov-Ecosystem-Mapper/3.0 (Research)"
        assert settings.word_count_threshold == 20

    def test_concurrency_validation(self) -> None:
        """Test that concurrency values are positive."""
        with pytest.raises(ValidationError):
            CrawlerSettings(max_concurrent_requests=0)

        with pytest.raises(ValidationError):
            CrawlerSettings(max_concurrent_requests=-1)

    def test_custom_values(self) -> None:
        """Test custom crawler configuration."""
        settings = CrawlerSettings(
            max_concurrent_requests=50,
            timeout=30,
            politeness_delay=1.0,
        )
        assert settings.max_concurrent_requests == 50
        assert settings.timeout == 30
        assert settings.politeness_delay == 1.0

    def test_excluded_tags(self) -> None:
        """Test excluded tags default and custom values."""
        settings = CrawlerSettings()
        assert "nav" in settings.excluded_tags
        assert "footer" in settings.excluded_tags

        custom_settings = CrawlerSettings(excluded_tags=["custom", "tag"])
        assert custom_settings.excluded_tags == ["custom", "tag"]


class TestAppConfig:
    """Tests for main AppConfig class."""

    @pytest.fixture
    def settings(self) -> AppConfig:
        """Provide an AppConfig instance."""
        return AppConfig()

    def test_app_metadata(self, settings: AppConfig) -> None:
        """Test application metadata."""
        assert settings.name == "url_discovery_engine"
        assert settings.version == "1.0.0"

    def test_nested_settings(self, settings: AppConfig) -> None:
        """Test that nested settings are properly initialized."""
        assert isinstance(settings.database, DatabaseSettings)
        assert isinstance(settings.llm, LLMSettings)
        assert isinstance(settings.elasticsearch, ElasticsearchSettings)
        assert isinstance(settings.crawler, CrawlerSettings)

    def test_debug_parsing(self) -> None:
        """Test debug flag parsing from various input types."""
        # Boolean
        settings = AppConfig(debug=True)
        assert settings.debug is True

        # String true
        settings = AppConfig(debug="true")
        assert settings.debug is True

        # String 1
        settings = AppConfig(debug="1")
        assert settings.debug is True

    @pytest.mark.parametrize(
        ("env_vars", "expected_host", "expected_model"),
        [
            ({"DB_HOST": "custom.db.com"}, "custom.db.com", "qwen35"),
            ({"LLM_MODEL_NAME": "custom-model"}, "localhost", "custom-model"),
            (
                {"DB_HOST": "test.com", "LLM_MODEL_NAME": "test-model"},
                "test.com",
                "test-model",
            ),
        ],
    )
    def test_environment_override(
        self, monkeypatch: pytest.MonkeyPatch, env_vars: dict[str, Any], expected_host: str, expected_model: str
    ) -> None:
        """Test that environment variables override defaults."""
        for key, value in env_vars.items():
            monkeypatch.setenv(key, value)

        settings = AppConfig()
        assert settings.database.host == expected_host
        assert settings.llm.model_name == expected_model


class TestConfigurationLoading:
    """Tests for configuration loading mechanisms."""

    @pytest.fixture
    def env_setup(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Setup environment variables for testing."""
        monkeypatch.setenv("DB_HOST", "test.db.local")
        monkeypatch.setenv("LLM_MODEL_NAME", "test-model")
        monkeypatch.setenv("ES_INDEX_NAME", "test_index")

    def test_env_variables_loaded(self, env_setup: None) -> None:
        """Test that environment variables are properly loaded."""
        settings = AppConfig()
        assert settings.database.host == "test.db.local"
        assert settings.llm.model_name == "test-model"
        assert settings.elasticsearch.index_name == "test_index"

    def test_settings_instance_reuse(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that settings instance can be safely reused."""
        monkeypatch.setenv("DB_HOST", "host1")
        settings1 = AppConfig()
        assert settings1.database.host == "host1"

        monkeypatch.setenv("DB_HOST", "host2")
        settings2 = AppConfig()
        assert settings2.database.host == "host2"
