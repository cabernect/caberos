"""Semantic recall — FTS5 (SQLite) or tsvector (Postgres) or embeddings (D34).

The recall backend is selected based on the active database backend.
- SQLite: FTS5 virtual table (memory_fts)
- Postgres: tsvector column (search_vector) + GIN index on memory_entries
- Embeddings: future — will use LiteLLM embeddings when configured

Both FTS5 and Postgres FTS are keyword-based, $0 cost. The query interface
is the same — only the SQL differs.
"""

import hashlib
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..fts import fts5_match_query
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
    source_refs: list[str] | None = None,
) -> str:
    """Store a conversation snippet for later recall. Returns the entry id.

    With run_id, the entry is working scratch retained until session-close
    learning completes cleanly. Durable entries use run_id=None.
    """
    import json

    entry = MemoryEntry(
        contact_id=contact_id,
        agent_id=agent_id,
        key=key,
        value=value,
        tags=json.dumps(tags or []),
        run_id=run_id,
        source_refs=json.dumps(source_refs or []),
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
    # Sanitize to quoted terms — raw input can contain FTS5 syntax
    # (colons, parens, *) that produced "no such column" errors.
    safe_query = fts5_match_query(query, operator="OR")
    if safe_query is None:
        return []
    result = await db.execute(
        text(
            "SELECT m.id, m.key, m.value, m.tags "
            "FROM memory_fts f "
            "JOIN memory_entries m ON m.id = f.entry_id "
            "WHERE f.contact_id = :cid AND f.agent_id = :aid "
            "AND m.revoked_at IS NULL "
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
            "AND revoked_at IS NULL "
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


async def clear_run_entries(
    db: AsyncSession,
    run_id: str,
    entry_ids: list[str] | None = None,
) -> int:
    """Delete working memory entries scoped to a run.

    Session-close learning calls this after durable retention succeeds.
    Also removes the FTS5 index entries. `entry_ids` narrows the delete
    to a pre-snapshotted set so entries written mid-flight stay put.
    """
    from sqlalchemy import delete, select

    if entry_ids is None:
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
    result = await db.execute(
        delete(MemoryEntry).where(
            MemoryEntry.run_id == run_id,
            MemoryEntry.id.in_(entry_ids),
        )
    )
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


async def recall_core_archive(
    db: AsyncSession,
    agent_id: str,
    query: str,
    limit: int = 5,
    session_id: str | None = None,
) -> list[dict[str, Any]]:
    """Lexical archive search over past core revisions.

    Evidence, not another engine: newest 50 revisions for this agent, split
    into curated paragraphs, casefold token-substring match, dedup exact
    text. Managed identity never participates; the pinned revision's
    paragraphs are excluded — live core is already in context.
    """

    from sqlalchemy import select as _select

    from ..models.core import CoreRevision
    from ..models.session import Session
    from .core import split_core

    pinned_id: str | None = None
    if session_id:
        sess = await db.get(Session, session_id)
        pinned_id = getattr(sess, "core_revision_id", None) if sess else None

    tokens = [t.casefold() for t in query.split() if t.strip()]
    if not tokens:
        return []

    # Stream candidates newest-first until the lexical limit hits — old
    # demoted knowledge stays reachable instead of being cut by .limit(50).
    rows = await db.stream_scalars(
        _select(CoreRevision)
        .where(CoreRevision.agent_id == agent_id)
        .order_by(CoreRevision.created_at.desc(), CoreRevision.id)
        .execution_options(yield_per=50)
    )

    results: list[dict[str, Any]] = []
    # Seed the dedup set with the pinned core's own paragraphs — archive
    # hits already in context must not echo back under another revision id.
    seen: set[str] = set()
    pinned_row = await db.get(CoreRevision, pinned_id) if pinned_id else None
    if (
        pinned_row is not None
        and pinned_row.agent_id == agent_id
        and pinned_row.published
        and hashlib.sha256(pinned_row.content.encode()).hexdigest() == pinned_row.content_hash
    ):
        try:
            _s, _i, pinned_curated = split_core(pinned_row.content)
        except Exception:
            pinned_curated = pinned_row.curated_content
        for para in pinned_curated.split("\n\n"):
            t = para.strip()
            if t:
                seen.add(t)

    async for rev in rows:
        if rev.id == pinned_id:
            continue
        if hashlib.sha256(rev.content.encode()).hexdigest() != rev.content_hash:
            continue
        published = bool(rev.published)
        try:
            _sha, _idt, curated = split_core(rev.content)
            if _sha is None:
                curated = rev.curated_content
        except Exception:
            continue
        # Paragraphs = double-newline blocks.
        for para in curated.split("\n\n"):
            para = para.strip()
            if not para or para in seen:
                continue
            low = para.casefold()
            if not any(t in low for t in tokens):
                continue
            seen.add(para)
            results.append(
                {
                    "revision_id": rev.id,
                    "source": "core_archive",
                    "label": ("historical core" if published else "unpublished core proposal"),
                    "published": published,
                    "content": para,
                    "created_at": str(getattr(rev, "created_at", "")),
                }
            )
            if len(results) >= limit:
                return results
    return results
