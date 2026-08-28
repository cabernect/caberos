"""Shared utilities for the service layer."""

import logging
import sqlite3
from pathlib import Path

log = logging.getLogger(__name__)


def get_app_version() -> str:
    """Get the application version from package metadata."""
    try:
        from importlib.metadata import version

        return version("agentos")
    except Exception:
        return "unknown"


def check_db_integrity(db_path: Path) -> str:
    """Run PRAGMA integrity_check on a SQLite database file.

    Returns "ok" or "failed". Detailed failures are logged for diagnostics.
    """
    try:
        conn = sqlite3.connect(str(db_path))
        try:
            result = conn.execute("PRAGMA integrity_check").fetchone()
        finally:
            conn.close()
    except sqlite3.DatabaseError:
        log.exception("SQLite integrity check could not run for %s", db_path)
        return "failed"

    if result and result[0] == "ok":
        return "ok"

    log.error(
        "SQLite integrity check failed for %s: %r",
        db_path,
        result[0] if result else "no result",
    )
    return "failed"
