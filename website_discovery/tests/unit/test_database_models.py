"""
Unit tests for database models.

This module tests the Pydantic ORM models:
    - Domain: Discovered domain tracking
    - SeedUrl: Seed URL management
    - UrlQueue: Processing queue
    - DiscoveryLog: Audit trail
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.database.models import (
    DiscoveryAction,
    DiscoveryLog,
    Domain,
    DomainStatus,
    QueueStatus,
    SeedUrl,
    UrlQueue,
)


class TestDomainModel:
    """Tests for Domain model."""

    def test_valid_domain_creation(self) -> None:
        """Test creating a valid domain instance."""
        domain = Domain(
            domain="example.gov.bd",
            protocol="https",
            is_live=True,
        )
        assert domain.domain == "example.gov.bd"
        assert domain.protocol == "https"
        assert domain.is_live is True
        assert domain.status_code is None
        assert domain.content_hash is None

    def test_domain_normalization(self) -> None:
        """Test domain name normalization."""
        domain = Domain(domain="  https://EXAMPLE.GOV.BD/  ")
        # Protocol removed, uppercase converted to lowercase
        assert domain.domain == "example.gov.bd/"

    def test_domain_with_protocol_removed(self) -> None:
        """Test that protocol is removed from domain."""
        domain = Domain(domain="http://www.test.gov.bd")
        # Protocol is removed but www. is kept (handled by DomainFinder)
        assert domain.domain == "www.test.gov.bd"

    def test_default_values(self) -> None:
        """Test default field values."""
        domain = Domain(domain="test.gov.bd")
        assert domain.protocol == "https"
        assert domain.is_live is True
        assert domain.discovered_at is not None
        assert domain.tags == []

    def test_invalid_protocol(self) -> None:
        """Test protocol validation."""
        with pytest.raises(ValidationError):
            Domain(domain="test.gov.bd", protocol="ftp")

    def test_status_code_validation(self) -> None:
        """Test status code range validation."""
        # Valid status codes
        Domain(domain="test.gov.bd", status_code=200)
        Domain(domain="test.gov.bd", status_code=404)

        # Invalid status codes
        with pytest.raises(ValidationError):
            Domain(domain="test.gov.bd", status_code=99)

        with pytest.raises(ValidationError):
            Domain(domain="test.gov.bd", status_code=600)

    def test_get_status_method(self) -> None:
        """Test Domain.get_status() method."""
        live_domain = Domain(domain="test.gov.bd", is_live=True)
        dead_domain = Domain(domain="test.gov.bd", is_live=False)

        assert live_domain.get_status() == DomainStatus.LIVE
        assert dead_domain.get_status() == DomainStatus.DEAD

    def test_from_row(self) -> None:
        """Test Domain.from_row() method."""
        row = type("Record", (), {
            "id": 1,
            "domain": "test.gov.bd",
            "protocol": "https",
            "is_live": True,
            "status_code": 200,
            "response_time": 150,
            "last_checked": None,
            "discovered_at": None,
            "rediscovered_at": None,
            "content_hash": None,
            "tags": ["gov", "test"],
        })()

        domain = Domain.from_row(row)
        assert domain.id == 1
        assert domain.domain == "test.gov.bd"
        assert domain.tags == ["gov", "test"]


class TestSeedUrlModel:
    """Tests for SeedUrl model."""

    def test_valid_seed_url_creation(self) -> None:
        """Test creating a valid seed URL."""
        seed = SeedUrl(
            url="https://bangladesh.gov.bd",
            source="manual",
        )
        assert seed.url == "https://bangladesh.gov.bd"
        assert seed.source == "manual"

    def test_url_normalization_adds_https(self) -> None:
        """Test that https:// is added if missing."""
        seed = SeedUrl(url="example.gov.bd")
        assert seed.url == "https://example.gov.bd"

    def test_url_whitespace_stripped(self) -> None:
        """Test that URLs are trimmed."""
        seed = SeedUrl(url="  https://example.gov.bd  ")
        assert seed.url == "https://example.gov.bd"

    def test_source_validation(self) -> None:
        """Test source field validation."""
        valid_sources = ["manual", "batch", "api", "import", "export"]

        for source in valid_sources:
            seed = SeedUrl(url="https://example.gov.bd", source=source)
            assert seed.source == source

        with pytest.raises(ValidationError):
            SeedUrl(url="https://example.gov.bd", source="invalid")

    def test_source_uppercase_normalized(self) -> None:
        """Test that source is lowercased."""
        seed = SeedUrl(url="https://example.gov.bd", source="BATCH")
        assert seed.source == "batch"


