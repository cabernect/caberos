"""Async SQLAlchemy engine, session factory, and FastAPI dependency.

The database backend is pluggable (D5):
- SQLite (default): local-first, zero config, FTS5 for search
- Postgres: set AGENTOS_DATABASE_URL=postgresql+asyncpg://user:pass@host/db
- Others: implement DatabaseBackend and register in the factory

The rest of the codebase talks to AsyncSession and is DB-agnostic.
"""

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from .config import settings
from .db_backends import get_backend

# Select the backend from the configured URL
_backend = get_backend(settings.db_url)

# Create the engine (backend handles PRAGMAs, connection args, etc.)
engine = _backend.create_engine(settings.db_url)

async_session_factory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency that yields an async DB session."""
    async with async_session_factory() as session:
        yield session


async def init_db() -> None:
    """Create all tables, apply schema patches, and set up full-text search.

    Delegates to the active backend — each backend handles its own
    schema initialization, incremental patches, and FTS setup.
    """
    async with engine.begin() as conn:
        await _backend.init_schema(conn)
        await _backend.init_fulltext_search(conn)
