"""GET /api/home — Today page aggregate (W13)."""

from datetime import UTC, datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient

from agentos.agent_service import create_agent
from agentos.api import home
from agentos.auth import require_operator
from agentos.config_schema import AgentConfig, ModelConfig
from agentos.db import get_db
from agentos.main import app
from agentos.models.agent import Agent
from agentos.models.approval import ApprovalRequest
from agentos.models.channel_config import ChannelConfig
from agentos.models.contact import Contact
from agentos.models.document import Document
from agentos.models.mcp import McpServer
from agentos.models.notification import Notification
from agentos.models.operator import Operator
from agentos.models.provider import Provider
from agentos.models.run import Run
from agentos.models.session import Session
from agentos.models.skill import Skill


@pytest.fixture
async def client(db, monkeypatch):
    # The endpoint counts the process-global live channel registry — pin it
    # so test order/concurrent channel state can't leak in.
    monkeypatch.setattr(home, "list_active_channels", lambda: [])

    async def fake_operator():
        return Operator(id="test-operator", username="test", password_hash="x")

    app.dependency_overrides[require_operator] = fake_operator
    app.dependency_overrides[get_db] = lambda: db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as http:
        yield http
    app.dependency_overrides.clear()


async def _run(db, agent_id, status, session_id="sess-1", **kw):
    db.add(
        Run(
            id=kw.pop("id", f"run-{status}-{agent_id}"),
            session_id=session_id,
            contact_id="contact-1",
            agent_id=agent_id,
            status=status,
            trigger=kw.pop("trigger", "user_message"),
            **kw,
        )
    )


@pytest.fixture
async def seeded(db):
    db.add(Contact(id="contact-1", channel="test", bot_id="a1", external_user_id="u"))
    db.add(Session(id="sess-1", contact_id="contact-1", agent_id="a1"))
    # configured + idle
    await create_agent(
        db,
        AgentConfig(id="a1", name="Caber", model=ModelConfig(provider_id="p1", name="m1")),
    )
    # no model → needs_setup
    await create_agent(db, AgentConfig(id="a2", name="Scout", model=ModelConfig()))
    # paused (disabled)
    db.add(Agent(id="a3", name="Paused", enabled=False))
    db.add(Provider(id="p1", name="OpenAI", type="openai"))
    db.add(McpServer(id="m1", name="Filesystem", transport="stdio", command="fs"))
    db.add(
        ChannelConfig(
            id="c1",
            platform="telegram",
            agent_id="a1",
            encrypted_bot_token="enc",
            enabled=True,
        )
    )
    db.add(Skill(id="s1", name="pdf", scope="global", owner_agent_id=None, status="published"))
    db.add(Skill(id="s2", name="draft", scope="global", owner_agent_id=None, status="draft"))
    db.add(
        Document(
            id="d1",
            agent_id="a1",
            source_path="notes.md",
            storage_path="knowledge/a1/notes.md",
            display_name="notes.md",
            mime_type="text/markdown",
            size_bytes=12,
            content_hash="h1",
        )
    )
    await db.commit()


@pytest.mark.asyncio
async def test_home_empty_install(client):
    resp = await client.get("/api/home")
    assert resp.status_code == 200
    body = resp.json()
    assert body["counts"]["agents_total"] == 0
    assert body["agents"] == []
    assert body["needs_you"] == []
    assert body["happened"] == []
    assert body["egress"]["providers"] == []


@pytest.mark.asyncio
async def test_home_counts_and_agent_status(client, seeded):
    resp = await client.get("/api/home")
    body = resp.json()

    counts = body["counts"]
    assert counts["agents_total"] == 3
    assert counts["agents_running"] == 0
    assert counts["mcps_total"] == 1
    assert counts["mcps_connected"] == 0
    assert counts["skills_published"] == 1
    assert counts["channels_total"] == 1
    assert counts["channels_active"] == 0
    assert counts["vault_documents"] == 1

    status_by_id = {a["id"]: a["status"] for a in body["agents"]}
    assert status_by_id == {"a1": "idle", "a2": "needs_setup", "a3": "paused"}


@pytest.mark.asyncio
async def test_home_running_agent_wins(client, seeded, db):
    await _run(db, "a1", "running")
    await db.commit()

    body = (await client.get("/api/home")).json()
    status_by_id = {a["id"]: a["status"] for a in body["agents"]}
    # running outranks everything — even an unconfigured agent shows its live run
    assert status_by_id["a1"] == "running"
    assert body["counts"]["agents_running"] == 1
    # recency ordering: the live agent leads the list
    assert body["agents"][0]["id"] == "a1"


