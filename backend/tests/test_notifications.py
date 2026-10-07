import asyncio

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from agentos import notifications as notif
from agentos.auth import require_operator
from agentos.db import get_db
from agentos.main import app
from agentos.models.base import Base
from agentos.models.notification import Notification, NotificationDelivery
from agentos.models.operator import Operator
from agentos.notifications import create_notification


@pytest.fixture
async def client(db):
    async def fake_operator():
        return Operator(id="test-operator", username="test", password_hash="x")

    app.dependency_overrides[require_operator] = fake_operator
    app.dependency_overrides[get_db] = lambda: db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as http:
        yield http
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_notifications_are_listed_and_marked_read(client, db):
    await create_notification(
        db,
        notification_type="oauth_reauth_required",
        severity="error",
        title="Reconnect Notion",
        message="The OAuth refresh token is no longer valid.",
        action_path="/mcps",
        entity_id="server-1",
    )
    await db.commit()

    unread = await client.get("/api/notifications", params={"unread_only": True})
    assert unread.status_code == 200
    notification = unread.json()[0]
    assert notification["title"] == "Reconnect Notion"
    assert notification["read"] is False

    marked = await client.post(f"/api/notifications/{notification['id']}/read")
    assert marked.status_code == 200
    assert (await client.get("/api/notifications", params={"unread_only": True})).json() == []


@pytest.mark.asyncio
async def test_unread_notifications_are_deduplicated(db):
    first = await create_notification(
        db,
        notification_type="gateway_error",
        severity="error",
        title="Gateway unavailable",
        message="Retry the gateway.",
        entity_id="gateway",
    )
    await db.commit()
    second = await create_notification(
        db,
        notification_type="gateway_error",
        severity="error",
        title="Gateway unavailable",
        message="Retry the gateway.",
        entity_id="gateway",
    )
    assert second.id == first.id


# ---------------------------------------------------------------------------
# W9 — event_id idempotency, deliveries, prefs, SSE ordering
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_event_id_is_idempotent(client, db):
    """Same event_id twice → one row, same id — INSERT-or-ignore."""
    first = await create_notification(
        db,
        notification_type="schedule_failed",
        severity="error",
        title="Heartbeat failed",
        message="3 consecutive failures",
        entity_id="agent-1",
        entity_type="agent",
        event_id="schedule_failed:agent-1:2026-01-02",
    )
    await db.commit()
    second = await create_notification(
        db,
        notification_type="schedule_failed",
        severity="error",
        title="Heartbeat failed",
        message="3 consecutive failures",
        entity_id="agent-1",
        entity_type="agent",
        event_id="schedule_failed:agent-1:2026-01-02",
    )
    await db.commit()
    assert second.id == first.id
    resp = await client.get("/api/notifications")
    assert len(resp.json()) == 1


@pytest.mark.asyncio
async def test_distinct_event_ids_not_collapsed(client, db):
    """Two occurrences of the same event type = two notifications."""
    for day in ("2026-01-02", "2026-01-03"):
        await create_notification(
            db,
            notification_type="schedule_failed",
            severity="error",
            title="Heartbeat failed",
            message="3 consecutive failures",
            entity_id="agent-1",
            entity_type="agent",
            event_id=f"schedule_failed:agent-1:{day}",
        )
    await db.commit()
    resp = await client.get("/api/notifications")
    assert len(resp.json()) == 2


@pytest.mark.asyncio
async def test_concurrent_same_event_id_collapses(tmp_path):
    """Two sessions on separate connections racing the same event_id →
    one winner row. File-backed SQLite + the real partial unique index —
    the in-memory engine shares one connection and can't race."""
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/t.db")
    async with engine.begin() as conn:
        # create_all now builds ux_notifications_event_id itself — it's a
        # declared model Index, so the manual DDL is no longer needed.
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def emit(session: AsyncSession):
        item = await create_notification(
            session,
            notification_type="update_available",
            severity="info",
            title="Update",
            message="v1.2.3",
            entity_id="caberos",
            event_id="update_available:1.2.3",
        )
        await session.commit()
        return item

    async with factory() as s1, factory() as s2:
        first, second = await asyncio.gather(emit(s1), emit(s2))
        assert first.id == second.id
    await engine.dispose()


