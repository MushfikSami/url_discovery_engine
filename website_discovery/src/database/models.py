"""
Pydantic ORM models for the Website Discovery Service.

This module defines Pydantic models that represent database tables
and provide type-safe data access.

Models:
    Domain: Represents discovered domains with status tracking
    SeedUrl: Represents seed URLs for discovery
    UrlQueue: Represents URLs in the discovery queue
    DiscoveryLog: Represents discovery audit trail

Usage:
    >>> from src.database.models import Domain, DomainStatus
    >>>
    >>> domain = Domain(
    ...     domain="example.gov.bd",
    ...     protocol="https",
    ...     is_live=True,
    ...     status_code=200
    ... )
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, field_validator


class DomainStatus(str, Enum):
    """Domain liveness status."""

    LIVE = "live"
    DEAD = "dead"
    UNKNOWN = "unknown"


class QueueStatus(str, Enum):
    """URL queue status."""

    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class DiscoveryAction(str, Enum):
    """Discovery log action types."""

    DISCOVERED = "discovered"
    CHECKED = "checked"
    FAILED = "failed"
    REDISCOVERED = "rediscovered"
    RETRYING = "retrying"


class Domain(BaseModel):
    """
    Domain model representing a discovered .gov.bd domain.

    Attributes:
        id: Database row ID (set after insert).
        domain: Domain name (e.g., 'example.gov.bd').
        protocol: HTTP protocol (http/https).
        is_live: Current liveness status.
        status_code: Last HTTP status code.
        response_time: Response time in milliseconds.
        last_checked: Last liveness check timestamp.
        discovered_at: When domain was first discovered.
        rediscovered_at: When domain was rediscovered after being dead.
        content_hash: Optional hash for content change detection.
        tags: Optional list of tags for categorization.

    Example:
        >>> domain = Domain(
        ...     domain="moef.gov.bd",
        ...     protocol="https",
        ...     is_live=True,
        ...     status_code=200
        ... )
    """

    id: int | None = Field(default=None, description="Database row ID")
    domain: str = Field(..., min_length=1, max_length=255, description="Domain name")
    protocol: str = Field(default="https", pattern="^(http|https)$", description="Protocol")
    is_live: bool = Field(default=True, description="Liveness status")
    status_code: int | None = Field(default=None, ge=100, le=599, description="HTTP status code")
    response_time: int | None = Field(default=None, ge=0, description="Response time ms")
    last_checked: datetime | None = Field(default=None, description="Last check timestamp")
    discovered_at: datetime | None = Field(default_factory=datetime.utcnow, description="Discovery timestamp")
    rediscovered_at: datetime | None = Field(default=None, description="Rediscovery timestamp")
    content_hash: str | None = Field(default=None, max_length=64, description="Content hash")
    tags: list[str] = Field(default_factory=list, description="Tags")

    @field_validator("domain")
    @classmethod
    def validate_domain(cls, value: str) -> str:
        """Validate domain format."""
        value = value.lower().strip()

        # Remove protocol if present
        for prefix in ("http://", "https://", "www."):
            if value.startswith(prefix):
                value = value[len(prefix) :]
                break

        return value

    @field_validator("last_checked", "discovered_at", "rediscovered_at")
    @classmethod
    def validate_timestamp(cls, value: datetime | None) -> datetime | None:
        """Ensure timestamps are timezone-aware."""
        if value is None:
            return None

        # Add UTC timezone if naive
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)

        return value

    def get_status(self) -> DomainStatus:
        """
        Get domain status enum.

        Returns:
            DomainStatus value based on is_live.
        """
        return DomainStatus.LIVE if self.is_live else DomainStatus.DEAD

    def to_dict(self, include_sensitive: bool = False) -> dict[str, Any]:
        """
        Convert to dictionary.

        Args:
            include_sensitive: Include sensitive fields.

        Returns:
            Dictionary representation.
        """
        data = self.model_dump(exclude={"id"}, exclude_none=True)

        if not include_sensitive:
            data.pop("content_hash", None)

        return data

    @classmethod
    def from_row(cls, row: Any) -> Domain:
        """
        Create domain from database row.

        Args:
            row: Database row (asyncpg.Record or similar).

        Returns:
            Domain instance.
        """
        return cls(
            id=row.id if hasattr(row, "id") else None,
            domain=row.domain,
            protocol=row.protocol,
            is_live=row.is_live,
            status_code=row.status_code,
            response_time=row.response_time,
            last_checked=row.last_checked,
            discovered_at=row.discovered_at,
            rediscovered_at=row.rediscovered_at,
            content_hash=row.content_hash,
            tags=row.tags if hasattr(row, "tags") else [],
        )


class SeedUrl(BaseModel):
    """
    Seed URL model for discovery sources.

    Attributes:
        id: Database row ID.
        url: Full URL of seed.
        source: How seed was added (manual/batch/api).
        added_at: When seed was added.

    Example:
        >>> seed = SeedUrl(
        ...     url="https://bangladesh.gov.bd",
        ...     source="manual"
        ... )
    """

    id: int | None = Field(default=None, description="Database row ID")
    url: str = Field(..., min_length=1, max_length=500, description="Seed URL")
    source: str = Field(default="manual", description="Source type")
    added_at: datetime | None = Field(default_factory=datetime.utcnow, description="Addition timestamp")

    @field_validator("url")
    @classmethod
    def validate_url(cls, value: str) -> str:
        """Validate URL format."""
        value = value.strip()

        # Add https:// if missing
        if not value.startswith(("http://", "https://")):
            value = f"https://{value}"

        return value

    @field_validator("source")
    @classmethod
    def validate_source(cls, value: str) -> str:
        """Validate source value."""
        valid_sources = ("manual", "batch", "api", "import", "export")
        if value.lower() not in valid_sources:
            raise ValueError(f"Source must be one of: {valid_sources}")
        return value.lower()

    @classmethod
    def from_row(cls, row: Any) -> SeedUrl:
        """Create seed from database row."""
        return cls(
            id=row.id if hasattr(row, "id") else None,
            url=row.url,
            source=row.source,
            added_at=row.added_at,
        )


class UrlQueue(BaseModel):
    """
    URL queue model for discovery scheduling.

    Attributes:
        id: Database row ID.
        url: URL to process.
        priority: Queue priority (1=critical, 5=low).
        scheduled_at: When URL should be processed.
        attempts: Number of processing attempts.
        status: Current queue status.
        domain: Associated domain if known.

    Example:
        >>> queue_item = UrlQueue(
        ...     url="https://example.gov.bd/about",
        ...     priority=2
        ... )
    """

    id: int | None = Field(default=None, description="Database row ID")
    url: str = Field(..., min_length=1, max_length=500, description="URL to process")
    priority: int = Field(default=3, ge=1, le=5, description="Queue priority")
    scheduled_at: datetime | None = Field(default_factory=datetime.utcnow, description="Scheduled time")
    attempts: int = Field(default=0, ge=0, description="Attempt count")
    status: QueueStatus = Field(default=QueueStatus.PENDING, description="Queue status")
    domain: str | None = Field(default=None, max_length=255, description="Associated domain")

    @field_validator("url")
    @classmethod
    def validate_url(cls, value: str) -> str:
        """Validate URL format."""
        return value.strip()

    def is_expired(self, max_age_seconds: int = 3600) -> bool:
        """
        Check if queue item has expired.

        Args:
            max_age_seconds: Maximum age in seconds.

        Returns:
            True if item has exceeded max age.
        """
        if self.scheduled_at is None:
            return False

        from datetime import timezone

        age = (datetime.now(timezone.utc) - self.scheduled_at.replace(tzinfo=timezone.utc)).total_seconds()
        return age > max_age_seconds

    @classmethod
    def from_row(cls, row: Any) -> UrlQueue:
        """Create queue item from database row."""
        return cls(
            id=row.id if hasattr(row, "id") else None,
            url=row.url,
            priority=row.priority,
            scheduled_at=row.scheduled_at,
            attempts=row.attempts,
            status=QueueStatus(row.status),
            domain=row.domain,
        )


class DiscoveryLog(BaseModel):
    """
    Discovery log model for audit trail.

    Attributes:
        id: Database row ID.
        timestamp: When the action occurred.
        action: Type of discovery action.
        domain: Affected domain.
        details: Additional JSON data.
        error_message: Error details if any.

    Example:
        >>> log_entry = DiscoveryLog(
        ...     action=DiscoveryAction.DISCOVERED,
        ...     domain="moef.gov.bd",
        ...     details={"protocol": "https", "source": "link"}
        ... )
    """

    id: int | None = Field(default=None, description="Database row ID")
    timestamp: datetime | None = Field(default_factory=datetime.utcnow, description="Action timestamp")
    action: DiscoveryAction = Field(default=DiscoveryAction.DISCOVERED, description="Action type")
    domain: str | None = Field(default=None, max_length=255, description="Affected domain")
    details: dict[str, Any] | None = Field(default=None, description="Additional details")
    error_message: str | None = Field(default=None, max_length=1000, description="Error message")

    @field_validator("timestamp")
    @classmethod
    def validate_timestamp(cls, value: datetime | None) -> datetime | None:
        """Ensure timestamp is timezone-aware."""
        if value is None:
            return None

        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)

        return value

    def to_log_entry(self) -> dict[str, Any]:
        """
        Convert to log entry for output.

        Returns:
            Dictionary suitable for logging.
        """
        return {
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
            "action": self.action.value,
            "domain": self.domain,
            "details": self.details,
            "error_message": self.error_message,
        }

    @classmethod
    def from_row(cls, row: Any) -> DiscoveryLog:
        """Create log entry from database row."""
        details = row.details
        if isinstance(details, dict):
            pass
        elif isinstance(details, str):
            import json
            try:
                details = json.loads(details)
            except (json.JSONDecodeError, TypeError):
                details = None

        return cls(
            id=row.id if hasattr(row, "id") else None,
            timestamp=row.timestamp,
            action=DiscoveryAction(row.action),
            domain=row.domain,
            details=details,
            error_message=row.error_message,
        )


class DiscoveryStats(BaseModel):
    """
    Aggregated discovery statistics.

    Attributes:
        total_domains: Total discovered domains.
        live_domains: Currently live domains.
        dead_domains: Currently dead domains.
        newest_discovery: Most recent discovery date.
        oldest_discovery: Oldest discovery date.

    Example:
        >>> stats = DiscoveryStats(
        ...     total_domains=1000,
        ...     live_domains=850,
        ...     dead_domains=150
        ... )
    """

    total_domains: int = Field(default=0, description="Total domains")
    live_domains: int = Field(default=0, description="Live domains")
    dead_domains: int = Field(default=0, description="Dead domains")
    newest_discovery: datetime | None = Field(default=None, description="Newest discovery")
    oldest_discovery: datetime | None = Field(default=None, description="Oldest discovery")

    @property
    def live_rate(self) -> float:
        """Calculate live rate percentage."""
        if self.total_domains == 0:
            return 0.0
        return (self.live_domains / self.total_domains) * 100

    def to_summary(self) -> dict[str, Any]:
        """
        Get summary dictionary.

        Returns:
            Summary with statistics.
        """
        return {
            "total": self.total_domains,
            "live": self.live_domains,
            "dead": self.dead_domains,
            "live_rate": round(self.live_rate, 2),
            "newest": self.newest_discovery.isoformat() if self.newest_discovery else None,
            "oldest": self.oldest_discovery.isoformat() if self.oldest_discovery else None,
        }
