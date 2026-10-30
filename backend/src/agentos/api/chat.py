"""Dashboard chat channel API routes (D20, D33).

POST   /api/chat/{agent_id}/message              — send a message (starts a run)
GET    /api/chat/{agent_id}/runs/{run_id}/events  — SSE stream of run events (reconnectable)
GET    /api/chat/{agent_id}/runs/{run_id}         — poll run status
POST   /api/chat/{agent_id}/runs/{run_id}/stop    — stop a run
GET    /api/chat/{agent_id}/sessions             — list sessions
POST   /api/chat/{agent_id}/sessions             — create new session
GET    /api/chat/{agent_id}/sessions/{sid}/messages  — session messages
DELETE /api/chat/{agent_id}/sessions/{sid}       — delete session
"""

import asyncio
import json
import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import String, and_, cast, func, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import require_operator
from ..db import get_db
from ..models.agent import Agent
from ..models.contact import Contact
from ..models.operator import Operator
from ..models.run import Message, Run
from ..models.session import Session
from ..models.source import RunSource
from ..models.web_source import WebSource
from ..pipeline import Attachment
from ..run_manager import get_run, get_run_status, start_run, stop_run
from ..services.data_lifecycle import delete_runs

router = APIRouter(prefix="/api/chat", tags=["chat"])


def _iso_utc(dt: datetime | None) -> str:
    """Serialize a datetime to ISO 8601 with UTC marker.
    Handles naive datetimes (assumed UTC from SQLite) and aware datetimes.
    """
    if dt is None:
        return ""
    if dt.tzinfo is None:
        # Naive datetime — SQLite stores UTC, so append Z
        return dt.isoformat() + "Z"
    return dt.isoformat()


class ModelOverride(BaseModel):
    """Optional model override — user can switch models per-message."""

    provider_id: str
    name: str
    supports_vision: bool | None = None
    thinking_enabled: bool | None = None
    thinking_effort: str | None = None  # "low", "medium", "high", "max", etc.


class AttachmentIn(BaseModel):
    """An attachment sent from the frontend for tool-mediated access."""

    type: str  # "image", "url", "file"
    mime_type: str = ""
    data: str  # base64 for uploads, URL for urls, text content for text files
    filename: str = ""


class SendMessageRequest(BaseModel):
    text: str
    is_test: bool = False
    model_override: ModelOverride | None = None
    session_id: str | None = None  # if provided, use this session; else auto-resume
    new_session: bool = False  # if true, force create a new session (ignore auto-resume)
    attachments: list[AttachmentIn] = []  # attachments exposed through existing tools
    skill: str | None = None  # slash command: /skillname → auto-load skill into context


class MessageOut(BaseModel):
    id: str
    role: str
    content: str
    created_at: str


@router.post("/{agent_id}/message")
async def send_message(
    agent_id: str,
    body: SendMessageRequest,
    operator: Operator = Depends(require_operator),
) -> dict:
    """Send a message to an agent. Starts a run and returns {run_id, session_id}.

    The run executes independently. Connect to GET /runs/{run_id}/events
    to stream the events. The run survives disconnects — reconnect anytime.
    """
    # Quick agent existence + model check (short-lived session)
    from ..agent_service import get_active_config
    from ..db import async_session_factory

    async with async_session_factory() as check_db:
        result = await check_db.execute(select(Agent).where(Agent.id == agent_id))
        agent = result.scalar_one_or_none()
        if agent is None:
            raise HTTPException(status_code=404, detail="Agent not found")
        if not agent.enabled:
            raise HTTPException(status_code=400, detail="Agent is disabled")

        # Pre-check: refuse to start if no model is configured (and not a test run).
        # Skip this check if the user provided a model_override — they're
        # explicitly choosing a model for this message.
        if not body.is_test and not body.model_override:
            config = await get_active_config(check_db, agent_id)
            if config and not config.model.is_configured:
                raise HTTPException(
                    status_code=400,
                    detail="No model configured for this agent. "
                    "Add a provider in Settings → Providers, then assign a model.",
                )

    result = await start_run(
        agent_id=agent_id,
        text=body.text,
        user_id=operator.id,
        is_test=body.is_test,
        model_override=(
            {
                "provider_id": body.model_override.provider_id,
                "name": body.model_override.name,
                "thinking_enabled": body.model_override.thinking_enabled,
                "thinking_effort": body.model_override.thinking_effort,
            }
            if body.model_override
            else None
        ),
        session_id=body.session_id,
        new_session=body.new_session,
        attachments=[
            Attachment(
                type=a.type,
                mime_type=a.mime_type,
                data=a.data,
                filename=a.filename,
            )
            for a in body.attachments
        ],
        skill=body.skill,
    )

    return {"run_id": result["run_id"], "session_id": result["session_id"], "status": "started"}