@pytest.mark.asyncio
async def test_delivery_report_upserts_attempts(client, db):
    item = await create_notification(
        db,
        notification_type="run_failed",
        severity="error",
        title="Run failed",
        message="boom",
        entity_id="run-1",
    )
    await db.commit()

    first = await client.post(
        f"/api/notifications/{item.id}/delivery",
        json={"adapter": "browser", "state": "failed", "error": "permission_denied"},
    )
    assert first.status_code == 200
    second = await client.post(
        f"/api/notifications/{item.id}/delivery",
        json={"adapter": "browser", "state": "delivered"},
    )
    assert second.status_code == 200

    row = await db.scalar(
        select(NotificationDelivery).where(
            NotificationDelivery.notification_id == item.id,
            NotificationDelivery.adapter == "browser",
        )
    )
    assert row.state == "delivered"
    assert row.attempts == 2
    assert row.error is None


@pytest.mark.asyncio
async def test_failed_deliveries_filters_unread_and_attempts(client, db):
    unread_failed = await create_notification(
        db, notification_type="run_failed", severity="error",
        title="A", message="m", entity_id="r1", event_id="e:r1",
    )
    read_failed = await create_notification(
        db, notification_type="run_failed", severity="error",
        title="B", message="m", entity_id="r2", event_id="e:r2",
    )
    exhausted = await create_notification(
        db, notification_type="run_failed", severity="error",
        title="C", message="m", entity_id="r3", event_id="e:r3",
    )
    read_failed.read = True
    db.add_all(
        [
            NotificationDelivery(
                notification_id=unread_failed.id, adapter="browser",
                state="failed", attempts=1,
            ),
            NotificationDelivery(
                notification_id=read_failed.id, adapter="browser",
                state="failed", attempts=1,
            ),
            NotificationDelivery(
                notification_id=exhausted.id, adapter="browser",
                state="failed", attempts=2,
            ),
        ]
    )
    await db.commit()

    resp = await client.get("/api/notifications/deliveries/failed")
    assert resp.status_code == 200
    ids = [r["notification"]["id"] for r in resp.json()]
    assert ids == [unread_failed.id]  # read + exhausted both excluded


@pytest.mark.asyncio
async def test_prefs_defaults_and_merge(client):
    got = await client.get("/api/notifications/prefs")
    assert got.status_code == 200
    body = got.json()
    assert body["defaults"]["toast"] is True
    assert body["defaults"]["browser"] is False
    assert body["quiet_hours"]["enabled"] is False

    put = await client.put(
        "/api/notifications/prefs",
        json={
            "quiet_hours": {"enabled": True, "start": "23:00"},
            "overrides": {"run_completed": {"toast": False}},
        },
    )
    assert put.status_code == 200
    merged = put.json()
    # Shallow merge keeps un-specified sub-keys.
    assert merged["quiet_hours"]["end"] == "07:00"
    assert merged["quiet_hours"]["enabled"] is True
    assert merged["overrides"]["run_completed"]["toast"] is False

    got2 = await client.get("/api/notifications/prefs")
    assert got2.json()["quiet_hours"]["start"] == "23:00"


@pytest.mark.asyncio
async def test_prefs_patch_merges_onto_stored(client):
    """B35: a client sends only the fields it means to change — a stale
    tab's patch must not revert untouched fields, and null deletes."""
    await client.put(
        "/api/notifications/prefs",
        json={
            "quiet_hours": {"enabled": True, "start": "14:00", "end": "16:00"},
            "overrides": {"run_failed": {"toast": False}},
        },
    )
    # A banner's permissions patch carries nothing else — stored state stands.
    put = await client.put(
        "/api/notifications/prefs", json={"permissions": {"browser_asked": True}}
    )
    merged = put.json()
    assert merged["quiet_hours"]["enabled"] is True
    assert merged["quiet_hours"]["start"] == "14:00"
    assert merged["overrides"]["run_failed"]["toast"] is False
    assert merged["permissions"]["browser_asked"] is True

    # null deletes just that event's override (omission can't express it).
    put2 = await client.put(
        "/api/notifications/prefs", json={"overrides": {"run_failed": None}}
    )
    assert put2.json()["overrides"] == {}


