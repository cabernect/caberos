"""Memory capability implementations — recall, store, remember_fact, query_facts, update.

These are called by the syscall mediator with extra_kwargs:
- db: AsyncSession
- agent_id: str
- contact_id: str (for subject-scoped caps, resolved from session — D10)
"""

from typing import Any

from ...memory import notebook, recall, triples


async def memory_recall(args: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
    """Recall conversation snippets matching a query (FTS5 by default)."""
    db = kwargs["db"]
    contact_id = kwargs["contact_id"]
    agent_id = kwargs["agent_id"]
    query = args["query"]

    results = await recall.recall_snippets(db, contact_id, agent_id, query, limit=5)
    return {
        "query": query,
        "results": results,
        "count": len(results),
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
    """Update MEMORY.md (agent-scoped, not contact-scoped)."""
    agent_id = kwargs["agent_id"]
    content = args["content"]

    bytes_written = notebook.write_memory(agent_id, content)
    return {"updated": True, "bytes": bytes_written}


async def search_history(args: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
    """Search raw message history via FTS5 (episodic — exact recall).

    This is the safety net for when MEMORY.md, KG, and session summaries
    don't have the specific detail the agent needs (error messages, config
    values, exact quotes).
    """
    from ...memory.episodic import search_history as _search

    db = kwargs["db"]
    agent_id = kwargs["agent_id"]
    query = args["query"]
    limit = args.get("limit", 5)

    results = await _search(db, agent_id, query, limit=limit)
    return {
        "query": query,
        "results": results,
        "count": len(results),
    }
