"""SQLite backend — the default (local-first, zero config, D5).

Uses aiosqlite as the async driver. Enables WAL mode + busy timeout for
concurrent read/write support. FTS5 for semantic recall.
"""

from typing import Any

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from .base import DatabaseBackend


class SQLiteBackend(DatabaseBackend):
    """SQLite + aiosqlite — default backend for local-first operation."""

    @property
    def name(self) -> str:
        return "sqlite"

    def create_engine(self, db_url: str) -> AsyncEngine:
        engine = create_async_engine(
            db_url,
            echo=False,
            connect_args={"check_same_thread": False},
        )

        # Enable WAL mode + busy timeout on every connection.
        # WAL allows concurrent readers with one writer.
        # busy_timeout makes SQLite wait (up to 5s) for a lock instead of
        # immediately throwing "database is locked".
        @event.listens_for(engine.sync_engine, "connect")
        def _set_wal_mode(dbapi_conn, _connection_record):
            cursor = dbapi_conn.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA busy_timeout=15000")
            cursor.close()

        return engine

    async def init_schema(self, conn: Any) -> None:
        from ..models import (  # noqa: F401
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
        from ..models.base import Base

        await conn.run_sync(Base.metadata.create_all)
        await self._apply_schema_patches(conn)

    async def _apply_schema_patches(self, conn: Any) -> None:
        """Add columns introduced after the initial schema (idempotent)."""
        patches = [
            ("messages", "attachments", "TEXT"),
            ("providers", "custom_models", "TEXT NOT NULL DEFAULT '[]'"),
            ("messages", "subagent_id", "VARCHAR(36)"),
            ("memory_entries", "run_id", "VARCHAR(36)"),
            ("sessions", "summary", "TEXT"),
            ("sessions", "closed", "BOOLEAN DEFAULT 0"),
            ("sessions", "conversation_summary", "TEXT"),
        ]
        for table, column, col_type in patches:
            if not await self.column_exists(conn, table, column):
                await self.add_column(conn, table, column, col_type)

    async def init_fulltext_search(self, conn: Any) -> None:
        """Create FTS5 virtual tables for semantic recall (D34) and episodic memory."""
        # 1. Working memory FTS (existing — for memory_recall tool)
        result = await conn.execute(
            text("SELECT name FROM sqlite_master WHERE type='table' AND name='memory_fts'")
        )
        if result.fetchone() is None:
            await conn.execute(
                text(
                    "CREATE VIRTUAL TABLE memory_fts USING fts5("
                    "content, entry_id UNINDEXED, contact_id UNINDEXED, "
                    "agent_id UNINDEXED, tokenize='porter unicode61')"
                )
            )

        # 2. Raw messages FTS (episodic — exact recall via search_history tool)
        result = await conn.execute(
            text("SELECT name FROM sqlite_master WHERE type='table' AND name='messages_fts'")
        )
        if result.fetchone() is None:
            await conn.execute(
                text(
                    "CREATE VIRTUAL TABLE messages_fts USING fts5("
                    "content, message_id UNINDEXED, run_id UNINDEXED, "
                    "session_id UNINDEXED, agent_id UNINDEXED, "
                    "tokenize='porter unicode61')"
                )
            )

        # 3. Session summaries FTS (episodic — topical recall at run start)
        result = await conn.execute(
            text("SELECT name FROM sqlite_master WHERE type='table' AND name='session_summaries_fts'")
        )
        if result.fetchone() is None:
            await conn.execute(
                text(
                    "CREATE VIRTUAL TABLE session_summaries_fts USING fts5("
                    "summary, session_id UNINDEXED, agent_id UNINDEXED, "
                    "contact_id UNINDEXED, tokenize='porter unicode61')"
                )
            )

    async def column_exists(self, conn: Any, table: str, column: str) -> bool:
        result = await conn.execute(text(f"PRAGMA table_info({table})"))
        existing_cols = {row[1] for row in result.fetchall()}
        return column in existing_cols

    async def add_column(self, conn: Any, table: str, column: str, col_type: str) -> None:
        await conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}"))