class CompactRequest(BaseModel):
    session_id: str


@router.post("/{agent_id}/compact")
async def compact_session(
    agent_id: str,
    body: CompactRequest,
    operator: Operator = Depends(require_operator),
) -> dict:
    """Manually trigger context compaction on a session.

    Forces compaction regardless of the token threshold. Useful when the user
    wants to proactively compress context before a long task, or when
    auto-compaction is off.
    """
    from ..agent_service import get_active_config
    from ..db import async_session_factory
    from ..harness.compaction import (
        compact_context,
        count_text_tokens,
        count_tool_tokens,
    )
    from ..harness.context import assemble_system_prompt, assemble_tool_schemas
    from ..models.session import Session
    from ..providers import ProviderRegistry

    async with async_session_factory() as db:
        # Load agent config
        config = await get_active_config(db, agent_id)
        if not config:
            raise HTTPException(status_code=404, detail="Agent not found")

        # Load session
        result = await db.execute(
            select(Session).where(Session.id == body.session_id, Session.agent_id == agent_id)
        )
        session = result.scalar_one_or_none()
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")

        # Load the session's uncovered conversation — deterministic order,
        # coverage-aware, no LIMIT cut, no dummy user message.
        from ..harness.conversation import Conversation

        conversation = await Conversation.load(db, session)

        # Get model info — resolved metadata + frozen rate snapshot ride
        # the same capture as execution calls.
        model_str = "gpt-4o"
        api_key = None
        base_url = None
        extra_params: dict = {}
        resolved_model: dict = {}
        accounting = None
        if config.model.is_configured:
            try:
                adapter = await ProviderRegistry(db).for_model(config.model.provider_id)
                info = await adapter.get_model_info(config.model)
                model_str = info["model_str"]
                api_key = info["api_key"]
                base_url = info["base_url"]
                extra_params = info.get("extra_params") or {}
                resolved_model = info.get("resolved_model") or {}
                accounting = info.get("accounting")
            except Exception:
                pass

        from ..providers.catalog_policy import resolve_input_budget

        try:
            input_budget = resolve_input_budget(
                resolved_model,
                model_override=config.model.max_context_tokens,
                run_override=config.limits.max_context_tokens,
                output_tokens=config.model.max_tokens,
            )["tokens"]
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))

        # Reserved = fixed system prompt + initially permitted schemas +
        # resolved assigned skill menu — the same fixed budget the live
        # path counts on its first dispatch.
        from ..capabilities.catalog import CapabilityRunCatalog
        from ..skills.resolution import resolve_effective_skills

        resolved_skills = await resolve_effective_skills(db, agent_id)
        capability_catalog = CapabilityRunCatalog(agent_config=config, db=db)
        tool_schemas = assemble_tool_schemas(
            config, capability_names=capability_catalog.model_capability_names()
        )
        # Reserved accounting uses the session's PINNED core (the fixed
        # managed/curated envelope), never the live notebook plus a
        # duplicated identity. The pin is created if this session predates
        # core support.
        from ..memory.core import CoreConflict, load_or_pin_core

        try:
            pinned_core = await load_or_pin_core(db, config, session)
            await db.commit()
        except CoreConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc))
        system_prompt = assemble_system_prompt(
            config, "", resolved_skills=resolved_skills, core_snapshot=pinned_core
        )
        reserved_tokens = count_text_tokens(system_prompt, model_str) + count_tool_tokens(
            tool_schemas, model_str
        )

        # Run compaction (force=True) against uncovered originals; the
        # summary already renders inside the result exactly once.
        compaction_result = await compact_context(
            messages=list(conversation.messages),
            source_ids=list(conversation.source_ids),
            agent_config=config,
            model_str=model_str,
            previous_summary=session.conversation_summary,
            api_key=api_key,
            base_url=base_url,
            extra_params=extra_params,
            force=True,
            input_budget=input_budget,
            resolved_model=resolved_model,
            accounting=accounting,
            reserved_tokens=reserved_tokens,
            session_id=body.session_id,
            # Manual /compact has no parent run — an honest blank, not a
            # fabricated run_id.
            run_id=None,
        )

        # Persist summary + coverage + version in one conditional write —
        # only after a valid compaction, even when the text is unchanged
        # (newly covered IDs still need storing). A CAS loss is a conflict.
        if compaction_result.compacted:
            _head_ids = {
                sid
                for group in conversation.source_ids[: compaction_result.head_count]
                for sid in (group or set())
            }
            _tail_ids = {
                sid
                for group in conversation.source_ids[
                    len(conversation.source_ids) - compaction_result.tail_count :
                ]
                for sid in (group or set())
            }
            stored = await conversation.store_summary(
                db,
                compaction_result.summary,
                conversation.covered_ids | compaction_result.covered_ids,
                retained_head_ids=_head_ids,
                retained_tail_ids=_tail_ids,
            )
            if not stored:
                raise HTTPException(
                    status_code=409,
                    detail="Conversation was compacted concurrently; retry",
                )

        return {
            "compacted": compaction_result.compacted,
            "original_tokens": compaction_result.original_tokens,
            "compacted_tokens": compaction_result.compacted_tokens,
            "max_context_tokens": input_budget,
            "head_count": compaction_result.head_count,
            "middle_count": compaction_result.middle_count,
            "tail_count": compaction_result.tail_count,
            "summary": compaction_result.summary,
            "error": compaction_result.error,
        }


