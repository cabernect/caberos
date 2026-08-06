"""Knowledge graph — structured facts as triples (D34).

Table: memory_triples (subject, predicate, object, contact_id, agent_id)
Subject-scoped: contact_id resolved from session, never model-supplied (D10).
"""

from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.memory import MemoryTriple


async def remember_fact(
    db: AsyncSession,
    contact_id: str,
    agent_id: str,
    subject: str,
    predicate: str,
    object: str,
    source_run_id: str | None = None,
    db_lock: Any = None,
) -> dict[str, Any]:
    """Store a fact as a triple. Returns the created triple's id."""
    triple = MemoryTriple(
        contact_id=contact_id,
        agent_id=agent_id,
        subject=subject,
        predicate=predicate,
        object=object,
        source_run_id=source_run_id,
    )

    async def _do_store():
        db.add(triple)
        await db.flush()

    if db_lock:
        async with db_lock:
            await _do_store()
    else:
        await _do_store()
    return {
        "id": triple.id,
        "subject": subject,
        "predicate": predicate,
        "object": object,
    }


async def query_facts(
    db: AsyncSession,
    contact_id: str,
    agent_id: str,
    subject: str | None = None,
    predicate: str | None = None,
    object: str | None = None,
) -> list[dict[str, Any]]:
    """Query facts by any combination of subject/predicate/object.
    All filters are exact match (LIKE for partial). Returns matching triples.
    """
    stmt = select(MemoryTriple).where(
        MemoryTriple.contact_id == contact_id,
        MemoryTriple.agent_id == agent_id,
    )
    if subject:
        stmt = stmt.where(MemoryTriple.subject == subject)
    if predicate:
        stmt = stmt.where(MemoryTriple.predicate == predicate)
    if object:
        stmt = stmt.where(MemoryTriple.object == object)
    stmt = stmt.order_by(MemoryTriple.created_at.desc()).limit(50)
    result = await db.execute(stmt)
    triples = result.scalars().all()
    return [
        {
            "id": t.id,
            "subject": t.subject,
            "predicate": t.predicate,
            "object": t.object,
        }
        for t in triples
    ]


async def clear_triples(db: AsyncSession, agent_id: str, contact_id: str | None = None) -> int:
    """Clear triples for an agent, optionally scoped to a contact. Returns count deleted."""
    stmt = delete(MemoryTriple).where(MemoryTriple.agent_id == agent_id)
    if contact_id:
        stmt = stmt.where(MemoryTriple.contact_id == contact_id)
    result = await db.execute(stmt)
    await db.flush()
    return result.rowcount or 0


async def list_triples(db: AsyncSession, agent_id: str) -> list[dict[str, Any]]:
    """List all triples for an agent (all contacts). For the dashboard."""
    stmt = (
        select(MemoryTriple)
        .where(MemoryTriple.agent_id == agent_id)
        .order_by(MemoryTriple.created_at.desc())
        .limit(200)
    )
    result = await db.execute(stmt)
    triples = result.scalars().all()
    return [
        {
            "id": t.id,
            "contact_id": t.contact_id,
            "subject": t.subject,
            "predicate": t.predicate,
            "object": t.object,
            "created_at": t.created_at.isoformat() if t.created_at else None,
        }
        for t in triples
    ]
