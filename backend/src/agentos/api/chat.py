"""Dashboard chat channel API routes (D20, D33).

POST /api/chat/{agent_id}/message — send a message
GET  /api/chat/{agent_id}/stream  — per-conversation SSE stream
GET  /api/chat/{agent_id}/history — conversation history
"""

import asyncio
import json
import uuid
from collections import defaultdict
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import require_operator
from ..db import async_session_factory, get_db
from ..harness.litellm_adapter import LiteLLMAdapter
from ..harness.loop import Harness
from ..models.agent import Agent
from ..models.operator import Operator
from ..models.run import Message, Run
from ..pipeline import InboundMessage, Pipeline

router = APIRouter(prefix="/api/chat", tags=["chat"])

# Per-agent SSE subscriber queues: agent_id -> list[asyncio.Queue]
# When a run emits events, they go to all subscribers for that agent.
_subscribers: dict[str, list[asyncio.Queue]] = defaultdict(list)


class SendMessageRequest(BaseModel):
    text: str
    is_test: bool = False


class MessageOut(BaseModel):
    id: str
    role: str
    content: str
    created_at: str


async def _broadcast(agent_id: str, event_type: str, payload: dict) -> None:
    """Push an SSE event to all subscribers watching this agent."""
    for queue in _subscribers.get(agent_id, []):
        try:
            queue.put_nowait((event_type, payload))
        except asyncio.QueueFull:
            pass  # drop if subscriber is slow


@router.post("/{agent_id}/message")
async def send_message(
    agent_id: str,
    body: SendMessageRequest,
    operator: Operator = Depends(require_operator),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Send a message to an agent. Triggers a run."""
    # Verify agent exists
    result = await db.execute(select(Agent).where(Agent.id == agent_id))
    agent = result.scalar_one_or_none()
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent not found")

    message_id = str(uuid.uuid4())
    inbound = InboundMessage(
        channel="dashboard_chat",
        bot_id=agent_id,
        external_user_id=operator.id,  # operator is the user in dashboard chat
        text=body.text,
        message_id=message_id,
        is_test=body.is_test,
    )

    # Run the pipeline in the background so we can stream events
    # Use a fresh DB session for the background task
    async def _run_pipeline() -> None:
        async with async_session_factory() as run_db:
            # Use LiteLLM adapter for real model access
            adapter = LiteLLMAdapter(run_db)
            harness = Harness(model=adapter)
            pipeline = Pipeline(db=run_db, harness=harness)

            # Set up event emitter that broadcasts to SSE subscribers
            async def event_emitter(event_type: str, payload: dict) -> None:
                await _broadcast(agent_id, event_type, payload)

            try:
                run = await pipeline.handle_inbound(
                    message=inbound,
                    trigger="user_message",
                    is_test=body.is_test,
                )
                # Broadcast the final message_complete with run info
                await _broadcast(
                    agent_id,
                    "message_complete",
                    {
                        "run_id": run.id,
                        "status": run.status,
                        "total_cost": run.cost,
                        "total_turns": 0,  # TODO: from result
                    },
                )
            except Exception as e:
                await _broadcast(
                    agent_id,
                    "message_complete",
                    {"run_id": "", "status": "failed", "error": str(e)},
                )

    asyncio.create_task(_run_pipeline())

    return {"message_id": message_id, "status": "queued"}


@router.get("/{agent_id}/stream")
async def stream(
    agent_id: str,
    request: Request,
    operator: Operator = Depends(require_operator),
) -> StreamingResponse:
    """Per-conversation SSE stream. Stays open; frontend opens on entering conversation view."""

    queue: asyncio.Queue = asyncio.Queue(maxsize=100)
    _subscribers[agent_id].append(queue)

    async def event_stream() -> Any:
        try:
            # Send a heartbeat every 15s to keep the connection alive
            heartbeat_task = asyncio.create_task(_heartbeat(queue))

            while True:
                if await request.is_disconnected():
                    break
                try:
                    event_type, payload = await asyncio.wait_for(queue.get(), timeout=1.0)
                    data = json.dumps(payload)
                    yield f"event: {event_type}\ndata: {data}\n\n"
                except TimeoutError:
                    continue
        finally:
            heartbeat_task.cancel()
            if queue in _subscribers.get(agent_id, []):
                _subscribers[agent_id].remove(queue)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


async def _heartbeat(queue: asyncio.Queue) -> None:
    """Send periodic heartbeat comments to keep the SSE connection alive."""
    while True:
        await asyncio.sleep(15)
        try:
            queue.put_nowait(("heartbeat", {"ts": datetime.now(UTC).isoformat()}))
        except asyncio.QueueFull:
            pass


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
            "created_at": msg.created_at.isoformat() if msg.created_at else "",
            "run_id": msg.run_id,
        }
        for msg, run in rows
    ]