@router.get("/{agent_id}/runs/{run_id}/events")
async def stream_run_events(
    agent_id: str,
    run_id: str,
    request: Request,
    operator: Operator = Depends(require_operator),
) -> StreamingResponse:
    """SSE stream of run events. Reconnectable — uses Last-Event-ID to resume.

    The run executes independently of this connection. If the client disconnects,
    the run keeps going. Reconnect with Last-Event-ID header to get missed events.
    """
    ctx = get_run(run_id)
    if ctx is None:
        raise HTTPException(status_code=404, detail="Run not found or already completed")

    # Parse Last-Event-ID header for reconnect (client sends the last seq they received)
    last_event_id = request.headers.get("Last-Event-ID", "0")
    try:
        after_seq = int(last_event_id)
    except ValueError:
        after_seq = 0

    async def event_stream() -> Any:
        seq = after_seq
        # First, replay any buffered events the client missed
        for ev_seq, event_type, payload in ctx.events:
            if ev_seq > seq:
                data = json.dumps(payload)
                yield f"id: {ev_seq}\nevent: {event_type}\ndata: {data}\n\n"
                seq = ev_seq

        # If the run is already done, we're done too
        if ctx.task.done() or ctx.status in ("completed", "failed", "stopped"):
            return

        # Stream live events
        while True:
            if await request.is_disconnected():
                break
            if ctx.task.done() and seq >= ctx._seq:
                break

            new_seq = await ctx.wait_for_event(seq, timeout=1.0)
            if new_seq is not None:
                # Yield all events up to new_seq
                for ev_seq, event_type, payload in ctx.events:
                    if ev_seq > seq and ev_seq <= new_seq:
                        data = json.dumps(payload)
                        yield f"id: {ev_seq}\nevent: {event_type}\ndata: {data}\n\n"
                seq = new_seq
            else:
                # No new event — send a keepalive comment so the proxy/browser
                # doesn't close the connection due to inactivity
                yield ": keepalive\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/{agent_id}/runs/{run_id}")
async def get_run_status_endpoint(
    agent_id: str,
    run_id: str,
    operator: Operator = Depends(require_operator),
) -> dict:
    """Poll the status of a run. Works even when detached from SSE."""
    status = await get_run_status(run_id)
    if status is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return status


@router.post("/{agent_id}/runs/{run_id}/stop")
async def stop_run_endpoint(
    agent_id: str,
    run_id: str,
    operator: Operator = Depends(require_operator),
) -> dict:
    """Stop a running run."""
    stopped = await stop_run(run_id)
    if not stopped:
        raise HTTPException(status_code=400, detail="Run not running or already finished")
    return {"status": "stopped"}


@router.get("/{agent_id}/history")
async def get_history(
    agent_id: str,
    operator: Operator = Depends(require_operator),
    db: AsyncSession = Depends(get_db),
    limit: int = 50,
) -> list[dict]:
    """Get conversation history for an agent (messages from all runs)."""
    result = await db.execute(
        select(Message, Run)
        .join(Run, Message.run_id == Run.id)
        .where(Run.trigger != "reflection")
        .where(Run.agent_id == agent_id)
        .order_by(Message.created_at.desc())
        .limit(limit)
    )
    rows = result.all()
    rows.reverse()  # chronological order
    return [
        {
            "id": msg.id,
            "role": msg.role,
            "content": msg.content,
            "created_at": _iso_utc(msg.created_at),
            "run_id": msg.run_id,
            "trigger": run.trigger,
        }
        for msg, run in rows
    ]


