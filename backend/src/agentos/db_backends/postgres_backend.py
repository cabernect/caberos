"""PostgreSQL backend — for multi-user or hosted deployments.

Uses asyncpg as the async driver. Full-text search via tsvector + GIN index.
Schema management via Alembic (recommended) or create_all + patches.
"""

import re
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from .base import DatabaseBackend


class PostgresBackend(DatabaseBackend):
    """PostgreSQL + asyncpg — for hosted / multi-user deployments."""

    @property
    def name(self) -> str:
        return "postgresql"

    def create_engine(self, db_url: str) -> AsyncEngine:
        # asyncpg doesn't need check_same_thread; it has its own connection pool.
        # statement_timeout prevents runaway queries (in milliseconds).
        engine = create_async_engine(
            db_url,
            echo=False,
            pool_pre_ping=True,  # detect dropped connections
            connect_args={
                "server_settings": {
                    "statement_timeout": "30000",  # 30s
                    "application_name": "caberos",
                },
            },
        )
        return engine

    async def init_schema(self, conn: Any) -> None:
        from ..models import (  # noqa: F401
            agent,
            approval,
            audit,
            capability,
            connector,
            contact,
            document,
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
            ("mcp_servers", "require_approval", "BOOLEAN DEFAULT TRUE"),
            ("mcp_servers", "oauth_config", "TEXT"),
            ("sessions", "channel", "VARCHAR(50)"),
            ("sessions", "external_user_id", "VARCHAR(255)"),
            ("channel_configs", "approval_policy", "VARCHAR(20) DEFAULT 'deny'"),
            ("documents", "structure_json", "TEXT NOT NULL DEFAULT '{}'"),
            ("document_chunks", "source_location", "TEXT"),
            ("document_chunks", "block_type", "VARCHAR(30) NOT NULL DEFAULT 'paragraph'"),
        ]
        for table, column, col_type in patches:
            if not await self.column_exists(conn, table, column):
                await self.add_column(conn, table, column, col_type)

        # Migrate existing channels to auto_approve to preserve current behavior.
        await conn.execute(
            text(
                "UPDATE channel_configs SET approval_policy = 'auto_approve' "
                "WHERE approval_policy = 'deny' OR approval_policy IS NULL"
            )
        )

    async def init_fulltext_search(self, conn: Any) -> None:
        """Create tsvector + GIN index for semantic recall (D34).

        Postgres full-text search: we add a generated tsvector column to
        memory_entries and a GIN index on it. The recall query uses
        to_tsquery / plainto_tsquery for matching.

        Note: we use 'english' as the default text search config. For
        multilingual support, this could be configurable.
        """
        # Add generated tsvector columns if they don't exist
        if not await self.column_exists(conn, "memory_entries", "search_vector"):
            await conn.execute(
                text(
                    "ALTER TABLE memory_entries "
                    "ADD COLUMN search_vector tsvector "
                    "GENERATED ALWAYS AS "
                    "(to_tsvector('english', coalesce(key, '') || ' ' || coalesce(value, ''))) STORED"
                )
            )
            await conn.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_memory_entries_search "
                    "ON memory_entries USING gin(search_vector)"
                )
            )

        if not await self.column_exists(conn, "document_chunks", "search_vector"):
            await conn.execute(
                text(
                    "ALTER TABLE document_chunks "
                    "ADD COLUMN search_vector tsvector "
                    "GENERATED ALWAYS AS "
                    "(to_tsvector('simple', coalesce(text, '') || ' ' || coalesce(heading_path, ''))) STORED"
                )
            )
            await conn.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_document_chunks_search "
                    "ON document_chunks USING gin(search_vector)"
                )
            )

    async def column_exists(self, conn: Any, table: str, column: str) -> bool:
        result = await conn.execute(
            text(
                "SELECT 1 FROM information_schema.columns "
                "WHERE table_name = :table AND column_name = :column"
            ),
            {"table": table, "column": column},
        )
        return result.fetchone() is not None

    @staticmethod
    def _identifier(value: str) -> str:
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", value):
            raise ValueError("Invalid database identifier")
        return value

    async def add_column(self, conn: Any, table: str, column: str, col_type: str) -> None:
        table = self._identifier(table)
        column = self._identifier(column)
        if col_type not in {
            "TEXT",
            "VARCHAR(36)",
            "VARCHAR(30) NOT NULL DEFAULT 'paragraph'",
            "VARCHAR(50)",
            "VARCHAR(255)",
            "VARCHAR(20) DEFAULT 'deny'",
            "BOOLEAN DEFAULT TRUE",
            "TEXT NOT NULL DEFAULT '[]'",
            "TEXT NOT NULL DEFAULT '{}'",
        }:
            raise ValueError("Invalid database column type")
        await conn.execute(
            text(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column} {col_type}")
        )
