"""
Status Report Tool.

This tool generates a status report of the discovery service:
    - Total discovered domains
    - Live vs dead counts
    - Queue status
    - Recent activity

Usage:
    python -m src.tools.status_report

Tool Usage:
    ===================================
    Purpose: Generate discovery status report
    ===================================

    1. Run the tool:

       python -m src.tools.status_report

    2. View output:

       =========================================
       Website Discovery Service - Status Report
       Generated: 2026-04-14 10:30:00
       =========================================

       DISCOVERY STATUS
       ----------------
       Total Domains:      1,234
       Live:               1,089 (88.2%)
       Dead:               145
       Rediscovered:       23

       QUEUE STATUS
       ------------
       Pending:            45
       Processing:         3
       Completed:          5,678
       Failed:             12

       RECENT ACTIVITY (last 24 hours)
       -------------------------------
       New Discoveries:    156
       Checks Performed:   234
       Errors:             5

       =========================================

    3. Save report to file:

       python -m src.tools.status_report > report.txt

    4. Get JSON output:

       python -m src.tools.status_report --format json
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import click
from loguru import logger

from src.database.connection import get_pool


async def get_discovery_stats() -> dict[str, Any]:
    """
    Get discovery statistics from database.

    Returns:
        Dictionary with discovery stats.
    """
    pool = await get_pool()

    stats: dict[str, Any] = {}

    # Total domains
    result = await pool.fetchval("SELECT COUNT(*) FROM domains")
    stats["total_domains"] = result or 0

    # Live domains
    result = await pool.fetchval(
        "SELECT COUNT(*) FROM domains WHERE is_live = TRUE"
    )
    stats["live_domains"] = result or 0

    # Dead domains
    result = await pool.fetchval(
        "SELECT COUNT(*) FROM domains WHERE is_live = FALSE"
    )
    stats["dead_domains"] = result or 0

    # Rediscovered domains
    result = await pool.fetchval(
        "SELECT COUNT(*) FROM domains WHERE rediscovered_at IS NOT NULL"
    )
    stats["rediscovered_count"] = result or 0

    # Recent discoveries (last 24 hours)
    result = await pool.fetchval(
        """
        SELECT COUNT(*) FROM domains
        WHERE discovered_at > NOW() - INTERVAL '24 hours'
        """
    )
    stats["new_discoveries_24h"] = result or 0

    # Oldest and newest discovery
    oldest = await pool.fetchval("SELECT MIN(discovered_at) FROM domains")
    newest = await pool.fetchval("SELECT MAX(discovered_at) FROM domains")
    stats["oldest_discovery"] = oldest
    stats["newest_discovery"] = newest

    # Calculate live rate
    if stats["total_domains"] > 0:
        stats["live_rate"] = (
            (stats["live_domains"] / stats["total_domains"]) * 100
        )
    else:
        stats["live_rate"] = 0.0

    return stats


async def get_queue_stats() -> dict[str, Any]:
    """
    Get queue statistics from database.

    Returns:
        Dictionary with queue stats.
    """
    pool = await get_pool()

    stats: dict[str, Any] = {}

    # Total queue items
    result = await pool.fetchval("SELECT COUNT(*) FROM url_queue")
    stats["total_queue"] = result or 0

    # By status
    stats["pending"] = await pool.fetchval(
        "SELECT COUNT(*) FROM url_queue WHERE status = 'pending'"
    ) or 0
    stats["processing"] = await pool.fetchval(
        "SELECT COUNT(*) FROM url_queue WHERE status = 'processing'"
    ) or 0
    stats["completed"] = await pool.fetchval(
        "SELECT COUNT(*) FROM url_queue WHERE status = 'completed'"
    ) or 0
    stats["failed"] = await pool.fetchval(
        "SELECT COUNT(*) FROM url_queue WHERE status = 'failed'"
    ) or 0

    # By priority
    stats["by_priority"] = {}
    for priority in range(1, 6):
        count = await pool.fetchval(
            """
            SELECT COUNT(*) FROM url_queue
            WHERE status = 'pending' AND priority = $1
            """,
            priority,
        )
        stats["by_priority"][priority] = count or 0

    return stats


async def get_seed_stats() -> dict[str, Any]:
    """
    Get seed URL statistics.

    Returns:
        Dictionary with seed stats.
    """
    pool = await get_pool()

    stats: dict[str, Any] = {}

    # Total seeds
    result = await pool.fetchval("SELECT COUNT(*) FROM seed_urls")
    stats["total_seeds"] = result or 0

    # By source
    sources = await pool.fetch("""
        SELECT source, COUNT(*) as count
        FROM seed_urls
        GROUP BY source
        ORDER BY count DESC
    """)
    stats["by_source"] = {row["source"]: row["count"] for row in sources}

    # Recently added (last 7 days)
    result = await pool.fetchval("""
        SELECT COUNT(*) FROM seed_urls
        WHERE added_at > NOW() - INTERVAL '7 days'
    """)
    stats["recent_7d"] = result or 0

    return stats


async def get_activity_stats(hours: int = 24) -> dict[str, Any]:
    """
    Get recent activity statistics.

    Args:
        hours: Number of hours to look back.

    Returns:
        Dictionary with activity stats.
    """
    pool = await get_pool()
    interval = f"INTERVAL '{hours} hours'"

    stats: dict[str, Any] = {}

    # Discovery actions
    discovered = await pool.fetchval(f"""
        SELECT COUNT(*) FROM discovery_log
        WHERE action = 'discovered'
        AND timestamp > NOW() - {interval}
    """)
    stats["discovered"] = discovered or 0

    # Check actions
    checked = await pool.fetchval(f"""
        SELECT COUNT(*) FROM discovery_log
        WHERE action = 'checked'
        AND timestamp > NOW() - {interval}
    """)
    stats["checked"] = checked or 0

    # Failed actions
    failed = await pool.fetchval(f"""
        SELECT COUNT(*) FROM discovery_log
        WHERE action = 'failed'
        AND timestamp > NOW() - {interval}
    """)
    stats["failed"] = failed or 0

    # Errors
    errors = await pool.fetchval(f"""
        SELECT COUNT(*) FROM discovery_log
        WHERE error_message IS NOT NULL
        AND timestamp > NOW() - {interval}
    """)
    stats["errors"] = errors or 0

    # Recent discoveries (top 5 domains)
    recent = await pool.fetch("""
        SELECT domain, discovered_at
        FROM domains
        ORDER BY discovered_at DESC
        LIMIT 5
    """)
    stats["recent_domains"] = [
        {"domain": row["domain"], "discovered_at": row["discovered_at"]}
        for row in recent
    ]

    return stats


def format_statistics(stats: dict[str, Any]) -> str:
    """
    Format statistics as a readable string.

    Args:
        stats: Dictionary with statistics.

    Returns:
        Formatted string.
    """
    lines: list[str] = []

    # Header
    lines.append("=" * 50)
    lines.append("Website Discovery Service - Status Report")
    lines.append(f"Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC")
    lines.append("=" * 50)
    lines.append("")

    # Discovery Status
    discovery = stats.get("discovery", {})
    lines.append("DISCOVERY STATUS")
    lines.append("-" * 30)
    lines.append(f"Total Domains:      {discovery.get('total_domains', 0):,}")
    lines.append(f"Live:               {discovery.get('live_domains', 0):,} "
                 f"({discovery.get('live_rate', 0):.1f}%)")
    lines.append(f"Dead:               {discovery.get('dead_domains', 0):,}")
    lines.append(f"Rediscovered:       {discovery.get('rediscovered_count', 0):,}")
    lines.append(f"New (24h):          {discovery.get('new_discoveries_24h', 0):,}")
    lines.append("")

    # Queue Status
    queue = stats.get("queue", {})
    lines.append("QUEUE STATUS")
    lines.append("-" * 30)
    lines.append(f"Pending:            {queue.get('pending', 0):,}")
    lines.append(f"Processing:         {queue.get('processing', 0):,}")
    lines.append(f"Completed:          {queue.get('completed', 0):,}")
    lines.append(f"Failed:             {queue.get('failed', 0):,}")
    lines.append(f"Total Queue:        {queue.get('total_queue', 0):,}")

    # Priority breakdown
    by_priority = queue.get("by_priority", {})
    if by_priority:
        lines.append("By Priority:")
        for priority, count in sorted(by_priority.items()):
            labels = {1: "Critical", 2: "High", 3: "Medium", 4: "Low", 5: "Minimum"}
            lines.append(f"  {labels.get(priority, 'Unknown')}: {count:,}")
    lines.append("")

    # Seed Stats
    seeds = stats.get("seeds", {})
    lines.append("SEED URL STATUS")
    lines.append("-" * 30)
    lines.append(f"Total Seeds:        {seeds.get('total_seeds', 0):,}")
    lines.append(f"Recent (7d):        {seeds.get('recent_7d', 0):,}")
    lines.append("")

    # Activity
    activity = stats.get("activity", {})
    lines.append("RECENT ACTIVITY (24h)")
    lines.append("-" * 30)
    lines.append(f"New Discoveries:    {activity.get('discovered', 0):,}")
    lines.append(f"Checks Performed:   {activity.get('checked', 0):,}")
    lines.append(f"Errors:             {activity.get('errors', 0):,}")
    lines.append(f"Failed Actions:     {activity.get('failed', 0):,}")

    if activity.get("recent_domains"):
        lines.append("")
        lines.append("Recent Discoveries:")
        for domain_info in activity["recent_domains"][:5]:
            lines.append(f"  - {domain_info['domain']}")
    lines.append("")

    lines.append("=" * 50)

    return "\n".join(lines)


def format_json_output(stats: dict[str, Any]) -> str:
    """
    Format statistics as JSON.

    Args:
        stats: Dictionary with statistics.

    Returns:
        JSON string.
    """
    return json.dumps(stats, indent=2, default=str)


async def generate_report(output_format: str = "text") -> str:
    """
    Generate a complete status report.

    Args:
        output_format: Output format ('text' or 'json').

    Returns:
        Formatted report string.
    """
    # Gather all statistics
    stats = {
        "discovery": await get_discovery_stats(),
        "queue": await get_queue_stats(),
        "seeds": await get_seed_stats(),
        "activity": await get_activity_stats(),
    }

    if output_format == "json":
        return format_json_output(stats)
    else:
        return format_statistics(stats)


@click.command()
@click.option(
    "--format",
    "-f",
    type=click.Choice(["text", "json"]),
    default="text",
    help="Output format (text or json)",
)
@click.option(
    "--output",
    "-o",
    type=click.Path(),
    default=None,
    help="Output file path",
)
def main(format: str, output: str | None) -> None:
    """
    Generate status report for the discovery service.

    \b
    Examples:
        python -m src.tools.status_report
        python -m src.tools.status_report --format json
        python -m src.tools.status_report -o report.txt
        python -m src.tools.status_report -f json -o report.json
    """
    logger.info("Generating status report...")

    # Generate report
    report = asyncio.run(generate_report(format))

    # Output
    if output:
        Path(output).write_text(report, encoding="utf-8")
        logger.info(f"Report saved to: {output}")
    else:
        print(report)

    logger.info("Status report complete")


if __name__ == "__main__":
    main()
