"""
Website Discovery Service - Main Entry Point.

This module serves as the entry point for the URL discovery service.
It orchestrates the startup, main loop, and graceful shutdown of the service.

Usage:
    python -m src.main

Or with nox:
    nox -s test  # Development testing
"""

from __future__ import annotations

import asyncio
import signal
import sys
from pathlib import Path
from typing import Any

from loguru import logger

from src.config.settings import settings
from src.database.connection import close_pool, get_pool
from src.database.schema import initialize_schema
import threading 
import signal 
import sys 

shutdown_event = threading.Event()
def handle_shutdown(signum, frame):
    "Only the main thread runs this when CTRL+C is pressed"
    print('\nReceived shutdown signal, shutting down gracefully...')
    shutdown_event.set()
signal.signal(signal.SIGINT, handle_shutdown)

def setup_logging() -> None:
    """
    Configure loguru logging.

    Sets up console and file output with rotation.
    Configured based on settings from config.yaml or .env.
    """
    log_file = Path(settings.logging.file)

    # Ensure log directory exists
    log_file.parent.mkdir(parents=True, exist_ok=True)

    # Remove default handler
    logger.remove()

    # Add console handler (production: only WARNING and above to reduce noise)
    if settings.logging.console_enabled:
        logger.add(
            sys.stdout,
            format="{level} | {message}",
            level=settings.logging.console_level,
            colorize=True,
            filter=lambda record: record["level"].no >= 30 if record["name"] in ("src.crawler.queue", "src.crawler.engine") else True,
        )

    # Add file handler with rotation
    logger.add(
        str(log_file),
        format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {name} | {message}",
        level=settings.logging.level,
        rotation=settings.logging.rotation,
        retention=settings.logging.retention,
        encoding="utf-8",
    )

    logger.info(f"Logging configured: level={settings.logging.level}")


async def initialize_database() -> None:
    """
    Initialize the database connection and schema.

    This function:
    1. Creates the connection pool
    2. Initializes the database schema (tables, indexes, views)
    3. Verifies schema was created successfully
    """
    logger.info("Initializing database...")

    try:
        # Initialize connection pool
        await get_pool()
        logger.info(f"Connected to {settings.database.host}:{settings.database.port}")

        # Initialize schema
        await initialize_schema()
        logger.info("Database schema initialized successfully")

    except Exception as e:
        logger.error(f"Database initialization failed: {e}")
        raise


async def run_discovery_cycle() -> None:
    """
    Run a single discovery cycle.

    This will:
    1. Load seed URLs from database
    2. Process URLs from queue
    3. Extract new domains
    4. Update database
    5. Schedule liveness checks
    """
    logger.info("Running discovery cycle...")

    try:
        # Use DiscoveryEngine to process seeds
        from src.crawler.engine import DiscoveryEngine

        engine = DiscoveryEngine(max_workers=50, discovery_mode="one-time",shutdown_event=shutdown_event)

        # Load seeds from database
        await engine.start()

        # Process queue with timeout (run for up to 10 minutes)
        try:
            await asyncio.wait_for(engine.run(), timeout=600)
        except asyncio.TimeoutError:
            logger.info("Discovery cycle timed out, stopping gracefully")

        await engine.stop()

        logger.info(f"Cycle completed: {len(engine.discovered_domains)} domains discovered")

    except Exception as e:
        logger.error(f"Discovery cycle error: {e}", exc_info=True)
        raise


async def main_loop() -> None:
    """
    Main service loop.

    Runs continuously until interrupted. Processes discovery cycles
    at intervals defined by scheduler settings.
    """
    logger.info("Starting discovery service main loop...")
    cycle_count = 0

    try:
        # 1. Change to check the event
        while not shutdown_event.is_set():
            cycle_count += 1
            logger.info(f"=== Discovery cycle #{cycle_count} starting ===")
            await run_discovery_cycle()
            logger.info(f"=== Discovery cycle #{cycle_count} completed, next cycle in {settings.scheduler.check_interval}s ===")
            
            # 2. Break the sleep into 1-second chunks so it can exit instantly if Ctrl+C is pressed
            for _ in range(settings.scheduler.check_interval):
                if shutdown_event.is_set():
                    break
                await asyncio.sleep(1)
                
    
    except asyncio.CancelledError:
        logger.info("Main loop cancelled gracefully")
        raise
    except Exception as e:
        logger.error(f"Main loop error: {e}")
        raise


async def shutdown() -> None:
    """
    Graceful shutdown handler.

    Performs cleanup operations:
    1. Closes database connection pool
    2. Saves any in-memory state
    3. Logs shutdown confirmation
    """
    logger.info("Shutting down...")

    # Close database pool
    await close_pool()
    logger.info("Database connection closed")

    logger.info("Shutdown complete")


async def signal_handler(signum: int, frame: Any | None = None) -> None:
    """
    Signal handler for graceful shutdown.

    Handles SIGINT (Ctrl+C) and SIGTERM signals.

    Args:
        signum: Signal number received
        frame: Optional frame information
    """
    logger.info(f"Received signal {signum}, initiating shutdown...")

    # Schedule shutdown
    loop = asyncio.get_running_loop()
    loop.create_task(shutdown())


def create_signal_tasks() -> list[asyncio.Task]:
    """
    Create signal handler tasks.

    Returns:
        List of asyncio tasks for signal handlers.
    """
    tasks = []

    for signal_type in (signal.SIGINT, signal.SIGTERM):
        task = asyncio.create_task(
            _handle_signal(signal_type)
        )
        tasks.append(task)

    return tasks


async def _handle_signal(signal_type: signal.Signals) -> None:
    """
    Internal signal handler.

    Args:
        signal_type: The signal type (SIGINT or SIGTERM)
    """
    try:
        await asyncio.Event().wait()
    except asyncio.CancelledError:
        pass


async def _main() -> None:
    """
    Internal main function.

    This is the actual implementation that wraps the main logic
    with proper error handling and cleanup.
    """
    # Setup logging first
    setup_logging()

    logger.info("=" * 50)
    logger.info("Website Discovery Service")
    logger.info(f"Version: {settings.version}")
    logger.info(f"Started: {settings.now().isoformat()}")
    logger.info(f"Timezone: {settings.timezone} (UTC+6)")
    logger.info("=" * 50)

    # Initialize database
    try:
        await initialize_database()
    except Exception as e:
        logger.critical(f"Failed to initialize: {e}")
        sys.exit(1)

    # Set up signal handlers
    
    try:
        # Run main discovery loop
        await main_loop()
    except asyncio.CancelledError:
        logger.info("Service cancelled")
    finally:
        await shutdown()


def main() -> None:
    """
    Main entry point.

    Runs the async main function with proper event loop management.
    """
    try:
        asyncio.run(_main())
    except KeyboardInterrupt:
        logger.info("Service stopped via keyboard interrupt")
        sys.exit(0)
    except Exception as e:
        logger.critical(f"Service fatal error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