@pytest.mark.asyncio
async def test_home_needs_you_verifies_pending_approval(client, seeded, db):
    # stale: notification for a run whose approval is already decided
    await _run(db, "a1", "completed", id="run-done")
    db.add(
        ApprovalRequest(
            id="ap-1",
            run_id="run-done",
            capability_name="terminal",
            status="approved",
        )
    )
    db.add(
        Notification(
            id="n-stale",
            notification_type="approval_required",
            severity="warning",
            title="Approval required",
            message="old",
            entity_id="run-done",
            read=False,
        )
    )
    # live: pending approval still waiting
    await _run(db, "a1", "awaiting_approval", id="run-pending")
    db.add(
        ApprovalRequest(
            id="ap-2",
            run_id="run-pending",
            capability_name="terminal",
            status="pending",
        )
    )
    db.add(
        Notification(
            id="n-live",
            notification_type="approval_required",
            severity="warning",
            title="Approval required",
            message="waiting",
            entity_id="run-pending",
            read=False,
        )
    )
    # read notification never surfaces
    db.add(
        Notification(
            id="n-read",
            notification_type="run_failed",
            severity="error",
            title="Run failed",
            message="x",
            read=True,
        )
    )
    await db.commit()

    items = (await client.get("/api/home")).json()["needs_you"]
    ids = {i["notification_id"] for i in items}
    assert ids == {"n-live"}


@pytest.mark.asyncio
async def test_home_happened_groups_terminal_runs(client, seeded, db):
    await _run(db, "a1", "completed", id="r1")
    await _run(db, "a1", "completed", id="r2")
    await _run(db, "a1", "failed", id="r3")
    # test + reflection runs are excluded
    await _run(db, "a1", "completed", id="r4", is_test=True)
    await _run(db, "a1", "completed", id="r5", trigger="reflection")
    await db.commit()

    happened = (await client.get("/api/home")).json()["happened"]
    by_outcome = {(g["agent_id"], g["outcome"]): g["count"] for g in happened}
    assert by_outcome == {("a1", "completed"): 2, ("a1", "failed"): 1}


@pytest.mark.asyncio
async def test_home_happened_buckets_by_operator_local_day(client, seeded, db):
    """Runs straddling UTC midnight are one day in +07 — ?tz= decides."""
    utc_midnight = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    await _run(db, "a1", "completed", id="r-late", started_at=utc_midnight - timedelta(hours=1))
    await _run(db, "a1", "completed", id="r-early", started_at=utc_midnight + timedelta(hours=1))
    await db.commit()

    # UTC (default): two different calendar days → two groups
    groups_utc = (await client.get("/api/home")).json()["happened"]
    assert [g["count"] for g in groups_utc] == [1, 1]

    # Asia/Ho_Chi_Minh: both runs land on the same local day → one group
    groups_vn = (await client.get("/api/home?tz=Asia/Ho_Chi_Minh")).json()["happened"]
    assert len(groups_vn) == 1
    assert groups_vn[0]["count"] == 2


@pytest.mark.asyncio
async def test_home_happened_window_times_serialize_with_offset(client, seeded, db):
    """Column selects bypass the UTC load hook — naive output would make the
    browser render the UTC wall clock as local time."""
    await _run(db, "a1", "completed", id="r-tz")
    await db.commit()

    body = (await client.get("/api/home")).json()
    group = body["happened"][0]
    for key in ("window_start", "window_end"):
        parsed = datetime.fromisoformat(group[key])
        assert parsed.tzinfo is not None, f"{key} serialized naive: {group[key]}"
        assert parsed.utcoffset() == timedelta(0)
    for agent in body["agents"]:
        if agent["last_run_at"]:
            assert datetime.fromisoformat(agent["last_run_at"]).tzinfo is not None


@pytest.mark.asyncio
async def test_stats_time_series_buckets_by_operator_local_day(client, seeded, db):
    """GET /api/stats — daily series uses the operator's calendar, not UTC."""
    utc_midnight = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    await _run(db, "a1", "completed", id="r-late", started_at=utc_midnight - timedelta(hours=1))
    await _run(db, "a1", "completed", id="r-early", started_at=utc_midnight + timedelta(hours=1))
    await db.commit()

    series_utc = (await client.get("/api/stats?days=2")).json()["time_series"]
    utc_runs = {p["date"]: p["runs"] for p in series_utc}
    assert utc_runs[(utc_midnight - timedelta(days=1)).date().isoformat()] == 1
    assert utc_runs[utc_midnight.date().isoformat()] == 1

    series_vn = (await client.get("/api/stats?days=2&tz=Asia/Ho_Chi_Minh")).json()["time_series"]
    vn_runs = {p["date"]: p["runs"] for p in series_vn}
    # +07 shifts both runs onto the same local calendar day
    assert vn_runs.get(utc_midnight.date().isoformat()) == 2


