"""Database backend interface — plug out / plug in (D5).

Each backend handles its own:
- Engine creation (driver, connection args, event listeners)
- Schema initialization (create_all + incremental patches)
- Full-text search (FTS5 for SQLite, tsvector for Postgres, etc.)

The rest of the codebase talks to SQLAlchemy AsyncSession and is DB-agnostic.
"""

from abc import ABC, abstractmethod
from typing import Any

from sqlalchemy.ext.asyncio import AsyncEngine


class DatabaseBackend(ABC):
    """Abstract base for database backends."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Backend name (e.g. 'sqlite', 'postgresql')."""

    @abstractmethod
    def create_engine(self, db_url: str) -> AsyncEngine:
        """Create and return an async SQLAlchemy engine.

        This is where backend-specific connection args, PRAGMAs,
        and event listeners are configured.
        """

    @abstractmethod
    async def init_schema(self, conn: Any) -> None:
        """Create all tables + apply incremental schema patches.

        Called inside `engine.begin()` — receives a raw SQLAlchemy connection.
        """

    @abstractmethod
    async def init_fulltext_search(self, conn: Any) -> None:
        """Create full-text search indexes for semantic recall (D34).

        SQLite: FTS5 virtual table.
        Postgres: tsvector + GIN index.
        Others: backend-specific.
        """

    @abstractmethod
    async def column_exists(self, conn: Any, table: str, column: str) -> bool:
        """Check if a column exists in a table (for incremental patches)."""

    @abstractmethod
    async def add_column(self, conn: Any, table: str, column: str, col_type: str) -> None:
        """Add a column to an existing table (for incremental patches)."""
