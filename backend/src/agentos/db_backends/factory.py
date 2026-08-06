"""Database backend factory — selects the right backend from the URL scheme.

Usage:
    from agentos.db_backends import get_backend
    backend = get_backend("sqlite+aiosqlite:///data/agentos.db")
    engine = backend.create_engine(db_url)

To add a new backend:
1. Implement DatabaseBackend in a new module
2. Register the URL scheme here
"""

from .base import DatabaseBackend
from .postgres_backend import PostgresBackend
from .sqlite_backend import SQLiteBackend

# Registry: URL scheme prefix → backend class
_BACKENDS: dict[str, type[DatabaseBackend]] = {
    "sqlite": SQLiteBackend,
    "postgresql": PostgresBackend,
    "postgres": PostgresBackend,  # common alias
}


def get_backend(db_url: str) -> DatabaseBackend:
    """Return the appropriate backend for the given database URL.

    Auto-detects from the URL scheme:
    - sqlite+aiosqlite://... → SQLiteBackend
    - postgresql+asyncpg://... → PostgresBackend

    Raises ValueError for unsupported schemes.
    """
    scheme = db_url.split("://")[0].split("+")[0] if "://" in db_url else db_url

    backend_cls = _BACKENDS.get(scheme)
    if backend_cls is None:
        raise ValueError(
            f"Unsupported database scheme: '{scheme}'. Supported: {', '.join(_BACKENDS.keys())}"
        )

    return backend_cls()


def register_backend(scheme: str, backend_cls: type[DatabaseBackend]) -> None:
    """Register a custom backend at runtime (for plugins)."""
    _BACKENDS[scheme] = backend_cls