class TestUrlQueueModel:
    """Tests for UrlQueue model."""

    def test_valid_queue_item_creation(self) -> None:
        """Test creating a valid queue item."""
        item = UrlQueue(
            url="https://example.gov.bd/page",
            priority=2,
            status=QueueStatus.PENDING,
        )
        assert item.url == "https://example.gov.bd/page"
        assert item.priority == 2
        assert item.status == QueueStatus.PENDING

    def test_priority_validation(self) -> None:
        """Test priority range validation (1-5)."""
        for priority in range(1, 6):
            item = UrlQueue(url="https://example.gov.bd", priority=priority)
            assert item.priority == priority

        with pytest.raises(ValidationError):
            UrlQueue(url="https://example.gov.bd", priority=0)

        with pytest.raises(ValidationError):
            UrlQueue(url="https://example.gov.bd", priority=6)

    def test_status_validation(self) -> None:
        """Test status field validation."""
        for status in QueueStatus:
            item = UrlQueue(url="https://example.gov.bd", status=status)
            assert item.status == status

    def test_is_expired_method(self) -> None:
        """Test UrlQueue.is_expired() method."""
        from datetime import datetime, timedelta, timezone

        # Item that hasn't expired
        recent_item = UrlQueue(
            url="https://example.gov.bd",
            scheduled_at=datetime.now(timezone.utc),
        )
        assert recent_item.is_expired(max_age_seconds=60) is False

        # Item that has expired
        old_item = UrlQueue(
            url="https://example.gov.bd",
            scheduled_at=datetime.now(timezone.utc) - timedelta(hours=2),
        )
        assert old_item.is_expired(max_age_seconds=60) is True

    def test_no_scheduled_at(self) -> None:
        """Test expiration with no scheduled_at."""
        item = UrlQueue(
            url="https://example.gov.bd",
            scheduled_at=None,
        )
        assert item.is_expired(max_age_seconds=60) is False


class TestDiscoveryLogModel:
    """Tests for DiscoveryLog model."""

    def test_valid_log_entry_creation(self) -> None:
        """Test creating a valid log entry."""
        log = DiscoveryLog(
            action=DiscoveryAction.DISCOVERED,
            domain="example.gov.bd",
            details={"protocol": "https", "source": "link"},
        )
        assert log.action == DiscoveryAction.DISCOVERED
        assert log.domain == "example.gov.bd"
        assert log.details is not None

    def test_action_enum_values(self) -> None:
        """Test DiscoveryAction enum."""
        for action in DiscoveryAction:
            log = DiscoveryLog(action=action)
            assert log.action == action

    def test_to_log_entry_method(self) -> None:
        """Test DiscoveryLog.to_log_entry() method."""
        log = DiscoveryLog(
            action=DiscoveryAction.FAILED,
            domain="example.gov.bd",
            details={"error": "timeout"},
            error_message="Connection timeout after 5 seconds",
        )

        entry = log.to_log_entry()
        assert entry["action"] == "failed"
        assert entry["domain"] == "example.gov.bd"
        assert "error_message" in entry

    def test_timestamp_timezone_aware(self) -> None:
        """Test that timestamps are timezone-aware."""
        from datetime import datetime

        naive_dt = datetime.now()
        log = DiscoveryLog(timestamp=naive_dt)

        # Should add UTC timezone
        assert log.timestamp.tzinfo is not None


class TestDomainStatusEnum:
    """Tests for DomainStatus enum."""

    def test_enum_values(self) -> None:
        """Test DomainStatus enum values."""
        assert DomainStatus.LIVE.value == "live"
        assert DomainStatus.DEAD.value == "dead"
        assert DomainStatus.UNKNOWN.value == "unknown"


class TestQueueStatusEnum:
    """Tests for QueueStatus enum."""

    def test_enum_values(self) -> None:
        """Test QueueStatus enum values."""
        assert QueueStatus.PENDING.value == "pending"
        assert QueueStatus.PROCESSING.value == "processing"
        assert QueueStatus.COMPLETED.value == "completed"
        assert QueueStatus.FAILED.value == "failed"


class TestDiscoveryActionEnum:
    """Tests for DiscoveryAction enum."""

    def test_enum_values(self) -> None:
        """Test DiscoveryAction enum values."""
        assert DiscoveryAction.DISCOVERED.value == "discovered"
        assert DiscoveryAction.CHECKED.value == "checked"
        assert DiscoveryAction.FAILED.value == "failed"
        assert DiscoveryAction.REDISCOVERED.value == "rediscovered"
        assert DiscoveryAction.RETRYING.value == "retrying"


class TestDomainDictConversion:
    """Tests for Domain to_dict conversion."""

    def test_to_dict_basic(self) -> None:
        """Test basic dictionary conversion."""
        domain = Domain(
            id=1,
            domain="test.gov.bd",
            protocol="https",
            is_live=True,
            status_code=200,
        )

        data = domain.to_dict(include_sensitive=False)
        assert data["domain"] == "test.gov.bd"
        assert "id" not in data

    def test_to_dict_excludes_sensitive(self) -> None:
        """Test that sensitive fields are excluded."""
        domain = Domain(
            domain="test.gov.bd",
            content_hash="abc123def456",
        )

        data = domain.to_dict(include_sensitive=False)
        assert "content_hash" not in data

        data_with_sensitive = domain.to_dict(include_sensitive=True)
        assert data_with_sensitive["content_hash"] == "abc123def456"
