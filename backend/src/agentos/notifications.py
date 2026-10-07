"""Persistent operator notifications + event fan-out (W9).

Emitters write a Notification row with a deterministic ``event_id``; a
unique index makes re-emission a no-op (INSERT-or-ignore), so tick
retries, restart replays, and double-emitters can never duplicate. When
the caller's transaction commits, the row is broadcast to SSE
subscribers — the in-app inbox is written first, always.
"""

import asyncio
import hashlib
import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import delete, event, func, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from .models.notification import Notification, NotificationDelivery

log = logging.getLogger("agentos.notifications")

# ---------------------------------------------------------------------------
# SSE fan-out — one asyncio.Queue per subscriber (the /stream endpoint holds
# one per connected tab; the cross-tab leader decides who pings).
# ---------------------------------------------------------------------------

_subscribers: set[asyncio.Queue] = set()


def subscribe() -> asyncio.Queue:
    q: asyncio.Queue = asyncio.Queue(maxsize=256)
    _subscribers.add(q)
    return q


def unsubscribe(q: asyncio.Queue) -> None:
    _subscribers.discard(q)


def broadcast(payload: dict) -> None:
    for q in list(_subscribers):
        try:
            q.put_nowait(payload)
        except asyncio.QueueFull:
            # Slow consumer — drop rather than block emitters.
            pass


def notification_payload(item: Notification) -> dict:
    return {
        "id": item.id,
        "notification_type": item.notification_type,
        "severity": item.severity,
        "title": item.title,
        "message": item.message,
        "action_path": item.action_path,
        "entity_id": item.entity_id,
        "entity_type": item.entity_type,
        "agent_id": item.agent_id,
        "agent_name": item.agent_name,
        "event_id": item.event_id,
        "read": item.read,
        "created_at": item.created_at.isoformat() if item.created_at else None,
    }


def _emit_after_commit(db: AsyncSession, item: Notification) -> None:
    """Broadcast once the caller's transaction actually commits.

    A rollback must disarm the listener too — otherwise it survives and
    fires on the session's *next* commit, broadcasting a row that was
    never persisted.
    """
    payload = notification_payload(item)
    target = db.sync_session

    def _emit(_session) -> None:
        event.remove(target, "after_rollback", _drop)
        broadcast(payload)

    def _drop(_session) -> None:
        event.remove(target, "after_commit", _emit)

    event.listen(target, "after_commit", _emit, once=True)
    event.listen(target, "after_rollback", _drop, once=True)


