"""Async SQLAlchemy engine, session factory, and FastAPI dependency."""

from collections.abc import AsyncGenerator

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from .config import settings

# Ensure the data directory exists
settings.db_path.parent.mkdir(parents=True, exist_ok=True)

engine = create_async_engine(
    settings.db_url,
    echo=False,
    connect_args={"check_same_thread": False},
)


# Enable WAL mode + busy timeout on every connection
# WAL allows concurrent readers with one writer.
# busy_timeout makes SQLite wait (up to 5s) for a lock instead of
# immediately throwing "database is locked" when another connection
# is writing. This is essential for async FastAPI where multiple
# endpoints + background tasks share the same SQLite file.
@event.listens_for(engine.sync_engine, "connect")
def _set_wal_mode(dbapi_conn, _connection_record):
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA busy_timeout=5000")  # 5 seconds
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
    """Create all tables and apply incremental schema patches.

    For fresh DBs: create_all() creates every table to match the models.
    For existing DBs: create_all() is a no-op on existing tables, then we
    run _apply_schema_patches() to add any new columns via ALTER TABLE.

    This is simpler than Alembic for a local-first SQLite app:
    - One user, one DB file, data is re-seedable
    - Schema changes are rare and simple (add a column)
    - No migration files to maintain, no event loop workarounds
    """
    from .models import (  # noqa: F401 — import all models to register them
        agent,
        approval,
        audit,
        capability,
        connector,
        contact,
        elicitation,
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
        await _apply_schema_patches(conn)


async def _apply_schema_patches(conn) -> None:
    """Add columns that were introduced after the initial schema.

    Each patch checks if the column exists before adding it (idempotent).
    SQLite doesn't support IF NOT EXISTS for ADD COLUMN, so we check
    pragma_table_info first.
    """
    patches = [
        # (table, column, column_def)
        ("messages", "attachments", "TEXT"),
        ("providers", "custom_models", "TEXT NOT NULL DEFAULT '[]'"),
        ("messages", "subagent_id", "VARCHAR(36)"),
    ]

    for table, column, col_type in patches:
        result = await conn.execute(text(f"PRAGMA table_info({table})"))
        existing_cols = {row[1] for row in result.fetchall()}
        if column not in existing_cols:
            await conn.execute(
                text(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}")
            )
