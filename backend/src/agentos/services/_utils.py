"""Shared utilities for the service layer."""

import sqlite3
from pathlib import Path


def get_app_version() -> str:
    """Get the application version from package metadata."""
    try:
        from importlib.metadata import version

        return version("agentos")
    except Exception:
        return "unknown"


def check_db_integrity(db_path: Path) -> str:
    """Run PRAGMA integrity_check on a SQLite database file.

    Returns "ok" or the error string.
    """
    try:
        conn = sqlite3.connect(str(db_path))
        result = conn.execute("PRAGMA integrity_check").fetchone()[0]
        conn.close()
        return result
    except sqlite3.DatabaseError as e:
        return str(e)
