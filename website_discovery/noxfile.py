"""
Nox configuration for website-discovery service.

This file defines reusable development sessions for linting, testing, and formatting.

Usage:
    nox          # Run all sessions with default Python versions
    nox -s lint  # Run only linting
    nox -s test  # Run only tests
    nox -s format -- --check  # Run formatting check without modifying files
"""

from __future__ import annotations

import nox

# Python versions to test against
PYTHON_VERSIONS = ["3.10", "3.11", "3.12","3.13"]

# Default session to run when no session specified
nox.options.sessions = ["lint", "test"]

# Session markers
DEFAULT_PYTHON = "3.11"


@nox.session(python=DEFAULT_PYTHON)
def lint(session: nox.Session) -> None:
    """Run all linters (ruff, mypy)."""
    session.install("-r", "requirements.txt")
    session.install("pre-commit")

    if session.posargs:
        # Run on specific files
        session.run("ruff", "check", *session.posargs)
        session.run("mypy", *session.posargs)
    else:
        # Run on entire project
        session.run("ruff", "check", "src", "tests")
        session.run("mypy", "src")


@nox.session(python=PYTHON_VERSIONS)
def test(session: nox.Session) -> None:
    """Run the test suite."""
    session.install("-r", "requirements.txt")
    session.install("-e", ".[dev]")

    # Run pytest with coverage
    if session.posargs:
        session.run("pytest", *session.posargs, "--cov", "--cov-report=term-missing")
    else:
        session.run(
            "pytest",
            "tests",
            "-v",
            "--cov=src",
            "--cov-report=term-missing",
            "--cov-report=html",
        )


@nox.session(python=DEFAULT_PYTHON)
def format(session: nox.Session) -> None:
    """Format code with black and isort."""
    session.install("black")
    session.install("isort")

    if session.posargs and "--check" in session.posargs:
        # Check without modifying
        session.run("black", "--check", "src", "tests")
        session.run("isort", "--check", "src", "tests")
    else:
        # Format files
        session.run("black", "src", "tests")
        session.run("isort", "src", "tests")


@nox.session(python=DEFAULT_PYTHON)
def pre_commit(session: nox.Session) -> None:
    """Run all pre-commit hooks."""
    session.install("pre-commit")
    session.run("pre-commit", "run", "--all-files")


@nox.session(python=DEFAULT_PYTHON)
def typecheck(session: nox.Session) -> None:
    """Run mypy type checking."""
    session.install("-r", "requirements.txt")
    session.install("-e", ".[dev]")

    if session.posargs:
        session.run("mypy", *session.posargs)
    else:
        session.run("mypy", "src", "tests")


@nox.session(python=DEFAULT_PYTHON)
def docs(session: nox.Session) -> None:
    """Build and check documentation."""
    session.install("-r", "requirements.txt")
    session.install("sphinx", "sphinx-rtd-theme")

    # Build docs (placeholder - add actual docs build when ready)
    session.run("python", "-m", "pydoc", "src", external=True)


@nox.session(python=DEFAULT_PYTHON)
def clean(session: nox.Session) -> None:
    """Remove generated files."""
    # Remove common generated directories
    dirs = [
        ".nox",
        ".pytest_cache",
        ".ruff_cache",
        ".mypy_cache",
        "htmlcov",
        "__pycache__",
        "build",
        "dist",
        "*.egg-info",
    ]

    for dir_name in dirs:
        session.run("rm", "-rf", dir_name, external=True)
