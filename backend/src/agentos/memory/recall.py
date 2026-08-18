"""Semantic recall — FTS5 (SQLite) or tsvector (Postgres) or embeddings (D34).

The recall backend is selected based on the active database backend.
- SQLite: FTS5 virtual table (memory_fts)
- Postgres: tsvector column (search_vector) + GIN index on memory_entries
- Embeddings: future — will use LiteLLM embeddings when configured

Both FTS5 and Postgres FTS are keyword-based, $0 cost. The query interface
is the same — only the SQL differs.
"""

from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..models.memory import MemoryEntry


def _is_postgres() -> bool:
    """Check if the active backend is Postgres."""
    return settings.db_url.startswith("postgres")


async def store_snippet(
    db: AsyncSession,
    contact_id: str,
    agent_id: str,
    key: str,
    value: str,
    tags: list[str] | None = None,
    run_id: str | None = None,
    db_lock: Any = None,
) -> str:
    """Store a conversation snippet for later recall. Returns the entry id.

    If run_id is provided, the entry is run-scoped (working memory) and will
    be deleted at run end unless promoted to MEMORY.md.
    """
    import json

    entry = MemoryEntry(
        contact_id=contact_id,
        agent_id=agent_id,
        key=key,
        value=value,
        tags=json.dumps(tags or []),
        run_id=run_id,
    )

    async def _do_store():
        db.add(entry)
        await db.flush()

        # Index in FTS5 (SQLite only — Postgres uses generated tsvector column)
        if not _is_postgres():
            await db.execute(
                text(
                    "INSERT INTO memory_fts (entry_id, contact_id, agent_id, content) "
                    "VALUES (:eid, :cid, :aid, :content)"
                ),
                {"eid": entry.id, "cid": contact_id, "aid": agent_id, "content": f"{key} {value}"},
            )
            await db.flush()

    if db_lock:
        async with db_lock:
            await _do_store()
    else:
        await _do_store()
    return entry.id


async def recall_snippets(
    db: AsyncSession,
    contact_id: str,
    agent_id: str,
    query: str,
    limit: int = 5,
) -> list[dict[str, Any]]:
    """Recall snippets matching the query. Subject-scoped (D10)."""
    if _is_postgres():
        return await _recall_postgres(db, contact_id, agent_id, query, limit)
    return await _recall_fts5(db, contact_id, agent_id, query, limit)


async def _recall_fts5(
    db: AsyncSession,
    contact_id: str,
    agent_id: str,
    query: str,
    limit: int,
) -> list[dict[str, Any]]:
    """FTS5 recall (SQLite)."""
    safe_query = query.replace('"', '""')
    result = await db.execute(
        text(
            "SELECT m.id, m.key, m.value, m.tags "
            "FROM memory_fts f "
            "JOIN memory_entries m ON m.id = f.entry_id "
            "WHERE f.contact_id = :cid AND f.agent_id = :aid "
            "AND memory_fts MATCH :q "
            "ORDER BY rank LIMIT :limit"
        ),
        {"cid": contact_id, "aid": agent_id, "q": safe_query, "limit": limit},
    )
    rows = result.fetchall()
    import json

    return [
        {
            "id": row[0],
            "key": row[1],
            "value": row[2],
            "tags": json.loads(row[3]) if row[3] else [],
        }
        for row in rows
    ]


async def _recall_postgres(
    db: AsyncSession,
    contact_id: str,
    agent_id: str,
    query: str,
    limit: int,
) -> list[dict[str, Any]]:
    """tsvector recall (Postgres). Uses plainto_tsquery for safe user input."""
    result = await db.execute(
        text(
            "SELECT id, key, value, tags "
            "FROM memory_entries "
            "WHERE contact_id = :cid AND agent_id = :aid "
            "AND search_vector @@ plainto_tsquery('english', :q) "
            "ORDER BY ts_rank(search_vector, plainto_tsquery('english', :q)) DESC "
            "LIMIT :limit"
        ),
        {"cid": contact_id, "aid": agent_id, "q": query, "limit": limit},
    )
    rows = result.fetchall()
    import json

    return [
        {
            "id": row[0],
            "key": row[1],
            "value": row[2],
            "tags": json.loads(row[3]) if row[3] else [],
        }
        for row in rows
    ]


async def clear_entries(db: AsyncSession, agent_id: str, contact_id: str | None = None) -> int:
    """Clear memory entries for an agent, optionally scoped to a contact."""
    from sqlalchemy import delete

    stmt = delete(MemoryEntry).where(MemoryEntry.agent_id == agent_id)
    if contact_id:
        stmt = stmt.where(MemoryEntry.contact_id == contact_id)
    result = await db.execute(stmt)
    await db.flush()
    return result.rowcount or 0


async def clear_run_entries(db: AsyncSession, run_id: str) -> int:
    """Delete all working memory entries scoped to a run.

    Called at run end after MEMORY.md consolidation. Entries that were
    promoted are already in MEMORY.md — everything else is transient.
    Also removes their FTS5 index entries.
    """
    from sqlalchemy import delete, select

    # Get entry IDs for FTS cleanup
    result = await db.execute(select(MemoryEntry.id).where(MemoryEntry.run_id == run_id))
    entry_ids = [row[0] for row in result.fetchall()]

    if not entry_ids:
        return 0

    # Delete FTS5 index entries (SQLite only)
    if not _is_postgres():
        for eid in entry_ids:
            await db.execute(
                text("DELETE FROM memory_fts WHERE entry_id = :eid"),
                {"eid": eid},
            )

    # Delete the entries themselves
    result = await db.execute(delete(MemoryEntry).where(MemoryEntry.run_id == run_id))
    await db.flush()
    return result.rowcount or 0


async def get_run_entries(db: AsyncSession, run_id: str) -> list[dict[str, Any]]:
    """Get all working memory entries for a run (for consolidation LLM)."""
    from sqlalchemy import select

    result = await db.execute(
        select(MemoryEntry).where(MemoryEntry.run_id == run_id).order_by(MemoryEntry.created_at)
    )
    entries = result.scalars().all()
    import json

    return [
        {
            "id": e.id,
            "key": e.key,
            "value": e.value,
            "tags": json.loads(e.tags) if e.tags else [],
        }
        for e in entries
    ]
