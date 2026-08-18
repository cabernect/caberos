"""External channel API routes (Ticket 08c).

POST   /api/channels/{platform}/webhook   — webhook receiver (platform → CaberOS)
GET    /api/channels                      — list configured channels
POST   /api/channels                      — add a channel config
DELETE /api/channels/{id}                 — remove a channel config
POST   /api/channels/{id}/test            — send a test message
"""

import asyncio
import hmac
import json
import logging
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import require_operator
from ..channels import get_channel, reload_channel, remove_channel
from ..channels.base import OutboundMessage
from ..db import get_db
from ..models.channel_config import ChannelConfig
from ..runner import run_agent
from ..secret_store import encrypt

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/channels", tags=["channels"])


# --- Models ---


class ChannelCreate(BaseModel):
    platform: str  # "telegram", "discord", "zalo", ...
    agent_id: str
    bot_token: str  # plaintext — encrypted before storage
    webhook_secret: str = ""
    enabled: bool = True
    mode: str = "polling"  # "polling" or "webhook"
    extra_config: dict[str, Any] | None = None


class ChannelUpdate(BaseModel):
    """Partial update — all fields optional. bot_token=None means keep existing."""

    bot_token: str | None = None  # if provided, re-encrypt and update
    webhook_secret: str | None = None
    enabled: bool | None = None
    mode: str | None = None


class ChannelOut(BaseModel):
    id: str
    platform: str
    agent_id: str
    enabled: bool
    mode: str
    has_webhook_secret: bool
    webhook_url: str
    has_token: bool
    extra_config: dict[str, Any] | None = None


class ChannelTest(BaseModel):
    chat_id: str  # where to send the test message


# --- Routes ---


@router.get("")
async def list_channels(
    db: AsyncSession = Depends(get_db),
    _op=Depends(require_operator),
) -> list[ChannelOut]:
    """List all configured channels."""
    result = await db.execute(select(ChannelConfig).order_by(ChannelConfig.platform))
    configs = result.scalars().all()
    return [_config_to_out(c) for c in configs]


