"""
Tools package for CLI utilities.

This package provides command-line tools for the service:
    - ingest_seed_urls: Add seed URLs from text files
    - status_report: Generate status reports
"""

from __future__ import annotations

from src.tools.ingest_seed_urls import main as ingest_seed_urls_main
from src.tools.status_report import main as status_report_main

__all__ = [
    "ingest_seed_urls_main",
    "status_report_main",
]
