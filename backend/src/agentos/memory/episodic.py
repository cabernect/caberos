"""Episodic memory — session summaries + raw message FTS5 (D34).

Two FTS5 indexes, two query intents:
  - messages_fts → exact recall ("what was said") → search_history tool
  - session_summaries_fts → topical recall ("what we did") → auto-injected at run start

Session close generates a 3-5 sentence summary and extracts KG triples.
Triggered by: lazy at run start, periodic sweeper, or explicit close.
Idempotency guard: session.closed = True.
"""

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ..config_schema import AgentConfig
from ..models.session import Session


async def index_message(
    db: AsyncSession,
    message_id: str,
    run_id: str,
    session_id: str,
    agent_id: str,
    content: str,
) -> None:
    """Index a message in the messages FTS5 table (episodic — exact recall)."""
    try:
        await db.execute(
            text(
                "INSERT INTO messages_fts (message_id, run_id, session_id, agent_id, content) "
                "VALUES (:mid, :rid, :sid, :aid, :content)"
            ),
            {
                "mid": message_id,
                "rid": run_id,
                "sid": session_id,
                "aid": agent_id,
                "content": content,
            },
        )
        await db.flush()
    except Exception:
        pass  # FTS not ready, or duplicate — non-critical


async def search_history(
    db: AsyncSession,
    agent_id: str,
    query: str,
    limit: int = 5,
) -> list[dict[str, Any]]:
    """Search raw messages via FTS5 (exact recall — episodic safety net).

    Called on-demand by the agent via the search_history tool.
    """
    safe_query = query.replace('"', '""')
    result = await db.execute(
        text(
            "SELECT f.message_id, f.run_id, f.session_id, f.content "
            "FROM messages_fts f "
            "WHERE f.agent_id = :aid "
            "AND messages_fts MATCH :q "
            "ORDER BY rank LIMIT :limit"
        ),
        {"aid": agent_id, "q": safe_query, "limit": limit},
    )
    rows = result.fetchall()
    return [
        {
            "message_id": row[0],
            "run_id": row[1],
            "session_id": row[2],
            "content": row[3],
        }
        for row in rows
    ]


async def search_session_summaries(
    db: AsyncSession,
    agent_id: str,
    contact_id: str,
    query: str,
    limit: int = 5,
) -> list[dict[str, Any]]:
    """Search session summaries via FTS5 (topical recall — auto-injected at run start).

    Returns matching summaries for injection into the system prompt.
    """
    safe_query = query.replace('"', '""')
    result = await db.execute(
        text(
            "SELECT f.session_id, f.summary "
            "FROM session_summaries_fts f "
            "WHERE f.agent_id = :aid AND f.contact_id = :cid "
            "AND session_summaries_fts MATCH :q "
            "ORDER BY rank LIMIT :limit"
        ),
        {"aid": agent_id, "cid": contact_id, "q": safe_query, "limit": limit},
    )
    rows = result.fetchall()
    return [
        {
            "session_id": row[0],
            "summary": row[1],
        }
        for row in rows
    ]


async def close_session(
    db: AsyncSession,
    agent_config: AgentConfig,
    session: Session,
    contact_id: str,
) -> None:
    """Close a session: generate summary + extract KG triples.

    Idempotent: if session.closed is already True, skip.
    Two LLM calls:
      1. Session summary (3-5 sentences) → sessions.summary + FTS5
      2. KG triples (batch, with existing for dedup) → memory_triples
    """
    if session.closed:
        return

    # Gather all user + assistant messages for this session
    from ..models.run import Message, Run

    result = await db.execute(
        select(Message)
        .join(Run, Run.id == Message.run_id)
        .where(Run.session_id == session.id)
        .where(Message.role.in_(["user", "assistant"]))
        .order_by(Message.created_at)
    )
    messages = result.scalars().all()

    if not messages:
        # No messages — just mark closed
        session.closed = True
        session.status = "closed"
        await db.flush()
        return

    # Build conversation excerpt for the LLM
    convo = []
    for msg in messages:
        role = "User" if msg.role == "user" else "Assistant"
        convo.append(f"{role}: {msg.content[:500]}")
        if len(convo) >= 20:
            break

    # --- LLM Call 1: Session summary ---
    await _generate_session_summary(db, agent_config, session, convo)

    # --- LLM Call 2: KG triple extraction ---
    await _extract_kg_triples(db, agent_config, session, contact_id, convo)

    # Mark closed
    session.closed = True
    session.status = "closed"
    await db.flush()


