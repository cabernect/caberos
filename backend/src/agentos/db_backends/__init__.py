"""Pluggable database backends.

SQLite is the default (local-first, zero config). Postgres is a config swap
via AGENTOS_DATABASE_URL=postgresql+asyncpg://user:pass@host/db.

To add a new backend:
1. Create a new module in this package (e.g. mysql_backend.py)
2. Implement the DatabaseBackend ABC
3. Register it in the factory (get_backend) by URL scheme
"""

from .base import DatabaseBackend
from .factory import get_backend

__all__ = ["DatabaseBackend", "get_backend"]
