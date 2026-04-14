"""
Logging configuration for URL Discovery Engine.

This module provides a centralized logging setup using Loguru with:
- Colored console output for development
- File logging with rotation for production
- Configurable log levels
- Custom log format with timestamps and module names

Usage:
    from src.url_discovery_engine.logger import get_logger

    logger = get_logger(__name__)
    logger.info("This is an info message")
    logger.error("This is an error message")
"""

import sys
from pathlib import Path
from typing import Any

from loguru import logger as loguru_logger

# Import settings at runtime to avoid circular imports
# We'll configure logger based on settings


def get_logger(module_name: str = __name__) -> Any:
    """
    Get a logger instance configured for the given module.

    This function sets up Loguru with appropriate handlers based on the
    application settings. It returns a logger instance ready to use.

    Args:
        module_name: The name of the module requesting the logger.
                    Usually passed as __name__.

    Returns:
        A Loguru logger instance configured for this module.

    Example:
        >>> logger = get_logger(__name__)
        >>> logger.info("Starting application")
        >>> logger.error("An error occurred")
    """
    try:
        # Import settings here to avoid circular imports
        from .config.settings import settings

        # Get log level from settings
        log_level = settings.logging.level.upper()

        # Remove all existing handlers
        loguru_logger.remove()

        # Add console handler with colored output
        loguru_logger.add(
            sys.stderr,
            format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
                   "<level>{level: <8}</level> | "
                   "<cyan>{name}:{line}</cyan> - "
                   "<level>{message}</level>",
            level=log_level,
            colorize=True,
            enqueue=True,  # Thread-safe
            backtrace=True,  # Show full traceback
            diagnose=True,  # Show variable values in tracebacks
        )

        # Add file handler for persistent logging
        log_file = Path(settings.logging.file)
        log_file.parent.mkdir(parents=True, exist_ok=True)

        loguru_logger.add(
            str(log_file),
            format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{line} - {message}",
            level=log_level,
            rotation="10 MB",  # Rotate files at 10MB
            retention="30 days",  # Keep logs for 30 days
            compression="zip",  # Compress old logs
            enqueue=True,
            backtrace=True,
            diagnose=False,  # Don't include variables in file logs (saves space)
        )

        # Return the configured logger filtered by module
        return loguru_logger.bind(module=module_name)

    except Exception as e:
        # Fallback to basic logging if settings fail
        print(f"Warning: Could not configure logger: {e}", file=sys.stderr)
        loguru_logger.add(
            sys.stderr,
            format="{time:HH:mm:ss} | {level} | {message}",
            level="INFO",
            colorize=True,
        )
        return loguru_logger.bind(module=module_name)


def configure_logger(
    level: str = "INFO",
    log_file: str | None = None,
    console_output: bool = True,
    file_output: bool = True,
) -> Any:
    """
    Manually configure the logger with custom settings.

    This function provides a way to configure logging outside of the
    standard settings, useful for testing or special use cases.

    Args:
        level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL).
        log_file: Path to log file. If None, no file logging.
        console_output: Whether to log to console.
        file_output: Whether to log to file.

    Returns:
        Configured logger instance.

    Example:
        >>> logger = configure_logger(level="DEBUG", console_output=True)
        >>> logger.debug("Debug message")
    """
    # Remove all existing handlers
    loguru_logger.remove()

    if console_output:
        loguru_logger.add(
            sys.stderr,
            format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
                   "<level>{level: <8}</level> | "
                   "<cyan>{name}:{line}</cyan> - "
                   "<level>{message}</level>",
            level=level.upper(),
            colorize=True,
            enqueue=True,
            backtrace=True,
            diagnose=True,
        )

    if file_output and log_file:
        loguru_logger.add(
            log_file,
            format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {name}:{line} - {message}",
            level=level.upper(),
            rotation="10 MB",
            retention="30 days",
            compression="zip",
            enqueue=True,
        )

    return loguru_logger.bind(module=__name__)


# Create a default logger instance when this module is imported
# This allows immediate use without calling get_logger()
_logger = get_logger("url_discovery_engine")
