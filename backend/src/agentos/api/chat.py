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

import json
import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import require_operator
from ..db import get_db
from ..models.agent import Agent
from ..models.approval import ApprovalRequest
from ..models.audit import AuditRecord
from ..models.contact import Contact
from ..models.elicitation import ElicitationRequest
from ..models.operator import Operator
from ..models.run import Message, Run
from ..models.session import Session
from ..pipeline import Attachment
from ..run_manager import get_run, get_run_status, start_run, stop_run

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


class AttachmentIn(BaseModel):
    """A multimodal attachment sent from the frontend."""

    type: str  # "image", "url", "file"
    mime_type: str = ""
    data: str  # base64 for images, URL for urls, text content for files
    filename: str = ""


class SendMessageRequest(BaseModel):
    text: str
    is_test: bool = False
    model_override: ModelOverride | None = None
    session_id: str | None = None  # if provided, use this session; else auto-resume
    new_session: bool = False  # if true, force create a new session (ignore auto-resume)
    attachments: list[AttachmentIn] = []  # multimodal attachments
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
        if result.scalar_one_or_none() is None:
            raise HTTPException(status_code=404, detail="Agent not found")

        # Pre-check: refuse to start if no model is configured (and not a test run).
        # This gives the user an immediate, clear error instead of a confusing
        # LiteLLM failure after the run starts.
        if not body.is_test:
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
            {"provider_id": body.model_override.provider_id, "name": body.model_override.name}
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
    from ..harness.compaction import compact_context, count_tokens, get_model_max_tokens
    from ..harness.context import assemble_system_prompt, build_message_history
    from ..harness.litellm_adapter import LiteLLMAdapter
    from ..models.run import Message, Run
    from ..models.session import Session

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

        # Load all messages from the session
        msg_result = await db.execute(
            select(Message)
            .where(Message.run_id.in_(
                select(Run.id).where(Run.session_id == session.id)
            ))
            .order_by(Message.seq)
        )
        all_messages = msg_result.scalars().all()

        # Build message history (same as harness does)
        # Use a dummy message — compaction works on history, not the new message
        system_prompt = assemble_system_prompt(config, "")
        from types import SimpleNamespace

        recent = [SimpleNamespace(role=m.role, content=m.content) for m in all_messages]
        history = build_message_history(system_prompt, recent, "", None)

        # Get model info
        model_str = "gpt-4o"
        api_key = None
        base_url = None
        adapter = LiteLLMAdapter(db)
        if config.model.is_configured:
            try:
                info = await adapter.get_model_info(config.model)
                model_str = info["model_str"]
                api_key = info["api_key"]
                base_url = info["base_url"]
            except Exception:
                pass

        # Run compaction (force=True)
        system_msgs = [history[0]] if history and history[0].get("role") == "system" else []
        conversation_msgs = history[len(system_msgs):]

        compaction_result = await compact_context(
            messages=conversation_msgs,
            agent_config=config,
            model_str=model_str,
            previous_summary=session.conversation_summary,
            api_key=api_key,
            base_url=base_url,
            force=True,
        )

        # Persist the updated summary
        if compaction_result.summary != session.conversation_summary:
            from sqlalchemy import update as sa_update

            await db.execute(
                sa_update(Session)
                .where(Session.id == session.id)
                .values(conversation_summary=compaction_result.summary)
            )
            await db.commit()

        return {
            "compacted": compaction_result.compacted,
            "original_tokens": compaction_result.original_tokens,
            "compacted_tokens": compaction_result.compacted_tokens,
            "max_context_tokens": get_model_max_tokens(model_str),
            "head_count": compaction_result.head_count,
            "middle_count": compaction_result.middle_count,
            "tail_count": compaction_result.tail_count,
            "summary": compaction_result.summary,
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
    status = get_run_status(run_id)
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
        .outerjoin(Run, Run.session_id == Session.id)
        .outerjoin(Message, Message.run_id == Run.id)
        .where(Session.agent_id == agent_id)
        .group_by(Session.id)
        .order_by(Session.last_activity_at.desc())
    )
    rows = result.all()
    return [
        {
            "id": sess.id,
            "title": sess.title or "New conversation",
            "status": sess.status,
            "started_at": _iso_utc(sess.started_at),
            "last_activity_at": _iso_utc(sess.last_activity_at),
            "message_count": msg_count,
        }
        for sess, msg_count in rows
    ]


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


@router.get("/{agent_id}/sessions/{session_id}/messages")
async def get_session_messages(
    agent_id: str,
    session_id: str,
    operator: Operator = Depends(require_operator),
    db: AsyncSession = Depends(get_db),
    limit: int = 100,
) -> list[dict]:
    """Get messages for a specific session, ordered by run then sequence."""
    result = await db.execute(
        select(Message, Run)
        .join(Run, Message.run_id == Run.id)
        .where(Run.session_id == session_id, Run.agent_id == agent_id)
        .order_by(Run.started_at.asc(), Message.seq.asc(), Message.created_at.asc())
        .limit(limit)
    )
    rows = result.all()
    return [
        {
            "id": msg.id,
            "role": msg.role,
            "content": msg.content,
            "created_at": _iso_utc(msg.created_at),
            "run_id": msg.run_id,
            "run_status": run.status,
            "tokens_in": run.tokens_in,
            "tokens_out": run.tokens_out,
            "cost": run.cost,
            "subagent_id": msg.subagent_id,
            "attachments": msg.attachments,
        }
        for msg, run in rows
    ]


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

    # Delete messages via runs
    run_ids_result = await db.execute(select(Run.id).where(Run.session_id == session_id))
    run_ids = [r[0] for r in run_ids_result.all()]

    if run_ids:
        # Delete child rows first to satisfy FK constraints
        await db.execute(delete(Message).where(Message.run_id.in_(run_ids)))
        await db.execute(delete(AuditRecord).where(AuditRecord.run_id.in_(run_ids)))
        await db.execute(delete(ApprovalRequest).where(ApprovalRequest.run_id.in_(run_ids)))
        await db.execute(delete(ElicitationRequest).where(ElicitationRequest.run_id.in_(run_ids)))
        await db.execute(delete(Run).where(Run.id.in_(run_ids)))

    await db.delete(session)
    await db.commit()
    return {"deleted": True}