async def create_notification(
    db: AsyncSession,
    *,
    notification_type: str,
    severity: str,
    title: str,
    message: str,
    action_path: str | None = None,
    entity_id: str | None = None,
    entity_type: str | None = None,
    event_id: str | None = None,
    agent_id: str | None = None,
) -> Notification:
    """Write a notification row; dedup on ``event_id``.

    ``event_id`` is a deterministic emitter key (``{type}:{entity}:{key}``).
    When absent it is synthesized from content, so every event is
    idempotent — two occurrences of the *same* event collapse, two
    *distinct* events each notify.

    ``agent_id`` marks which agent produced the event; the display name is
    resolved + snapshotted onto the row so the UI needs no join and the
    badge survives renames/deletes.
    """
    agent_name: str | None = None
    if agent_id:
        from .models.agent import Agent

        agent_name = await db.scalar(
            select(Agent.name).where(Agent.id == agent_id).limit(1)
        )
    if event_id is None:
        digest = hashlib.sha256(
            f"{notification_type}|{entity_id}|{title}|{message}".encode()
        ).hexdigest()[:32]
        event_id = f"{notification_type}:{entity_id or '-'}:{digest}"

    existing = await db.scalar(
        select(Notification).where(Notification.event_id == event_id).limit(1)
    )
    if existing:
        return existing

    # INSERT ... ON CONFLICT DO NOTHING — one atomic statement, so a unique-
    # index collision can't error the caller's transaction the way the old
    # savepoint+retry needed to. (That savepoint also broke under aiosqlite
    # on a SELECT-only session: the legacy driver layer emits SAVEPOINT
    # while still in autocommit, the INSERT then opens the implicit BEGIN,
    # and RELEASE fails with "no such savepoint" — B32.)
    now = datetime.now(timezone.utc)
    values = {
        "id": str(uuid.uuid4()),
        "notification_type": notification_type,
        "severity": severity,
        "title": title,
        "message": message,
        "action_path": action_path,
        "entity_id": entity_id,
        "entity_type": entity_type,
        "agent_id": agent_id,
        "agent_name": agent_name,
        "event_id": event_id,
        "read": False,
        "created_at": now,
        "updated_at": now,
    }
    if db.bind and db.bind.dialect.name == "postgresql":
        from sqlalchemy.dialects.postgresql import insert as pg_insert

        stmt = pg_insert(Notification.__table__).values(**values)
    else:
        stmt = sqlite_insert(Notification.__table__).values(**values)
    # Bare ON CONFLICT DO NOTHING — the unique index on event_id is partial
    # (WHERE event_id IS NOT NULL), which can't be named as a conflict
    # target without repeating its WHERE clause; the bare form covers any
    # constraint violation anyway.
    result = await db.execute(stmt.on_conflict_do_nothing())
    item = await db.scalar(
        select(Notification).where(Notification.event_id == event_id).limit(1)
    )
    if item is None:
        # Insert conflicted but the winner isn't visible to our transaction
        # yet — same race the old retry loop covered. Report success-shape;
        # the row will appear on the winner's commit either way.
        return Notification(
            notification_type=notification_type,
            severity=severity,
            title=title,
            message=message,
            action_path=action_path,
            entity_id=entity_id,
            entity_type=entity_type,
            agent_id=agent_id,
            agent_name=agent_name,
            event_id=event_id,
        )
    if result.rowcount:
        _emit_after_commit(db, item)
    return item


def one_line(text: str, limit: int = 160) -> str:
    """Collapse a blob to a single-line excerpt for the notification body."""
    s = " ".join(text.split())
    return s if len(s) <= limit else s[: limit - 1].rstrip() + "…"


def call_brief(payload: dict) -> str:
    """Short human description of a pending tool call for approval pings —
    the capability plus its headline arg (command/url/path/...), and a
    '(+N more)' suffix when the call arrived in an approval batch."""
    import json as _json

    cap = str(payload.get("capability") or "tool")
    args = payload.get("args") or {}
    if not isinstance(args, dict):
        args = {}
    headline = next(
        (
            str(args[k])
            for k in ("command", "cmd", "url", "path", "query", "name", "question", "task")
            if args.get(k)
        ),
        "",
    )
    if not headline and args:
        headline = _json.dumps(args, ensure_ascii=False)
    brief = f"{cap} — {one_line(headline, 120)}" if headline else cap
    batch = payload.get("approval_batch_size") or 1
    if isinstance(batch, int) and batch > 1:
        brief += f" (+{batch - 1} more)"
    return brief


async def prune_notifications(db: AsyncSession, *, max_age_days: int = 30) -> int:
    """Delete notifications (and their delivery rows) older than max_age_days.

    The inbox is append-only otherwise — a long-lived install accumulates a
    row per run completion, approval, and suppressed delivery forever. Runs
    once at gateway startup; unread rows are not exempt — a notification
    nobody looked at for a month is noise either way.
    """
    cutoff = func.datetime("now", f"-{max_age_days} days")
    n = await db.execute(
        delete(Notification).where(func.julianday(Notification.created_at) < func.julianday(cutoff))
    )
    await db.execute(
        delete(NotificationDelivery).where(
            func.julianday(NotificationDelivery.created_at) < func.julianday(cutoff)
        )
    )
    deleted = n.rowcount or 0
    if deleted:
        log.info("Pruned %d notification(s) older than %d days", deleted, max_age_days)
    return deleted
