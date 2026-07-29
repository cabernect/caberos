"""Async SQLAlchemy engine, session factory, and FastAPI dependency."""

from collections.abc import AsyncGenerator

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from .config import settings

# Ensure the data directory exists
settings.db_path.parent.mkdir(parents=True, exist_ok=True)

engine = create_async_engine(
    settings.db_url,
    echo=False,
    connect_args={"check_same_thread": False},
)


# Enable WAL mode on every connection
@event.listens_for(engine.sync_engine, "connect")
def _set_wal_mode(dbapi_conn, _connection_record):
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


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
    """Create all tables (used in tests and startup)."""
    from .models import (  # noqa: F401 — import all models to register them
        agent,
        approval,
        audit,
        capability,
        connector,
        contact,
        memory,
        operator,
        provider,
        run,
        session,
        sub_agent,
    )
    from .models.base import Base

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
