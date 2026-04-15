"""
Metrics Service for performance monitoring.

This module provides:
    - Metrics collection (discovery count, queue depth, etc.)
    - Prometheus-compatible metrics export
    - JSON metrics export
    - Real-time metrics endpoint

Usage:
    >>> from src.services.metrics import MetricsService
    >>> service = MetricsService()
    >>> service.increment_discovery()
    >>> metrics = service.get_metrics()
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

from loguru import logger

from src.config.settings import settings


class MetricsService:
    """
    Service for collecting and exporting metrics.

    Collects metrics for:
    - Discovery count (total, successful, failed)
    - Queue depth
    - Response times
    - Error rates

    Example:
        >>> service = MetricsService()
        >>> service.start_timer("discovery")
        >>> # ... do work ...
        >>> service.record_time("discovery", 1.5)
    """

    def __init__(
        self,
        collection_interval: int | None = None,
        export_format: str = "prometheus",
    ) -> None:
        """
        Initialize MetricsService.

        Args:
            collection_interval: Seconds between collections.
            export_format: Export format (prometheus/json).
        """
        self.collection_interval: int = collection_interval or settings.metrics.collection_interval
        self.export_format: str = export_format

        # Metrics storage
        self._counters: dict[str, int] = defaultdict(int)
        self._gauges: dict[str, int] = {}
        self._histograms: dict[str, list[float]] = defaultdict(list)
        self._start_time: datetime = datetime.now(timezone.utc)

        # Timer tracking
        self._timers: dict[str, datetime] = {}

        logger.info(f"MetricsService initialized: format={export_format}")

    def increment(self, name: str, value: int = 1) -> None:
        """
        Increment a counter.

        Args:
            name: Counter name.
            value: Amount to increment.
        """
        self._counters[name] += value
        logger.debug(f"Counter {name}: {self._counters[name]}")

    def decrement(self, name: str, value: int = 1) -> None:
        """
        Decrement a counter.

        Args:
            name: Counter name.
            value: Amount to decrement.
        """
        self._counters[name] = max(0, self._counters[name] - value)

    def set_gauge(self, name: str, value: int) -> None:
        """
        Set a gauge value.

        Args:
            name: Gauge name.
            value: Current value.
        """
        self._gauges[name] = value

    def record_time(self, name: str, seconds: float) -> None:
        """
        Record a timing.

        Args:
            name: Timer name.
            seconds: Duration in seconds.
        """
        self._histograms[name].append(seconds)

        # Keep only last 1000 values
        if len(self._histograms[name]) > 1000:
            self._histograms[name] = self._histograms[name][-1000:]

    def start_timer(self, name: str) -> None:
        """
        Start a timer.

        Args:
            name: Timer name.
        """
        self._timers[name] = datetime.now(timezone.utc)

    def stop_timer(self, name: str) -> float | None:
        """
        Stop a timer and return duration.

        Args:
            name: Timer name.

        Returns:
            Duration in seconds or None if timer not started.
        """
        if name not in self._timers:
            return None

        end = datetime.now(timezone.utc)
        duration = (end - self._timers[name]).total_seconds()
        del self._timers[name]

        self.record_time(name, duration)
        return duration

    # Discovery metrics
    def record_discovery(self, successful: bool = True) -> None:
        """
        Record a domain discovery.

        Args:
            successful: Whether discovery was successful.
        """
        self.increment("discoveries_total")
        if successful:
            self.increment("discoveries_successful")
        else:
            self.increment("discoveries_failed")

    def record_liveness_check(self, successful: bool = True) -> None:
        """
        Record a liveness check.

        Args:
            successful: Whether check was successful.
        """
        self.increment("liveness_checks_total")
        if successful:
            self.increment("liveness_checks_successful")
        else:
            self.increment("liveness_checks_failed")

    def record_error(self, error_type: str) -> None:
        """
        Record an error.

        Args:
            error_type: Type of error.
        """
        self.increment("errors_total")
        self.increment(f"errors_{error_type}")

    # Queue metrics
    def set_queue_depth(self, depth: int) -> None:
        """
        Set queue depth gauge.

        Args:
            depth: Current queue depth.
        """
        self.set_gauge("queue_depth", depth)

    def set_discovered_count(self, count: int) -> None:
        """
        Set discovered domain count.

        Args:
            count: Total discovered domains.
        """
        self.set_gauge("discovered_count", count)

    def set_dead_count(self, count: int) -> None:
        """
        Set dead domain count.

        Args:
            count: Total dead domains.
        """
        self.set_gauge("dead_count", count)

    def get_metrics(self) -> dict[str, Any]:
        """
        Get all current metrics.

        Returns:
            Dictionary with all metrics.
        """
        uptime = (datetime.now(timezone.utc) - self._start_time).total_seconds()

        return {
            "uptime_seconds": round(uptime, 2),
            "counters": dict(self._counters),
            "gauges": dict(self._gauges),
            "histograms": {
                name: self._calculate_histogram_stats(values)
                for name, values in self._histograms.items()
            },
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    def _calculate_histogram_stats(self, values: list[float]) -> dict[str, float]:
        """
        Calculate histogram statistics.

        Args:
            values: List of recorded values.

        Returns:
            Statistics dictionary.
        """
        if not values:
            return {"count": 0, "min": 0, "max": 0, "avg": 0}

        return {
            "count": len(values),
            "min": round(min(values), 3),
            "max": round(max(values), 3),
            "avg": round(sum(values) / len(values), 3),
        }

    def to_prometheus(self) -> str:
        """
        Export metrics in Prometheus format.

        Returns:
            Prometheus-formatted string.
        """
        lines: list[str] = []
        lines.append("# HELP website_discovery_uptime Service uptime in seconds")
        lines.append("# TYPE website_discovery_uptime gauge")
        lines.append(
            f'website_discovery_uptime {self.get_metrics()["uptime_seconds"]}'
        )

        # Counters
        for name, value in self._counters.items():
            metric_name = f"website_discovery_{name.replace('_', '_')}"
            lines.append(f"# HELP {metric_name} Counter")
            lines.append(f"# TYPE {metric_name} counter")
            lines.append(f"{metric_name} {value}")

        # Gauges
        for name, value in self._gauges.items():
            metric_name = f"website_discovery_{name.replace('_', '_')}"
            lines.append(f"# HELP {metric_name} Gauge")
            lines.append(f"# TYPE {metric_name} gauge")
            lines.append(f"{metric_name} {value}")

        return "\n".join(lines)

    def to_json(self) -> str:
        """
        Export metrics as JSON.

        Returns:
            JSON string.
        """
        import json

        return json.dumps(self.get_metrics(), indent=2)

    async def periodic_collection(self) -> None:
        """
        Run periodic metric collection.

        This would be called in a background task to continuously
        collect metrics at the configured interval.
        """
        logger.info("Starting periodic metric collection")

        while True:
            try:
                await asyncio.sleep(self.collection_interval)
                # Collect metrics from various sources
                # This is a placeholder for actual collection logic
                logger.debug("Metrics collection tick")
            except asyncio.CancelledError:
                logger.info("Periodic collection stopped")
                break


# Convenience functions for quick metric recording
_counter = MetricsService()


def increment(name: str, value: int = 1) -> None:
    """Increment a counter (global instance)."""
    _counter.increment(name, value)


def set_gauge(name: str, value: float) -> None:
    """Set a gauge (global instance)."""
    _counter.set_gauge(name, int(value))


def get_metrics() -> dict[str, Any]:
    """Get current metrics (global instance)."""
    return _counter.get_metrics()
