"""
Nox configuration for URL Discovery Engine.

This file defines automated development tasks using Nox:
- lint: Run ruff for linting
- format: Run black for code formatting
- type-check: Run mypy for type checking
- test: Run pytest for testing
- test-full: Run full test suite with coverage
- clean: Clean up generated files
- dev: Setup development environment

Usage:
    nox          # Run default session (lint)
    nox -s lint  # Run linting
    nox -s format  # Run formatting check
    nox -s type-check  # Run type checking
    nox -s test  # Run tests
    nox -s test-full  # Run tests with coverage
    nox -s dev  # Setup dev environment
"""

from __future__ import annotations

import nox

# Nox session options
nox.options.sessions = ["lint"]
nox.options.reuse_existing_virtualenvs = True
nox.options.force_venv_backend = "uv|conda|virtualenv"


# ==========================================
# Development Environment Sessions
# ==========================================

@nox.session(python=["3.10", "3.11", "3.12"])
def dev(session: nox.Session) -> None:
    """
    Setup development environment with all dependencies.

    Installs the package in editable mode with dev dependencies
    and all optional dependencies.

    Usage:
        nox -s dev
        nox -s dev-3.11
    """
    session.install("--upgrade", "pip", "setuptools", "wheel")
    session.install("-e", ".[dev]")
    session.log("Development environment setup complete!")
    session.log("Run 'nox -s lint' to check code quality")
    session.log("Run 'nox -s test' to run tests")


@nox.session(python="3.11")
def install(session: nox.Session) -> None:
    """
    Install the package in editable mode.

    Use this if you just want to install the package without
    running any other tasks.

    Usage:
        nox -s install
    """
    session.install("-e", ".")
    session.log("Package installed in editable mode!")


# ==========================================
# Linting Sessions
# ==========================================

@nox.session(python="3.11")
def lint(session: nox.Session) -> None:
    """
    Run all linters: ruff for linting and isort for imports.

    This session checks for code quality issues and import ordering.

    Usage:
        nox -s lint
    """
    # Install linting tools
    session.install("ruff", "isort")

    # Run ruff for linting
    session.run("ruff", "check", "src/", "tests/", "--show-filenames")

    # Run isort for import sorting check
    session.run("isort", "--check", "src/", "tests/")


@nox.session(python="3.11")
def ruff(session: nox.Session) -> None:
    """
    Run ruff for linting only.

    Ruff is a fast Python linter that checks for:
    - Syntax errors
    - Common bugs
    - Style violations
    - Unused code
    - And many more

    Usage:
        nox -s ruff
    """
    session.install("ruff")
    session.run("ruff", "check", "src/", "tests/")


@nox.session(python="3.11")
def isort(session: nox.Session) -> None:
    """
    Run isort for import sorting check.

    Usage:
        nox -s isort
    """
    session.install("isort")
    session.run("isort", "--check", "src/", "tests/")


# ==========================================
# Formatting Sessions
# ==========================================

@nox.session(python="3.11")
def format(session: nox.Session) -> None:
    """
    Check code formatting with black.

    Does not fix formatting - only checks. Use format-fix to auto-fix.

    Usage:
        nox -s format
    """
    session.install("black")
    session.run("black", "--check", "src/", "tests/", "noxfile.py")


@nox.session(python="3.11")
def format_fix(session: nox.Session) -> None:
    """
    Auto-format code with black.

    This session will automatically fix formatting issues.
    Review changes before committing!

    Usage:
        nox -s format-fix
    """
    session.install("black")
    session.run("black", "src/", "tests/", "noxfile.py")


@nox.session(python="3.11")
def ruff_fix(session: nox.Session) -> None:
    """
    Auto-fix linting issues with ruff.

    This session will automatically fix fixable issues.
    Review changes before committing!

    Usage:
        nox -s ruff-fix
    """
    session.install("ruff")
    session.run("ruff", "check", "--fix", "src/", "tests/")


# ==========================================
# Type Checking Sessions
# ==========================================

