"""
Crawler package for domain discovery.

This package provides the core crawling components:
    - engine: Main discovery orchestration
    - finder: Domain extraction from URLs
    - queue: URL queue management
"""

from __future__ import annotations

from src.crawler.engine import DiscoveryEngine
from src.crawler.finder import DomainFinder
from src.crawler.queue import PriorityQueue

__all__ = [
    "DiscoveryEngine",
    "DomainFinder",
    "PriorityQueue",
]
