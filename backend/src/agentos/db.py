"""Async SQLAlchemy engine, session factory, and FastAPI dependency.

The database backend is pluggable (D5):
- SQLite (default): local-first, zero config, FTS5 for search
- Postgres: set AGENTOS_DATABASE_URL=postgresql+asyncpg://user:pass@host/db
- Others: implement DatabaseBackend and register in the factory

The rest of the codebase talks to AsyncSession and is DB-agnostic.
"""

import asyncio
import logging
from collections.abc import AsyncGenerator, Awaitable, Callable

from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from .config import settings
from .db_backends import get_backend

log = logging.getLogger(__name__)


def is_database_locked(error: BaseException) -> bool:
    """Return whether an operational error is a transient database lock."""
    current: BaseException | None = error
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        message = str(current).lower()
        if any(
            marker in message
            for marker in (
                "database is locked",
                "database table is locked",
                "database schema is locked",
                "database is busy",
            )
        ):
            return True
        current = current.__cause__ or current.__context__
    return False


async def retry_locked_transaction[T](
    operation: Callable[[], Awaitable[T]],
    session: AsyncSession,
    operation_name: str,
) -> T:
    """Retry a complete transaction after transient database-lock failures."""
    max_retries = max(0, settings.db_lock_retries)
    for attempt in range(max_retries + 1):
        try:
            return await operation()
        except OperationalError as error:
            if not is_database_locked(error):
                raise
            await session.rollback()
            if attempt >= max_retries:
                raise
            delay = settings.db_lock_retry_delay * (2**attempt)
            log.warning(
                "Database locked during %s; retrying in %.2fs (%d/%d)",
                operation_name,
                delay,
                attempt + 1,
                max_retries,
            )
            await asyncio.sleep(delay)
    raise RuntimeError("Database transaction retry loop exhausted")


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