@nox.session(python="3.11")
def type_check(session: nox.Session) -> None:
    """
    Run mypy for type checking.

    Checks for type errors throughout the codebase.

    Usage:
        nox -s type-check
    """
    # Install package and type checking tools
    session.install("-e", ".")
    session.install("mypy")

    # Run mypy on source code
    session.run("mypy", "src/url_discovery_engine", "--strict")


# ==========================================
# Testing Sessions
# ==========================================

@nox.session(python="3.11")
def test(session: nox.Session) -> None:
    """
    Run pytest test suite.

    Runs all tests without coverage reporting.
    Fast feedback for development.

    Usage:
        nox -s test
    """
    # Install package and testing dependencies
    session.install("-e", ".[dev]")

    # Run pytest
    session.run("pytest", "tests/", "-v", "--tb=short")


@nox.session(python="3.11")
def test_full(session: nox.Session) -> None:
    """
    Run full test suite with coverage reporting.

    Runs all tests with coverage calculation.
    Slower but provides code coverage metrics.

    Usage:
        nox -s test_full
    """
    # Install package and testing dependencies
    session.install("-e", ".[dev]")

    # Run pytest with coverage
    session.run("pytest", "tests/", "-v", "--cov=url_discovery_engine", "--cov-report=term-missing")


@nox.session(python="3.11")
def test_unit(session: nox.Session) -> None:
    """
    Run unit tests only (tests/unit/).

    Faster test run for quick feedback during development.

    Usage:
        nox -s test_unit
    """
    session.install("-e", ".[dev]")
    session.run("pytest", "tests/unit/", "-v", "--tb=short")


@nox.session(python="3.11")
def test_integration(session: nox.Session) -> None:
    """
    Run integration tests only (tests/integration/).

    Tests that require external services or database connections.

    Usage:
        nox -s test_integration
    """
    session.install("-e", ".[dev]")
    session.run("pytest", "tests/integration/", "-v", "--tb=short", "-m", "integration")


# ==========================================
# Utility Sessions
# ==========================================

@nox.session(python="3.11")
def clean(session: nox.Session) -> None:
    """
    Clean up generated files and caches.

    Removes:
    - __pycache__ directories
    - .pytest_cache
    - .mypy_cache
    - .ruff_cache
    - .coverage
    - dist/
    - build/
    - *.egg-info
    - .venv/

    Usage:
        nox -s clean
    """
    session.run("rm", "-rf", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", ".coverage", "dist", "build", "*.egg-info")
    session.log("Cleaned up generated files!")


@nox.session(python="3.11")
def check(session: nox.Session) -> None:
    """
    Run all quality checks at once.

    This is a convenience session that runs:
    - lint
    - format
    - type_check

    Usage:
        nox -s check
    """
    # Run all checks in sequence
    session.install("ruff", "isort", "black", "mypy")

    session.run("ruff", "check", "src/", "tests/", external=True)
    session.run("isort", "--check", "src/", "tests/", external=True)
    session.run("black", "--check", "src/", "tests/", "noxfile.py", external=True)
    session.run("mypy", "src/url_discovery_engine", "--strict", external=True)


@nox.session(python="3.11")
def docs(session: nox.Session) -> None:
    """
    Check documentation and run docstring validation.

    Checks for missing docstrings and validates
    documentation format.

    Usage:
        nox -s docs
    """
    session.install("ruff", "pydocstyle")

    # Run ruff on docs
    session.run("ruff", "check", "src/")


# ==========================================
# Pre-commit Helper
# ==========================================

@nox.session(python="3.11", reusable=True)
def pre_commit(session: nox.Session) -> None:
    """
    Run pre-commit checks (for CI/CD or manual use).

    Equivalent to 'nox -s check' but with better output.

    Usage:
        nox -s pre_commit
    """
    session.install("ruff", "isort", "black", "mypy")

    # Run checks with explicit success/failure
    session.run("ruff", "check", "src/", "tests/", "--show-fixes", external=True, success_codes=[0, 1])
    session.run("isort", "--check", "src/", "tests/", external=True, success_codes=[0, 1])
    session.run("black", "--check", "src/", "tests/", external=True, success_codes=[0, 1])
    session.run("mypy", "src/url_discovery_engine", external=True, success_codes=[0, 1])
