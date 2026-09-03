"""SQLite backend — the default (local-first, zero config, D5).

Uses aiosqlite as the async driver. Enables WAL mode + busy timeout for
concurrent read/write support. FTS5 for semantic recall.
"""

import re
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
        await self._migrate_legacy_documents(conn)

        from ..models import (  # noqa: F401
            agent,
            approval,
            audit,
            capability,
            contact,
            document,
            elicitation,
            mcp,
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

    async def _migrate_legacy_documents(self, conn: Any) -> None:
        """Migrate the pre-global Vault schema without discarding indexed data."""
        result = await conn.execute(text("PRAGMA table_info(documents)"))
        columns = {row[1] for row in result.fetchall()}
        if not columns:
            return
        if "source_path" in columns:
            if "agent_id" not in columns:
                await self.add_column(conn, "documents", "agent_id", "VARCHAR(36)")
            await self._repair_document_chunk_foreign_key(conn)
            return
        if not {"agent_id", "workspace_path"} <= columns:
            return

        from ..models.document import Document

        await conn.execute(text("ALTER TABLE documents RENAME TO documents_legacy"))
        await conn.run_sync(Document.__table__.create)
        await conn.execute(
            text(
                "INSERT INTO documents "
                "(id, source_path, storage_path, display_name, mime_type, content_hash, "
                "size_bytes, status, error, indexed_at, structure_json, created_at, updated_at) "
                "SELECT id, agent_id || '/' || workspace_path, workspace_path, display_name, "
                "mime_type, content_hash, size_bytes, status, error, indexed_at, '{}', created_at, "
                "updated_at FROM documents_legacy"
            )
        )
        await conn.execute(text("DROP TABLE documents_legacy"))
        await self._repair_document_chunk_foreign_key(conn)

    async def _repair_document_chunk_foreign_key(self, conn: Any) -> None:
        """Restore chunk foreign keys after SQLite rewrites them during table renames."""
        result = await conn.execute(text("PRAGMA foreign_key_list(document_chunks)"))
        foreign_keys = result.fetchall()
        if not any(row[2] == "documents_legacy" for row in foreign_keys):
            return

        from ..models.document import DocumentChunk

        await conn.execute(text("ALTER TABLE document_chunks RENAME TO document_chunks_legacy"))
        await conn.run_sync(DocumentChunk.__table__.create)
        await conn.execute(
            text(
                "INSERT INTO document_chunks "
                "(id, document_id, seq, text, heading_path, page_number, token_count) "
                "SELECT id, document_id, seq, text, heading_path, page_number, token_count "
                "FROM document_chunks_legacy"
            )
        )
        await conn.execute(text("DROP TABLE document_chunks_legacy"))

    async def _apply_schema_patches(self, conn: Any) -> None:
        """Add columns introduced after the initial schema (idempotent)."""
        patches = [
            ("messages", "attachments", "TEXT"),
            ("providers", "custom_models", "TEXT NOT NULL DEFAULT '[]'"),
            ("messages", "subagent_id", "VARCHAR(36)"),
            ("run_sources", "message_id", "VARCHAR(36)"),
            ("memory_entries", "run_id", "VARCHAR(36)"),
            ("sessions", "summary", "TEXT"),
            ("sessions", "closed", "BOOLEAN DEFAULT 0"),
            ("sessions", "conversation_summary", "TEXT"),
            ("mcp_servers", "require_approval", "BOOLEAN DEFAULT 1"),
            ("mcp_servers", "oauth_config", "TEXT"),
            ("channel_configs", "mode", "VARCHAR(20) DEFAULT 'polling'"),
            ("sessions", "channel", "VARCHAR(50)"),
            ("sessions", "external_user_id", "VARCHAR(255)"),
            ("channel_configs", "approval_policy", "VARCHAR(20) DEFAULT 'deny'"),
            ("documents", "structure_json", "TEXT NOT NULL DEFAULT '{}'"),
            ("document_chunks", "source_location", "TEXT"),
            ("document_chunks", "block_type", "VARCHAR(30) NOT NULL DEFAULT 'paragraph'"),
            ("runs", "context_tokens", "INTEGER DEFAULT 0"),
            ("runs", "max_context_tokens", "INTEGER DEFAULT 0"),
            ("runs", "compacted", "BOOLEAN DEFAULT 0"),
            ("runs", "context_breakdown", "TEXT NOT NULL DEFAULT '{}'"),
            ("runs", "loaded_capabilities", "TEXT NOT NULL DEFAULT '[]'"),
        ]
        for table, column, col_type in patches:
            if not await self.column_exists(conn, table, column):
                await self.add_column(conn, table, column, col_type)

        # Migrate existing channels to auto_approve to preserve current behavior.
        # New channels default to deny (set by the model default).
        await conn.execute(
            text(
                "UPDATE channel_configs SET approval_policy = 'auto_approve' "
                "WHERE approval_policy = 'deny' OR approval_policy IS NULL"
            )
        )

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

        # 3. Document chunks FTS (shared local Knowledge Vault)
        result = await conn.execute(
            text("SELECT name FROM sqlite_master WHERE type='table' AND name='document_chunks_fts'")
        )
        fts_exists = result.fetchone() is not None
        if fts_exists:
            result = await conn.execute(text("PRAGMA table_info(document_chunks_fts)"))
            fts_columns = {row[1] for row in result.fetchall()}
            if "workspace_path" in fts_columns or "agent_id" not in fts_columns:
                if "workspace_path" in fts_columns:
                    legacy_rows = (
                        await conn.execute(
                            text(
                                "SELECT text, chunk_id, document_id, agent_id, workspace_path, "
                                "heading_path, page_number, sheet_name, source_location "
                                "FROM document_chunks_fts"
                            )
                        )
                    ).fetchall()
                else:
                    current_rows = (
                        await conn.execute(
                            text(
                                "SELECT text, chunk_id, document_id, source_path, storage_path, "
                                "heading_path, page_number, sheet_name, source_location "
                                "FROM document_chunks_fts"
                            )
                        )
                    ).fetchall()
                    legacy_rows = [
                        (r[0], r[1], r[2], None, r[3], r[5], r[6], r[7], r[8]) for r in current_rows
                    ]
                await conn.execute(text("DROP TABLE document_chunks_fts"))
                await conn.execute(
                    text(
                        "CREATE VIRTUAL TABLE document_chunks_fts USING fts5("
                        "text, chunk_id UNINDEXED, document_id UNINDEXED, agent_id UNINDEXED, "
                        "source_path UNINDEXED, storage_path UNINDEXED, heading_path UNINDEXED, page_number UNINDEXED, "
                        "sheet_name UNINDEXED, source_location UNINDEXED, tokenize='porter unicode61')"
                    )
                )
                fts_exists = True
                for row in legacy_rows:
                    await conn.execute(
                        text(
                            "INSERT INTO document_chunks_fts "
                            "(text, chunk_id, document_id, agent_id, source_path, storage_path, heading_path, "
                            "page_number, sheet_name, source_location) "
                            "VALUES (:content, :chunk_id, :document_id, :agent_id, :source_path, "
                            ":storage_path, :heading_path, :page_number, :sheet_name, "
                            ":source_location)"
                        ),
                        {
                            "content": row[0],
                            "chunk_id": row[1],
                            "document_id": row[2],
                            "agent_id": row[3],
                            "source_path": f"{row[3]}/{row[4]}",
                            "storage_path": row[4],
                            "heading_path": row[5],
                            "page_number": row[6],
                            "sheet_name": row[7],
                            "source_location": row[8],
                        },
                    )
        if not fts_exists:
            await conn.execute(
                text(
                    "CREATE VIRTUAL TABLE document_chunks_fts USING fts5("
                    "text, chunk_id UNINDEXED, document_id UNINDEXED, agent_id UNINDEXED, "
                    "source_path UNINDEXED, storage_path UNINDEXED, heading_path UNINDEXED, page_number UNINDEXED, "
                    "sheet_name UNINDEXED, source_location UNINDEXED, tokenize='porter unicode61')"
                )
            )

        # 4. Session summaries FTS (episodic — topical recall at run start)
        result = await conn.execute(
            text(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='session_summaries_fts'"
            )
        )
        if result.fetchone() is None:
            await conn.execute(
                text(
                    "CREATE VIRTUAL TABLE session_summaries_fts USING fts5("
                    "summary, session_id UNINDEXED, agent_id UNINDEXED, "
                    "contact_id UNINDEXED, tokenize='porter unicode61')"
                )
            )

    @staticmethod
    def _identifier(value: str) -> str:
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", value):
            raise ValueError("Invalid database identifier")
        return value

    async def column_exists(self, conn: Any, table: str, column: str) -> bool:
        table = self._identifier(table)
        column = self._identifier(column)
        result = await conn.execute(text(f"PRAGMA table_info({table})"))
        existing_cols = {row[1] for row in result.fetchall()}
        return column in existing_cols

    async def add_column(self, conn: Any, table: str, column: str, col_type: str) -> None:
        table = self._identifier(table)
        column = self._identifier(column)
        if col_type not in {
            "TEXT",
            "INTEGER DEFAULT 0",
            "VARCHAR(36)",
            "VARCHAR(30) NOT NULL DEFAULT 'paragraph'",
            "VARCHAR(50)",
            "VARCHAR(255)",
            "VARCHAR(20) DEFAULT 'polling'",
            "BOOLEAN DEFAULT 0",
            "BOOLEAN DEFAULT 1",
            "VARCHAR(20) DEFAULT 'deny'",
            "TEXT NOT NULL DEFAULT '[]'",
            "TEXT NOT NULL DEFAULT '{}'",
        }:
            raise ValueError("Invalid database column type")
        await conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}"))