@pytest.mark.asyncio
async def test_broadcast_fires_only_after_commit(db):
    """SSE payload must not reach subscribers before the row commits."""
    q = notif.subscribe()
    try:
        item = await create_notification(
            db, notification_type="run_completed", severity="success",
            title="done", message="m", entity_id="run-9",
            event_id="run_completed:run-9",
        )
        assert q.empty()  # uncommitted — nothing visible yet
        await db.commit()
        payload = q.get_nowait()
        assert payload["id"] == item.id
        assert payload["event_id"] == "run_completed:run-9"
    finally:
        notif.unsubscribe(q)


@pytest.mark.asyncio
async def test_rollback_never_broadcasts(db):
    """A rolled-back row must not broadcast on a later commit either."""
    q = notif.subscribe()
    try:
        await create_notification(
            db, notification_type="run_failed", severity="error",
            title="ghost", message="m", entity_id="run-x",
            event_id="ghost:run-x",
        )
        await db.rollback()
        # A subsequent unrelated commit must not flush the stale listener.
        db.add(
            Notification(
                notification_type="x", severity="info",
                title="y", message="z",
            )
        )
        await db.commit()
        assert q.empty()
    finally:
        notif.unsubscribe(q)


@pytest.mark.asyncio
async def test_emit_endpoint_dedupes(client):
    body = {
        "notification_type": "update_available",
        "severity": "info",
        "title": "Update available",
        "message": "v9.9.9 is ready",
        "entity_type": "app",
        "entity_id": "caberos",
        "event_id": "update_available:9.9.9",
    }
    first = await client.post("/api/notifications/emit", json=body)
    assert first.status_code == 200
    second = await client.post("/api/notifications/emit", json=body)
    assert second.status_code == 200
    assert first.json()["id"] == second.json()["id"]
    assert len((await client.get("/api/notifications")).json()) == 1


@pytest.mark.asyncio
async def test_inbox_orders_mixed_timestamp_formats(client, db):
    """Rows whose created_at strings differ in ISO shape must still sort
    chronologically — a raw ORDER BY on the text sorts every "T"-separated
    value above every space-separated one regardless of the actual time."""
    await db.execute(
        text(
            "INSERT INTO notifications "
            "(id, created_at, updated_at, notification_type, severity, "
            " title, message, read) VALUES "
            "('old-tz', '2026-10-06T03:18:18.975751+00:00', "
            " '2026-10-06T03:18:18.975751+00:00', "
            " 'run_completed', 'info', 'old', 'm', 0), "
            "('new-naive', '2026-10-06 06:34:35.259824', "
            " '2026-10-06 06:34:35.259824', "
            " 'run_completed', 'info', 'new', 'm', 0)"
        )
    )
    await db.commit()

    resp = await client.get("/api/notifications")
    assert resp.status_code == 200
    assert [r["title"] for r in resp.json()] == ["new", "old"]


@pytest.mark.asyncio
async def test_agent_attribution_snapshots_name(client, db):
    """Emitters pass agent_id; the row snapshots the display name at emit
    time so the badge survives later renames and needs no join."""
    from agentos.models.agent import Agent

    db.add(Agent(id="agent-1", name="Atlas"))
    await db.commit()

    item = await create_notification(
        db,
        notification_type="run_completed",
        severity="info",
        title="Run completed",
        message="Done.",
        entity_id="r1",
        agent_id="agent-1",
    )
    await db.commit()
    assert item.agent_id == "agent-1"
    assert item.agent_name == "Atlas"

    resp = await client.get("/api/notifications")
    row = next(r for r in resp.json() if r["id"] == item.id)
    assert row["agent_id"] == "agent-1"
    assert row["agent_name"] == "Atlas"

    # System-scoped events carry no attribution.
    other = await create_notification(
        db,
        notification_type="mcp_connection_failed",
        severity="error",
        title="MCP down",
        message="m",
    )
    assert other.agent_id is None
    assert other.agent_name is None