@pytest.mark.asyncio
async def test_agent_activity_sparkline_uses_local_day(client, seeded, db):
    """Sparkline cells are operator-local days — UTC midnight doesn't split."""
    from zoneinfo import ZoneInfo

    hcm = ZoneInfo("Asia/Ho_Chi_Minh")
    # Anchor to *local* midnight: one session each side of it. In +07 they
    # split across yesterday/today; in UTC they share a single day.
    local_midnight = (
        datetime.now(UTC).astimezone(hcm).replace(hour=0, minute=0, second=0, microsecond=0)
    )
    for i, delta in enumerate((-timedelta(hours=2), timedelta(hours=2))):
        db.add(
            Session(
                id=f"sess-edge-{i}",
                contact_id="contact-1",
                agent_id="a1",
                # Columns are naive-UTC storage — bind UTC instants like
                # production does; a non-UTC aware datetime stores its
                # wall-clock and silently drops the offset.
                started_at=(local_midnight + delta).astimezone(UTC),
            )
        )
    await db.commit()

    body_vn = (await client.get("/api/agents/activity?tz=Asia/Ho_Chi_Minh")).json()
    # idx 5 = yesterday, idx 6 = today (+ seeded sess-1, started now)
    assert body_vn["agents"]["a1"]["sessions_7d"] == [0, 0, 0, 0, 0, 1, 2]

    # Same data under UTC: the pair collapses into one cell.
    body_utc = (await client.get("/api/agents/activity")).json()
    assert sum(body_utc["agents"]["a1"]["sessions_7d"]) == 3
    assert max(body_utc["agents"]["a1"]["sessions_7d"]) >= 2


@pytest.mark.asyncio
async def test_agent_activity_rollup(client, seeded, db):
    """GET /api/agents/activity — per-agent sessions, sparkline, running."""
    # a1: 2 sessions this week, one running run
    db.add(
        Session(
            id="sess-2",
            contact_id="contact-1",
            agent_id="a1",
            started_at=datetime.now(UTC) - timedelta(days=3),
        )
    )
    db.add(
        Session(
            id="sess-3",
            contact_id="contact-1",
            agent_id="a1",
            started_at=datetime.now(UTC) - timedelta(days=10),
        )
    )
    await _run(db, "a1", "running")
    await db.commit()

    body = (await client.get("/api/agents/activity")).json()

    per = body["agents"]
    assert per["a1"]["sessions"] == 3  # seeded sess-1 + the two above
    assert sum(per["a1"]["sessions_7d"]) == 2  # 10-day-old session is outside window
    assert per["a1"]["sessions_7d"][3] == 1  # 3 days ago bucket
    assert per["a1"]["running"] == 1
    assert per["a2"]["sessions"] == 0
    assert per["a2"]["sessions_7d"] == [0] * 7
    assert body["sessions_this_week"] == 2  # sess-1 (now) + sess-2 (3d ago)
    assert body["sessions_prev_week"] == 1
    assert body["running_now"] == 1
    assert body["running_names"] == ["Caber"]


@pytest.mark.asyncio
async def test_home_egress_lists_surfaces(client, seeded):
    body = (await client.get("/api/home")).json()
    egress = body["egress"]
    assert egress["providers"] == [{"id": "p1", "name": "OpenAI", "type": "openai"}]
    assert egress["mcps"] == []  # configured but not connected
    assert egress["channels"][0]["platform"] == "telegram"
    assert egress["channels"][0]["connected"] is False
    assert egress["channels"][0]["agent_name"] == "Caber"


async def test_home_active_channel_status(client, seeded, monkeypatch):
    """A live channel in the registry counts as active + connected."""
    monkeypatch.setattr(
        home,
        "list_active_channels",
        lambda: [{"platform": "telegram", "agent_id": "a1", "connected": True}],
    )
    body = (await client.get("/api/home")).json()
    assert body["counts"]["channels_active"] == 1
    ch = next(c for c in body["egress"]["channels"] if c["platform"] == "telegram")
    assert ch["connected"] is True