@router.post("")
async def create_channel(
    req: ChannelCreate,
    db: AsyncSession = Depends(get_db),
    _op=Depends(require_operator),
) -> ChannelOut:
    """Add a new channel configuration."""
    # Check for duplicate
    existing = await db.execute(
        select(ChannelConfig).where(
            ChannelConfig.platform == req.platform,
            ChannelConfig.agent_id == req.agent_id,
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(409, f"Channel {req.platform} already configured for this agent")

    config = ChannelConfig(
        id=str(uuid.uuid4()),
        platform=req.platform,
        agent_id=req.agent_id,
        encrypted_bot_token=encrypt(req.bot_token),
        webhook_secret=req.webhook_secret,
        enabled=req.enabled,
        mode=req.mode,
        extra_config=json.dumps(req.extra_config) if req.extra_config else None,
    )
    db.add(config)
    await db.commit()
    await db.refresh(config)

    # Reload the channel in the registry
    await reload_channel(config)

    return _config_to_out(config)


@router.patch("/{config_id}")
async def update_channel(
    config_id: str,
    req: ChannelUpdate,
    db: AsyncSession = Depends(get_db),
    _op=Depends(require_operator),
) -> ChannelOut:
    """Update a channel configuration. Only provided fields are changed."""
    result = await db.execute(select(ChannelConfig).where(ChannelConfig.id == config_id))
    config = result.scalar_one_or_none()
    if config is None:
        raise HTTPException(404, "Channel not found")

    if req.bot_token is not None:
        config.encrypted_bot_token = encrypt(req.bot_token)
    if req.webhook_secret is not None:
        config.webhook_secret = req.webhook_secret
    if req.enabled is not None:
        config.enabled = req.enabled
    if req.mode is not None:
        config.mode = req.mode

    await db.commit()
    await db.refresh(config)

    # Reload the channel in the registry (stops old polling, starts new)
    await reload_channel(config)

    return _config_to_out(config)


@router.delete("/{config_id}")
async def delete_channel(
    config_id: str,
    db: AsyncSession = Depends(get_db),
    _op=Depends(require_operator),
) -> dict[str, str]:
    """Remove a channel configuration."""
    result = await db.execute(select(ChannelConfig).where(ChannelConfig.id == config_id))
    config = result.scalar_one_or_none()
    if config is None:
        raise HTTPException(404, "Channel not found")

    platform = config.platform
    agent_id = config.agent_id
    await db.delete(config)
    await db.commit()

    # Remove from active registry
    await remove_channel(platform, agent_id)

    return {"status": "deleted"}


@router.post("/{config_id}/test")
async def test_channel(
    config_id: str,
    req: ChannelTest,
    db: AsyncSession = Depends(get_db),
    _op=Depends(require_operator),
) -> dict[str, Any]:
    """Send a test message to verify the channel connection."""
    result = await db.execute(select(ChannelConfig).where(ChannelConfig.id == config_id))
    config = result.scalar_one_or_none()
    if config is None:
        raise HTTPException(404, "Channel not found")

    channel = get_channel(config.platform, config.agent_id)
    if channel is None:
        raise HTTPException(400, "Channel not active — check if enabled")

    outbound = OutboundMessage(
        session_id="test",
        text="✅ CaberOS channel test — connection working!",
        chat_id=req.chat_id,
    )
    result = await channel.deliver(outbound)
    return result


@router.post("/{platform}/webhook")
async def webhook_receiver(
    platform: str,
    request: Request,
    agent_id: str = Query(..., description="Agent ID to route the message to"),
) -> dict[str, Any]:
    """Receive a webhook from an external platform.

    This endpoint is public (no auth) — platforms can't authenticate.
    Security: if the channel has a webhook_secret configured, the request
    must include it (via header or query param, depending on platform).
    Requests without a valid secret are rejected with 401.
    """
    # Get the channel config to check webhook secret
    db_session_gen = get_db()
    db = await anext(db_session_gen)
    try:
        result = await db.execute(
            select(ChannelConfig).where(
                ChannelConfig.platform == platform,
                ChannelConfig.agent_id == agent_id,
            )
        )
        config = result.scalar_one_or_none()
    finally:
        await db.close()

    if config is None:
        raise HTTPException(404, f"No {platform} channel for agent {agent_id}")

    # Verify webhook secret if configured
    if config.webhook_secret:
        provided = (
            request.headers.get("X-Webhook-Secret")
            or request.headers.get("X-Bot-Api-Secret-Token")
            or request.query_params.get("webhook_secret")
        )
        if not provided or not hmac.compare_digest(provided, config.webhook_secret):
            raise HTTPException(401, "Invalid or missing webhook secret")

    # Get the channel instance
    channel = get_channel(platform, agent_id)
    if channel is None:
        raise HTTPException(404, f"No active {platform} channel for agent {agent_id}")

    # Parse the webhook payload
    try:
        raw_payload = await request.json()
    except Exception:
        raise HTTPException(400, "Invalid JSON payload")

    # Parse into InboundMessage
    inbound = await channel.receive(raw_payload)
    if inbound is None:
        return {"status": "ignored", "reason": "non-text message or unsupported payload"}

    # Send typing indicator (if supported)
    await channel.send_typing(inbound.external_user_id)

    # Run the agent (fire-and-forget — webhook must return quickly)
    async def _run_and_deliver():
        try:
            result = await run_agent(
                agent_id=agent_id,
                text=inbound.text,
                user_id=inbound.external_user_id,
                channel=platform,
                trigger="user_message",
            )
            # Fetch the final answer from the DB (stored as the last assistant message)
            if result.get("status") == "completed":
                from sqlalchemy import select

                from ..db import async_session_factory
                from ..models.run import Message, Run

                async with async_session_factory() as db:
                    stmt = (
                        select(Message.content)
                        .join(Run, Message.run_id == Run.id)
                        .where(Run.id == result["run_id"], Message.role == "assistant")
                        .order_by(Message.seq.desc())
                        .limit(1)
                    )
                    msg_result = await db.execute(stmt)
                    final_answer = msg_result.scalar_one_or_none()

                if final_answer:
                    outbound = OutboundMessage(
                        session_id=result["session_id"],
                        text=final_answer,
                        chat_id=inbound.external_user_id,
                        reply_to_message_id=inbound.message_id,
                    )
                    await channel.deliver(outbound)
        except Exception:
            log.error("Channel run failed", exc_info=True)

    asyncio.create_task(_run_and_deliver())

    return {"status": "accepted"}


def _config_to_out(config: ChannelConfig) -> ChannelOut:
    """Convert a ChannelConfig to a ChannelOut response."""
    extra = json.loads(config.extra_config) if config.extra_config else None
    # Build the webhook URL
    webhook_url = f"/api/channels/{config.platform}/webhook?agent_id={config.agent_id}"
    return ChannelOut(
        id=config.id,
        platform=config.platform,
        agent_id=config.agent_id,
        enabled=config.enabled,
        mode=config.mode,
        has_webhook_secret=bool(config.webhook_secret),
        webhook_url=webhook_url,
        has_token=bool(config.encrypted_bot_token),
        extra_config=extra,
    )