@pytest.mark.asyncio
async def test_prune_notifications_ages_out_rows_and_deliveries(db):
    """Retention: rows older than the window are deleted along with their
    delivery rows; fresh rows survive."""
    from agentos.notifications import prune_notifications

    item = await create_notification(
        db,
        notification_type="run_completed",
        severity="info",
        title="fresh",
        message="m",
        event_id="fresh-1",
    )
    db.add(NotificationDelivery(notification_id=item.id, adapter="toast", state="delivered"))
    await db.execute(
        text(
            "INSERT INTO notifications "
            "(id, created_at, updated_at, notification_type, severity, "
            " title, message, read) VALUES "
            "('ancient', '2000-01-01 00:00:00', '2000-01-01 00:00:00', "
            " 'run_completed', 'info', 'old', 'm', 0)"
        )
    )
    await db.execute(
        text(
            "INSERT INTO notification_deliveries "
            "(id, created_at, updated_at, notification_id, adapter, state, attempts) "
            "VALUES ('d-ancient', '2000-01-01 00:00:00', '2000-01-01 00:00:00', "
            " 'ancient', 'toast', 'delivered', 1)"
        )
    )
    await db.commit()

    deleted = await prune_notifications(db, max_age_days=30)
    await db.commit()

    assert deleted == 1
    remaining = (await db.execute(select(Notification))).scalars().all()
    assert [n.id for n in remaining] == [item.id]
    deliveries = (await db.execute(select(NotificationDelivery))).scalars().all()
    assert [d.notification_id for d in deliveries] == [item.id]


@pytest.mark.asyncio
async def test_startup_reconcile_interrupts_pending_approvals(db):
    """B42 — a pending approval's wait lives in an in-memory event, so every
    pending row is dead after a restart. Reconcile marks them interrupted
    so a stale card can't "succeed" on a dead run; decided rows are left."""
    import json

    from agentos.main import reconcile_pending_approvals
    from agentos.models.approval import ApprovalRequest
    from agentos.models.run import Message

    db.add_all(
        [
            ApprovalRequest(
                id="ap-dead",
                run_id="r-dead",
                capability_name="terminal",
                args='{"command": "rm -rf tmp/"}',
                status="pending",
            ),
            ApprovalRequest(
                id="ap-decided",
                run_id="r-dead",
                capability_name="terminal",
                args="{}",
                status="approved",
            ),
            Message(id="m-0", run_id="r-dead", role="user", content="hi", seq=5),
        ]
    )
    await db.commit()

    marked = await reconcile_pending_approvals(db)
    await db.commit()

    assert marked == 1
    rows = {
        a.id: a
        for a in (await db.execute(select(ApprovalRequest))).scalars().all()
    }
    assert rows["ap-dead"].status == "interrupted"
    assert rows["ap-dead"].decided_by == "system_restart"
    assert rows["ap-decided"].status == "approved"

    # The parked call leaves an interrupted tool_call row on the timeline
    # instead of vanishing — only for stale approvals, never decided ones.
    tool_rows = [
        m
        for m in (await db.execute(select(Message).where(Message.run_id == "r-dead")))
        .scalars()
        .all()
        if m.role == "tool_call"
    ]
    assert len(tool_rows) == 1
    payload = json.loads(tool_rows[0].content)
    assert payload["status"] == "interrupted"
    assert payload["capability"] == "terminal"
    assert payload["args"] == {"command": "rm -rf tmp/"}
    assert payload["approval_id"] == "ap-dead"
    assert tool_rows[0].seq == 6