async def _generate_session_summary(
    db: AsyncSession,
    agent_config: AgentConfig,
    session: Session,
    convo: list[str],
) -> None:
    """Generate a 3-5 sentence summary of the session and index it in FTS5."""
    try:
        from ..providers import ProviderRegistry

        prompt = (
            "Summarize this conversation in 3-5 sentences. Capture:\n"
            "- What the user asked for\n"
            "- What the agent did (tools used, files touched)\n"
            "- The outcome or result\n\n"
            "Output ONLY the summary, no preamble.\n\n" + "\n".join(convo)
        )

        adapter = await ProviderRegistry(db).for_model(agent_config.model.provider_id)
        response = await adapter.complete(
            agent_model=agent_config.model,
            messages=[{"role": "user", "content": prompt}],
            tools=None,
        )

        summary = response.content.strip()
        if not summary:
            return

        # Store summary on the session
        session.summary = summary

        # Index in session_summaries_fts
        await db.execute(
            text(
                "INSERT INTO session_summaries_fts (session_id, agent_id, contact_id, summary) "
                "VALUES (:sid, :aid, :cid, :summary)"
            ),
            {
                "sid": session.id,
                "aid": session.agent_id,
                "cid": session.contact_id,
                "summary": summary,
            },
        )
        await db.flush()
    except Exception:
        pass


async def _extract_kg_triples(
    db: AsyncSession,
    agent_config: AgentConfig,
    session: Session,
    contact_id: str,
    convo: list[str],
) -> None:
    """Extract KG triples from the conversation, with dedup against existing triples."""
    try:
        from ..providers import ProviderRegistry
        from .triples import query_facts, remember_fact

        # Get existing triples for dedup
        existing = await query_facts(db, contact_id, session.agent_id)
        existing_lines = [f"- ({t['subject']}, {t['predicate']}, {t['object']})" for t in existing]

        prompt = (
            "Extract structured facts from this conversation as (entity, predicate, object) triples.\n\n"
            "Rules:\n"
            "- Extract ONLY durable, queryable facts (not one-off task results)\n"
            "- Use canonical entity names (e.g. 'user' not 'the user' or 'they')\n"
            "- Do NOT duplicate facts that are already in the existing triples\n"
            "- If no new facts, output exactly: NO_NEW_FACTS\n\n"
        )
        if existing_lines:
            prompt += (
                "## Existing triples (don't duplicate)\n\n" + "\n".join(existing_lines) + "\n\n"
            )
        prompt += "## Conversation\n\n" + "\n".join(convo) + "\n\n"
        prompt += (
            "Output format (one per line):\n"
            "entity | predicate | object\n\n"
            "Examples:\n"
            "user | prefers | 24-hour time format\n"
            "user | works_with | PDF timesheets\n"
            "project | uses | pdftotext\n"
        )

        adapter = await ProviderRegistry(db).for_model(agent_config.model.provider_id)
        response = await adapter.complete(
            agent_model=agent_config.model,
            messages=[{"role": "user", "content": prompt}],
            tools=None,
        )

        result_text = response.content.strip()
        if not result_text or result_text == "NO_NEW_FACTS":
            return

        # Parse and upsert triples
        for line in result_text.split("\n"):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = [p.strip() for p in line.split("|")]
            if len(parts) != 3:
                continue
            subject, predicate, obj = parts
            if not subject or not predicate or not obj:
                continue

            await remember_fact(
                db,
                contact_id=contact_id,
                agent_id=session.agent_id,
                subject=subject,
                predicate=predicate,
                object=obj,
                source_run_id=None,
            )
    except Exception:
        pass


async def find_idle_sessions(
    db: AsyncSession,
    idle_minutes: int = 30,
) -> list[Session]:
    """Find sessions that are idle beyond the timeout and not yet closed."""
    cutoff = datetime.now(UTC).replace(tzinfo=None)  # SQLite stores naive UTC
    result = await db.execute(
        select(Session).where(
            Session.closed == False,  # noqa: E712
            Session.last_activity_at < cutoff,
        )
    )
    sessions = result.scalars().all()
    # Filter by idle timeout (per-session configurable)
    idle_sessions = []
    for s in sessions:
        last = s.last_activity_at
        if last.tzinfo is None:
            last = last.replace(tzinfo=UTC)
        age = (datetime.now(UTC) - last).total_seconds() / 60
        if age >= (s.idle_timeout_min or idle_minutes):
            idle_sessions.append(s)
    return idle_sessions
