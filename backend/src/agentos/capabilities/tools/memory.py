"""Memory capability implementations — recall, store, remember_fact, query_facts, update.

These are called by the syscall mediator with extra_kwargs:
- db: AsyncSession
- agent_id: str
- contact_id: str (for subject-scoped caps, resolved from session — D10)
"""

from typing import Any

from ...memory import recall, triples


async def memory_recall(args: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
    """Recall conversation snippets + archived core paragraphs.

    Contact snippets stay subject-scoped; the core archive is agent-global
    (owner audience) and returns bounded, labeled curated paragraphs from
    older revisions — managed identity and the currently pinned paragraphs
    are excluded so recall never echoes live core back."""
    db = kwargs["db"]
    contact_id = kwargs["contact_id"]
    agent_id = kwargs["agent_id"]
    query = args["query"]
    limit = max(1, min(int(args.get("limit", 5)), 50))

    results = await recall.recall_snippets(db, contact_id, agent_id, query, limit=limit)
    archive = await recall.recall_core_archive(
        db,
        agent_id=agent_id,
        query=query,
        limit=limit,
        session_id=kwargs.get("session_id"),
    )
    return {
        "query": query,
        "results": (results + archive)[:limit],
        "count": min(len(results) + len(archive), limit),
    }


async def memory_store(args: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
    """Store a conversation snippet for later recall (working memory, run-scoped)."""
    db = kwargs["db"]
    contact_id = kwargs["contact_id"]
    agent_id = kwargs["agent_id"]
    run_id = kwargs.get("run_id")
    db_lock = kwargs.get("db_lock")
    key = args.get("key", "snippet")
    value = args["text"]
    tags = args.get("tags", [])

    entry_id = await recall.store_snippet(
        db, contact_id, agent_id, key, value, tags, run_id=run_id, db_lock=db_lock
    )
    return {"stored": True, "id": entry_id}


async def memory_remember_fact(args: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
    """Store a structured fact as a triple in the knowledge graph."""
    db = kwargs["db"]
    contact_id = kwargs["contact_id"]
    agent_id = kwargs["agent_id"]
    source_run_id = kwargs.get("run_id")
    db_lock = kwargs.get("db_lock")

    result = await triples.remember_fact(
        db,
        contact_id=contact_id,
        agent_id=agent_id,
        subject=args["entity"],
        predicate=args["predicate"],
        object=args["object"],
        source_run_id=source_run_id,
        db_lock=db_lock,
    )
    return {"remembered": True, **result}


async def memory_query_facts(args: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
    """Query the knowledge graph for matching facts."""
    db = kwargs["db"]
    contact_id = kwargs["contact_id"]
    agent_id = kwargs["agent_id"]

    facts = await triples.query_facts(
        db,
        contact_id=contact_id,
        agent_id=agent_id,
        subject=args.get("entity"),
        predicate=args.get("predicate"),
        object=args.get("object"),
    )
    return {"facts": facts, "count": len(facts)}


async def memory_update(args: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
    """Update the curated portion of MEMORY.md (agent-scoped).

    Goes through update_core like every writer: the managed identity comes
    from the DB active config (never from the file), the session-pinned
    curated hash is the default CAS base, and conflicts report the current
    hash instead of silently stomping concurrent work.
    """
    db = kwargs["db"]
    agent_id = kwargs["agent_id"]
    session_id = kwargs.get("session_id")
    content = args["content"]

    import hashlib

    from ...agent_service import get_active_config
    from ...memory.core import CoreConflict, update_core
    from ...models.core import CoreRevision
    from ...models.session import Session

    config = await get_active_config(db, agent_id)
    if config is None:
        config = kwargs.get("agent_config")
    if config is None:
        return {"updated": False, "error": "agent not configured"}

    expected_hash = args.get("expected_hash")
    if expected_hash is None and session_id:
        # Default CAS base = the session-pinned revision's WHOLE-FILE hash,
        # only when the pinned revision validates (published, hash intact).
        session = await db.get(Session, session_id)
        if session is not None and session.agent_id != agent_id:
            return {"updated": False, "error": "Session does not belong to this agent"}
        if session is not None and session.core_revision_id:
            rev = await db.get(CoreRevision, session.core_revision_id)
            if (
                rev is not None
                and rev.agent_id == agent_id
                and rev.published
                and (hashlib.sha256(rev.content.encode("utf-8")).hexdigest() == rev.content_hash)
            ):
                expected_hash = rev.content_hash
            else:
                return {"updated": False, "error": "Session core revision is invalid"}

    try:
        snapshot = await update_core(db, config, content, expected_hash=expected_hash)
        await db.commit()
    except CoreConflict as exc:
        return {
            "updated": False,
            "conflict": str(exc),
            "current_hash": exc.current_hash,
            "current_curated_content": exc.current_curated,
        }
    return {
        "updated": True,
        "revision_id": snapshot.revision_id,
        "token_count": snapshot.token_count,
    }


async def search_history(args: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
    """Search raw message history via FTS5 (episodic — exact recall).

    This is the safety net for when MEMORY.md, KG, and session summaries
    don't have the specific detail the agent needs (error messages, config
    values, exact quotes).
    """
    from ...memory.episodic import search_scoped_history as _search
    from ...memory.history_queries import read_frozen_evidence

    db = kwargs["db"]
    agent_id = kwargs["agent_id"]
    contact_id = kwargs["contact_id"]
    query = args["query"]
    limit = args.get("limit", 5)
    history_scope = kwargs.get("history_scope")
    selectors = ("run_id", "message_id", "offset", "content_offset")
    if history_scope is not None:
        if (
            history_scope["agent_id"] != agent_id
            or history_scope["contact_id"] != contact_id
            or not isinstance(query, str)
        ):
            raise ValueError("History scope mismatch")
        page = await read_frozen_evidence(
            db,
            **history_scope,
            query=query,
            limit=limit,
            **{name: args[name] for name in selectors if name in args},
        )
        return {
            "query": query,
            "results": page["rows"],
            "count": len(page["rows"]),
            "next_offset": page["next_offset"],
        }
    if any(name in args for name in selectors):
        raise ValueError("History paging requires a frozen evidence scope")

    results = await _search(db, agent_id, contact_id, query, limit=limit)
    return {
        "query": query,
        "results": results,
        "count": len(results),
    }