# --- Session CRUD ---


class CreateSessionRequest(BaseModel):
    title: str | None = None


@router.get("/{agent_id}/sessions")
async def list_sessions(
    agent_id: str,
    operator: Operator = Depends(require_operator),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """List all sessions for an agent, most recent first."""
    # Get session info + message count
    result = await db.execute(
        select(
            Session,
            func.count(Message.id).label("msg_count"),
        )
        .outerjoin(Run, and_(Run.session_id == Session.id, Run.trigger != "reflection"))
        .outerjoin(Message, Message.run_id == Run.id)
        .where(Session.agent_id == agent_id)
        .group_by(Session.id)
        .order_by(Session.last_activity_at.desc())
    )
    rows = result.all()
    from ..memory.episodic import closing_session_ids

    closing = closing_session_ids()
    sessions = []
    for sess, msg_count in rows:
        active_result = await db.execute(
            select(Run)
            .where(
                Run.session_id == sess.id,
                Run.trigger != "reflection",
                Run.status.in_(("pending", "running", "awaiting_approval")),
            )
            .order_by(Run.started_at.desc())
            .limit(1)
        )
        active_run = active_result.scalar_one_or_none()
        sessions.append(
            {
                "id": sess.id,
                "title": sess.title or "New conversation",
                "status": sess.status,
                "started_at": _iso_utc(sess.started_at),
                "last_activity_at": _iso_utc(sess.last_activity_at),
                "message_count": msg_count,
                "channel": sess.channel,
                "external_user_id": sess.external_user_id,
                "active_run_id": active_run.id if active_run else None,
                "active_run_status": active_run.status if active_run else None,
                "learning": sess.id in closing,
            }
        )
    return sessions


@router.get("/{agent_id}/session-activity/stream")
async def session_activity_stream(
    agent_id: str,
    operator: Operator = Depends(require_operator),
) -> StreamingResponse:
    """Transient session-activity frames for this agent (close-time learning).

    UI state only — nothing persisted, dropped frames are safe because the
    sessions list carries an authoritative `learning` flag on next fetch.
    """
    from .. import session_activity

    queue = session_activity.subscribe()

    async def gen():
        try:
            yield f"data: {json.dumps({'type': 'hello'})}\n\n"
            while True:
                try:
                    payload = await asyncio.wait_for(queue.get(), timeout=25.0)
                except TimeoutError:
                    yield ": keepalive\n\n"
                    continue
                if payload.get("agent_id") != agent_id:
                    continue
                yield f"data: {json.dumps(payload)}\n\n"
        finally:
            session_activity.unsubscribe(queue)

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/{agent_id}/sessions")
async def create_session(
    agent_id: str,
    body: CreateSessionRequest,
    operator: Operator = Depends(require_operator),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Create a new session for an agent."""
    # Verify agent exists
    result = await db.execute(select(Agent).where(Agent.id == agent_id))
    if result.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="Agent not found")

    # Resolve or create the operator's contact
    result = await db.execute(
        select(Contact).where(
            Contact.channel == "dashboard_chat",
            Contact.bot_id == agent_id,
            Contact.external_user_id == operator.id,
        )
    )
    contact = result.scalar_one_or_none()
    if contact is None:
        contact = Contact(
            id=str(uuid.uuid4()),
            channel="dashboard_chat",
            bot_id=agent_id,
            external_user_id=operator.id,
            display_name=operator.id,
        )
        db.add(contact)
        await db.flush()

    session = Session(
        id=str(uuid.uuid4()),
        contact_id=contact.id,
        agent_id=agent_id,
        status="active",
        title=body.title,
    )
    db.add(session)
    await db.commit()
    return {
        "id": session.id,
        "title": session.title or "New conversation",
        "status": session.status,
    }


def _source_response(source: RunSource) -> dict:
    return {
        "id": source.id,
        "source_type": "knowledge",
        "chunk_id": source.chunk_id,
        "document_id": source.document_id,
        "source_path": source.source_path,
        "storage_path": source.storage_path,
        "heading_path": json.loads(source.heading_path) if source.heading_path else [],
        "page_number": source.page_number,
        "sheet_name": source.sheet_name,
        "source_location": source.source_location,
        "excerpt": source.excerpt,
        "rank": source.rank,
    }


def _web_source_response(source: WebSource) -> dict:
    return {
        "id": source.id,
        "source_type": "web",
        "chunk_id": None,
        "document_id": None,
        "source_path": source.url,
        "storage_path": source.url,
        "title": source.title,
        "heading_path": [],
        "page_number": None,
        "sheet_name": None,
        "source_location": None,
        "excerpt": source.excerpt,
        "rank": source.rank,
    }


@router.get("/{agent_id}/sessions/{session_id}/messages")
async def get_session_messages(
    agent_id: str,
    session_id: str,
    operator: Operator = Depends(require_operator),
    db: AsyncSession = Depends(get_db),
    limit: int = 100,
    before_id: str | None = None,
) -> dict:
    """Get the latest ``limit`` messages for a session, chronologically.

    Pass ``before_id`` — the oldest loaded message id — to page upward through
    history; ``has_more`` reports whether older rows remain.
    """
    # DESC + LIMIT grabs the newest window; ASC + LIMIT would pin the list to
    # the session's first `limit` rows — anything past that (i.e. every new
    # reply once the window fills) silently vanished from the chatview.
    # Message.id is the final tiebreaker: seq resets per run and started_at can
    # tie, so without it the ordering has gaps the cursor can't partition.
    # All timestamp comparisons go through CAST-to-text: server_default rows
    # store second precision while ORM-bound datetimes rebind microseconds —
    # comparing typed values lets a cursor row compare less than itself and
    # leak into the next page.
    started_txt = cast(Run.started_at, String)
    created_txt = cast(Message.created_at, String)
    filters = [Run.session_id == session_id, Run.agent_id == agent_id, Run.trigger != "reflection"]
    if before_id is not None:
        cursor = (
            await db.execute(
                select(started_txt, Message.seq, created_txt, Message.id)
                .join(Run, Message.run_id == Run.id)
                .where(Message.id == before_id, *filters)
            )
        ).one_or_none()
        if cursor is None:
            raise HTTPException(404, "cursor message not found")
        filters.append(tuple_(started_txt, Message.seq, created_txt, Message.id) < tuple_(*cursor))
    result = await db.execute(
        select(Message, Run)
        .join(Run, Message.run_id == Run.id)
        .where(*filters)
        .order_by(
            started_txt.desc(),
            Message.seq.desc(),
            created_txt.desc(),
            Message.id.desc(),
        )
        .limit(limit + 1)
    )
    fetched = result.all()
    has_more = len(fetched) > limit
    rows = list(reversed(fetched[:limit]))
    run_ids = {run.id for _, run in rows}
    source_rows = (
        await db.execute(select(RunSource).where(RunSource.run_id.in_(run_ids)))
        if run_ids
        else None
    )
    sources_by_run: dict[str, list[dict]] = {}
    if source_rows is not None:
        for source in source_rows.scalars().all():
            sources_by_run.setdefault(source.run_id, []).append(_source_response(source))
    if run_ids:
        web_source_rows = await db.execute(select(WebSource).where(WebSource.run_id.in_(run_ids)))
        for source in web_source_rows.scalars().all():
            sources_by_run.setdefault(source.run_id, []).append(_web_source_response(source))
    return {
        "messages": [
            {
                "id": msg.id,
                "role": msg.role,
                "content": msg.content,
                "created_at": _iso_utc(msg.created_at),
                "run_id": msg.run_id,
                "run_status": run.status,
                "trigger": run.trigger,
                "is_test": run.is_test,
                "tokens_in": run.tokens_in,
                "tokens_out": run.tokens_out,
                "cost": run.cost,
                "subagent_id": msg.subagent_id,
                "attachments": msg.attachments,
                "citations": sources_by_run.get(msg.run_id, [])
                if msg.role in ("assistant", "heartbeat")
                else [],
            }
            for msg, run in rows
        ],
        "has_more": has_more,
    }


@router.delete("/{agent_id}/sessions/{session_id}")
async def delete_session(
    agent_id: str,
    session_id: str,
    operator: Operator = Depends(require_operator),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Delete a session and all its messages."""
    result = await db.execute(
        select(Session).where(Session.id == session_id, Session.agent_id == agent_id)
    )
    session = result.scalar_one_or_none()
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")

    run_ids_result = await db.execute(select(Run.id).where(Run.session_id == session_id))
    run_ids = [r[0] for r in run_ids_result.all()]
    await delete_runs(db, run_ids)

    await db.delete(session)
    await db.commit()
    return {"deleted": True}
