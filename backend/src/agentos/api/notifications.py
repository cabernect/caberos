"""Operator notification API — inbox, delivery state, prefs, SSE (W9)."""

import asyncio
import json
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from .. import notifications as notif
from ..auth import require_operator
from ..db import get_db
from ..models.notification import Notification, NotificationDelivery, NotificationPrefs

router = APIRouter(prefix="/api/notifications", tags=["notifications"])


class NotificationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    notification_type: str
    severity: str
    title: str
    message: str
    action_path: str | None
    entity_id: str | None
    entity_type: str | None = None
    agent_id: str | None = None
    agent_name: str | None = None
    event_id: str | None = None
    read: bool
    created_at: datetime


class DeliveryReport(BaseModel):
    adapter: str  # toast | browser | system
    state: str  # delivered | suppressed | failed
    error: str | None = None


class EmitRequest(BaseModel):
    """Frontend-driven emitters (e.g. update_available) — dedup via event_id."""

    notification_type: str
    title: str
    message: str
    severity: str = "info"
    action_path: str | None = None
    entity_id: str | None = None
    entity_type: str | None = None
    event_id: str | None = None


# -- inbox --------------------------------------------------------------------


@router.get("", response_model=list[NotificationOut])
async def list_notifications(
    unread_only: bool = False,
    db: AsyncSession = Depends(get_db),
    _operator=Depends(require_operator),
):
    # julianday normalizes the stored string — plain ORDER BY breaks when rows
    # mix ISO variants ("T"+offset vs space separator), sorting all T-rows
    # above all space-rows regardless of actual time.
    query = select(Notification).order_by(func.julianday(Notification.created_at).desc()).limit(100)
    if unread_only:
        query = query.where(Notification.read.is_(False))
    result = await db.execute(query)
    return list(result.scalars().all())


@router.post("/read-all")
async def mark_all_notifications_read(
    db: AsyncSession = Depends(get_db),
    _operator=Depends(require_operator),
):
    await db.execute(update(Notification).where(Notification.read.is_(False)).values(read=True))
    await db.commit()
    return {"updated": True}


@router.post("/{notification_id}/read")
async def mark_notification_read(
    notification_id: str,
    db: AsyncSession = Depends(get_db),
    _operator=Depends(require_operator),
):
    result = await db.execute(select(Notification).where(Notification.id == notification_id))
    notification = result.scalar_one_or_none()
    if notification is None:
        raise HTTPException(status_code=404, detail="Notification not found")
    notification.read = True
    await db.commit()
    return {"updated": True}


# -- SSE stream ---------------------------------------------------------------


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload)}\n\n"


@router.get("/stream")
async def notification_stream(_operator=Depends(require_operator)):
    """SSE fan-out — one event per committed notification row.

    The client's delivery coordinator evaluates suppression/prefs on
    arrival; the 5 s inbox poll remains as a reconnect fallback.
    """
    queue = notif.subscribe()

    async def gen():
        try:
            yield _sse({"type": "hello"})
            while True:
                try:
                    payload = await asyncio.wait_for(queue.get(), timeout=25.0)
                    yield _sse({"type": "notification", "notification": payload})
                except TimeoutError:
                    yield ": keepalive\n\n"
        finally:
            notif.unsubscribe(queue)

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# -- deliveries ---------------------------------------------------------------


@router.post("/{notification_id}/delivery")
async def report_delivery(
    notification_id: str,
    report: DeliveryReport,
    db: AsyncSession = Depends(get_db),
    _operator=Depends(require_operator),
):
    """Upsert a per-surface delivery outcome (leader tab reports)."""
    notif_row = await db.get(Notification, notification_id)
    if notif_row is None:
        raise HTTPException(status_code=404, detail="Notification not found")
    row = await db.scalar(
        select(NotificationDelivery).where(
            NotificationDelivery.notification_id == notification_id,
            NotificationDelivery.adapter == report.adapter,
        )
    )
    if row is None:
        row = NotificationDelivery(notification_id=notification_id, adapter=report.adapter)
        db.add(row)
    row.state = report.state
    row.attempts = (row.attempts or 0) + 1
    row.error = report.error
    await db.commit()
    return {"recorded": True}


@router.get("/deliveries/failed")
async def failed_deliveries(
    db: AsyncSession = Depends(get_db),
    _operator=Depends(require_operator),
):
    """Retry candidates: failed adapters on still-unread notifications."""
    result = await db.execute(
        select(NotificationDelivery, Notification)
        .join(Notification, NotificationDelivery.notification_id == Notification.id)
        .where(NotificationDelivery.state == "failed", Notification.read.is_(False))
        .where(NotificationDelivery.attempts < 2)
    )
    return [
        {
            "notification": NotificationOut.model_validate(n),
            "adapter": d.adapter,
            "attempts": d.attempts,
        }
        for d, n in result.all()
    ]


# -- prefs --------------------------------------------------------------------


def _default_prefs() -> dict:
    return {
        "defaults": {"inbox": True, "toast": True, "browser": False, "system": False},
        "overrides": {},
        "quiet_hours": {"enabled": False, "start": "22:00", "end": "07:00", "tz": None},
        "permissions": {"browser_asked": False, "tauri_asked": False},
    }


async def _get_prefs(db: AsyncSession) -> NotificationPrefs:
    row = await db.scalar(select(NotificationPrefs).limit(1))
    if row is None:
        row = NotificationPrefs(prefs=json.dumps(_default_prefs()))
        db.add(row)
        await db.commit()
    return row


@router.get("/prefs")
async def get_prefs(db: AsyncSession = Depends(get_db), _operator=Depends(require_operator)):
    row = await _get_prefs(db)
    return json.loads(row.prefs)


@router.put("/prefs")
async def put_prefs(
    body: dict,
    db: AsyncSession = Depends(get_db),
    _operator=Depends(require_operator),
):
    """Patch the prefs blob — merged onto the *stored* state so a client
    only ever writes the fields it meant to change. Whole-blob PUTs used
    to let a stale tab revert fields it never touched (B35).

    Merge rules per top-level key:
    - dict-valued keys (`defaults`, `quiet_hours`, `permissions`) merge
      shallowly — send just the leaves you change;
    - `overrides` merges per event type: a dict upserts that event's
      override, `null` deletes it (omission can't express deletion);
    - scalars replace.
    """
    row = await _get_prefs(db)
    try:
        stored = json.loads(row.prefs)
    except (TypeError, json.JSONDecodeError):
        stored = {}
    merged = _default_prefs()
    for key, value in stored.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key].update(value)
        else:
            merged[key] = value
    for key, value in body.items():
        if key == "overrides" and isinstance(value, dict):
            for event_type, override in value.items():
                if override is None:
                    merged["overrides"].pop(event_type, None)
                else:
                    merged["overrides"][event_type] = override
        elif isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key].update(value)
        else:
            merged[key] = value
    row.prefs = json.dumps(merged)
    await db.commit()
    return merged


# -- frontend-driven emits ----------------------------------------------------


@router.post("/emit", response_model=NotificationOut)
async def emit_notification(
    req: EmitRequest,
    db: AsyncSession = Depends(get_db),
    _operator=Depends(require_operator),
):
    """Let the client emit events that have no backend source (e.g.
    update_available) so they flow through inbox/dedup/prefs like the rest."""
    item = await notif.create_notification(
        db,
        notification_type=req.notification_type,
        severity=req.severity,
        title=req.title,
        message=req.message,
        action_path=req.action_path,
        entity_id=req.entity_id,
        entity_type=req.entity_type,
        event_id=req.event_id,
    )
    await db.commit()
    return item
