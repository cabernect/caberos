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
            channel_config,
            contact,
            document,
            elicitation,
            execution_manifest,
            mcp,
            memory,
            model_call,
            notification,
            operator,
            operator_session,
            provider,
            run,
            session,
            source,
            sub_agent,
            web_source,
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
            ("run_sources", "message_id", "VARCHAR(36)"),
            ("memory_entries", "run_id", "VARCHAR(36)"),
            ("sessions", "summary", "TEXT"),
            ("sessions", "closed", "BOOLEAN DEFAULT FALSE"),
            ("sessions", "conversation_summary", "TEXT"),
            ("channel_configs", "mode", "VARCHAR(20) DEFAULT 'polling'"),
            ("runs", "context_tokens", "INTEGER DEFAULT 0"),
            ("runs", "max_context_tokens", "INTEGER DEFAULT 0"),
            ("runs", "compacted", "BOOLEAN DEFAULT FALSE"),
            ("runs", "context_breakdown", "TEXT NOT NULL DEFAULT '{}'"),
            ("runs", "loaded_capabilities", "TEXT NOT NULL DEFAULT '[]'"),
            ("mcp_tools", "effects", "TEXT"),
            ("audit_records", "outcome", "VARCHAR(20) DEFAULT 'ok'"),
            ("documents", "semantic_state", "VARCHAR(20) NOT NULL DEFAULT 'na'"),
            ("document_chunks", "kind", "VARCHAR(10) NOT NULL DEFAULT 'chunk'"),
            ("document_chunks", "parent_id", "VARCHAR(36)"),
            # W10 unified model-call ledger.
            ("model_calls", "kind", "VARCHAR(20) NOT NULL DEFAULT 'chat'"),
            ("model_calls", "purpose", "VARCHAR(20) NOT NULL DEFAULT 'reasoning'"),
            ("model_calls", "thinking_tokens", "INTEGER"),
            ("model_calls", "detail", "JSONB"),
            # W10 correlation columns.
            ("approval_requests", "call_id", "VARCHAR(255)"),
            ("approval_requests", "sub_agent_id", "VARCHAR(36)"),
            ("elicitation_requests", "call_id", "VARCHAR(255)"),
            ("elicitation_requests", "sub_agent_id", "VARCHAR(36)"),
            ("terminal_sessions", "call_id", "VARCHAR(255)"),
            ("terminal_sessions", "sub_agent_id", "VARCHAR(36)"),
            ("artifact_revisions", "call_id", "VARCHAR(255)"),
            ("artifact_revisions", "sub_agent_id", "VARCHAR(36)"),
            ("run_sources", "call_id", "VARCHAR(255)"),
            ("run_sources", "sub_agent_id", "VARCHAR(36)"),
            ("audit_records", "call_id", "VARCHAR(255)"),
            ("audit_records", "created_at", "TIMESTAMPTZ"),
            ("audit_records", "effects", "JSONB"),
        ]
        for table, column, col_type in patches:
            if not await self.column_exists(conn, table, column):
                await self.add_column(conn, table, column, col_type)

        # W10 — run/agent are nullable so embedding calls without a run can
        # land in the unified ledger (idempotent), and the run_id FK is
        # dropped by its actual constraint name so orphan ledger rows
        # survive. Custom-named constraints are handled; unrelated
        # constraints are untouched.
        await conn.execute(text("ALTER TABLE model_calls ALTER COLUMN run_id DROP NOT NULL"))
        await conn.execute(text("ALTER TABLE model_calls ALTER COLUMN agent_id DROP NOT NULL"))
        fk_rows = await conn.execute(
            text(
                "SELECT c.conname FROM pg_constraint AS c "
                "JOIN pg_attribute AS a ON a.attrelid = c.conrelid "
                "AND a.attnum = ANY(c.conkey) "
                "WHERE c.conrelid = 'model_calls'::regclass "
                "AND c.contype = 'f' AND a.attname = 'run_id'"
            )
        )
        for (conname,) in fk_rows.fetchall():
            quoted = conname.replace('"', '""')
            await conn.execute(text(f'ALTER TABLE model_calls DROP CONSTRAINT "{quoted}"'))
        # Embedding calls moved into the unified model_calls ledger.
        await conn.execute(text("DROP TABLE IF EXISTS embedding_calls"))

        # W10 ledger indexes — after the additive patches above.
        for index_sql in (
            "CREATE INDEX IF NOT EXISTS ix_model_calls_run_created "
            "ON model_calls(run_id, created_at)",
            "CREATE INDEX IF NOT EXISTS ix_model_calls_provider_model "
            "ON model_calls(provider_id, model_name)",
            "CREATE INDEX IF NOT EXISTS ix_model_calls_kind_created "
            "ON model_calls(kind, created_at)",
            "CREATE INDEX IF NOT EXISTS ix_audit_run_call_sub "
            "ON audit_records(run_id, call_id, sub_agent_id)",
            "CREATE INDEX IF NOT EXISTS ix_approval_run_call_sub "
            "ON approval_requests(run_id, call_id, sub_agent_id)",
            "CREATE INDEX IF NOT EXISTS ix_elicitation_run_call_sub "
            "ON elicitation_requests(run_id, call_id, sub_agent_id)",
            "CREATE INDEX IF NOT EXISTS ix_terminal_run_call_sub "
            "ON terminal_sessions(run_id, call_id, sub_agent_id)",
            "CREATE INDEX IF NOT EXISTS ix_run_sources_run_call_sub "
            "ON run_sources(run_id, call_id, sub_agent_id)",
            "CREATE INDEX IF NOT EXISTS ix_artifact_revisions_source_call "
            "ON artifact_revisions(source_run_id, call_id, sub_agent_id)",
        ):
            await conn.execute(text(index_sql))

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
            "INTEGER",
            "INTEGER DEFAULT 0",
            "TIMESTAMPTZ",
            "JSONB",
            "VARCHAR(36)",
            "VARCHAR(20) NOT NULL DEFAULT 'chat'",
            "VARCHAR(20) NOT NULL DEFAULT 'reasoning'",
            "VARCHAR(30) NOT NULL DEFAULT 'paragraph'",
            "VARCHAR(50)",
            "VARCHAR(255)",
            "VARCHAR(20) DEFAULT 'deny'",
            "VARCHAR(20) DEFAULT 'ok'",
            "VARCHAR(20) DEFAULT 'polling'",
            "BOOLEAN DEFAULT TRUE",
            "BOOLEAN DEFAULT FALSE",
            "TEXT NOT NULL DEFAULT '[]'",
            "TEXT NOT NULL DEFAULT '{}'",
            "VARCHAR(20) NOT NULL DEFAULT 'na'",
            "VARCHAR(10) NOT NULL DEFAULT 'chunk'",
        }:
            raise ValueError("Invalid database column type")
        await conn.execute(
            text(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column} {col_type}")
        )
