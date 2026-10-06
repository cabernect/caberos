"""Tests for the scheduler service — heartbeat config, durable schedules,
occurrences, revision pinning, missed/overlap/retry policies, run-now/test-run,
and the lock-safety seams (B29-B33)."""

import uuid
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
import pytest_asyncio
from sqlalchemy import func, select

from agentos import scheduler as svc
from agentos.agent_service import get_active_config, save_agent
from agentos.config_schema import AgentConfig, HeartbeatConfig
from agentos.models.agent import Agent
from agentos.models.schedule import Schedule, ScheduleOccurrence


@pytest_asyncio.fixture
async def test_agent(db):
    """Create a test agent with heartbeat enabled."""
    config = AgentConfig(
        id="hb-test",
        name="Heartbeat Test Agent",
        model={"provider_id": "test", "name": "test-model"},  # type: ignore[arg-type]
        soul="test soul",
        heartbeat=HeartbeatConfig(
            enabled=True,
            interval_minutes=1,
            task_prompt="Check status",
            max_cost_per_heartbeat=0.50,
            consecutive_failure_threshold=3,
        ),
    )
    agent = Agent(id="hb-test", name="Heartbeat Test Agent", enabled=True)
    db.add(agent)
    await db.commit()
    await save_agent(db, config)
    return agent


@pytest.mark.asyncio
async def test_heartbeat_config_fields():
    """HeartbeatConfig has all required fields with defaults."""
    hb = HeartbeatConfig()
    assert hb.enabled is False
    assert hb.interval_minutes == 60
    assert hb.task_prompt == ""
    assert hb.max_cost_per_heartbeat == 0.50
    assert hb.consecutive_failure_threshold == 3


@pytest.mark.asyncio
async def test_heartbeat_config_custom():
    """HeartbeatConfig accepts custom values."""
    hb = HeartbeatConfig(
        enabled=True,
        interval_minutes=30,
        task_prompt="Check inbox",
        max_cost_per_heartbeat=0.25,
        consecutive_failure_threshold=5,
    )
    assert hb.enabled is True
    assert hb.interval_minutes == 30
    assert hb.task_prompt == "Check inbox"
    assert hb.max_cost_per_heartbeat == 0.25
    assert hb.consecutive_failure_threshold == 5


@pytest.mark.asyncio
async def test_heartbeat_config_in_agent_config():
    """AgentConfig includes heartbeat config."""
    config = AgentConfig(
        id="test",
        name="Test",
        model={"provider_id": "p", "name": "m"},  # type: ignore[arg-type]
    )
    assert config.heartbeat.enabled is False
    assert config.heartbeat.interval_minutes == 60


@pytest.mark.asyncio
async def test_heartbeat_persisted_via_save_agent(db, test_agent):
    """Heartbeat config is persisted when saving an agent."""
    from agentos.agent_service import get_active_config

    config = await get_active_config(db, "hb-test")
    assert config is not None
    assert config.heartbeat.enabled is True
    assert config.heartbeat.interval_minutes == 1
    assert config.heartbeat.task_prompt == "Check status"
    assert config.heartbeat.max_cost_per_heartbeat == 0.50
    assert config.heartbeat.consecutive_failure_threshold == 3


@pytest.mark.asyncio
async def test_heartbeat_update_via_save_agent(db, test_agent):
    """Heartbeat config can be updated via save_agent."""
    from agentos.agent_service import get_active_config

    config = await get_active_config(db, "hb-test")
    config.heartbeat.enabled = False
    config.heartbeat.interval_minutes = 120
    await save_agent(db, config)

    # Re-read
    config2 = await get_active_config(db, "hb-test")
    assert config2.heartbeat.enabled is False
    assert config2.heartbeat.interval_minutes == 120


@pytest.mark.asyncio
async def test_heartbeat_projects_managed_schedule(db, test_agent):
    """Enabling heartbeat materializes a managed Schedule (engine migration path)."""
    from agentos.scheduler import get_managed_heartbeat, sync_heartbeat_schedule

    sched = await sync_heartbeat_schedule(db, test_agent.id)
    await db.commit()

    assert sched.managed == "heartbeat"
    assert sched.enabled is True
    assert sched.next_fire_at is not None

    again = await get_managed_heartbeat(db, test_agent.id)
    assert again is not None and again.id == sched.id


@pytest.mark.asyncio
async def test_scheduler_alert_creation(db, test_agent):
    """A schedule past its failure threshold surfaces via get_alerts."""
    from agentos.scheduler import clear_alert, get_alerts, sync_heartbeat_schedule

    sched = await sync_heartbeat_schedule(db, test_agent.id)
    sched.consecutive_failures = 3
    sched.last_error = "Connection refused"
    await db.commit()

    alerts = await get_alerts(db)
    assert len(alerts) == 1
    assert alerts[0].agent_id == test_agent.id
    assert alerts[0].consecutive_failures == 3
    assert alerts[0].last_error == "Connection refused"

    await clear_alert(db, test_agent.id)
    alerts = await get_alerts(db)
    assert len(alerts) == 0


@pytest.mark.asyncio
async def test_heartbeat_state_dataclass():
    """HeartbeatState dataclass has correct defaults."""
    from agentos.scheduler import HeartbeatState

    state = HeartbeatState(agent_id="test")
    assert state.agent_id == "test"
    assert state.last_fired is None
    assert state.last_status is None
    assert state.last_error is None
    assert state.consecutive_failures == 0
    assert state.next_fire is None


# ============================================================================
# Durable schedules (v2) — revisions, occurrences, policies, run-now/test-run,
# and lock-safety regressions.
# ============================================================================

NOW = datetime(2026, 3, 7, 12, 0, 0, tzinfo=UTC)  # fixed anchor for tests


def _cfg(
    trigger: dict,
    task: str = "Do the thing",
    policies: dict | None = None,
    **extra,
) -> dict:
    return {
        "trigger": trigger,
        "task_prompt": task,
        "policies": policies or svc.default_policies(),
        "auto_approve": extra.get("auto_approve", []),
        "limits": {"max_cost": extra.get("max_cost")},
        **{k: v for k, v in extra.items() if k not in ("auto_approve", "max_cost")},
    }


async def _mk_schedule(
    db, agent: Agent, trigger: dict | None = None, policies: dict | None = None, **extra
) -> Schedule:
    cfg = _cfg(trigger or {"kind": "interval", "every_seconds": 300}, policies=policies, **extra)
    sched = Schedule(agent_id=agent.id, name="Test Schedule", enabled=True)
    db.add(sched)
    await db.flush()
    await svc.write_revision(db, sched, cfg)
    return sched


@pytest_asyncio.fixture
async def agent(db):
    a = Agent(id="sched-agent", name="Sched Agent", enabled=True)
    db.add(a)
    config = AgentConfig(
        id="sched-agent",
        name="Sched Agent",
        model={"provider_id": "test", "name": "test-model"},  # type: ignore[arg-type]
    )
    await db.commit()
    await save_agent(db, config)
    return a


# -- trigger math --------------------------------------------------------------


def test_next_fire_once():
    trig = {"kind": "once", "at": "2026-03-10T09:00:00Z"}
    assert svc.next_fire(trig, NOW) == datetime(2026, 3, 10, 9, 0, tzinfo=UTC)
    # already past → exhausted
    assert svc.next_fire(trig, datetime(2026, 3, 11, tzinfo=UTC)) is None


def test_next_fire_interval():
    trig = {"kind": "interval", "every_seconds": 300}
    assert svc.next_fire(trig, NOW) == NOW + timedelta(seconds=300)


def test_next_fire_cron_timezone():
    # 9am America/New_York on weekdays — UTC instant differs across DST
    trig = {"kind": "cron", "cron": "0 9 * * 1-5", "timezone": "America/New_York"}
    # Mar 7 2026 is a Saturday (EST, UTC-5) → next is Mon Mar 9 13:00 UTC
    nxt = svc.next_fire(trig, NOW)
    assert nxt == datetime(2026, 3, 9, 13, 0, tzinfo=UTC)
    # After the Mar 8 spring-forward the zone is EDT (UTC-4) — Mon is still 13:00Z;
    # a day later it stays 13:00Z under EDT.
    nxt2 = svc.next_fire(trig, nxt)
    assert nxt2 == datetime(2026, 3, 10, 13, 0, tzinfo=UTC)


def test_dst_gap_fires_once_at_first_valid_instant():
    """Nonexistent wall time → shifted to first valid instant, executed once."""
    ny = ZoneInfo("America/New_York")
    trig = {"kind": "cron", "cron": "30 2 * * *", "timezone": "America/New_York"}
    fires = [
        datetime.fromisoformat(f).astimezone(ny)
        for f in svc.preview_occurrences(trig, 4, after=datetime(2026, 3, 7, 0, 0, tzinfo=UTC))
    ]
    assert len(fires) == 4
    # 2026-03-08 02:30 does not exist (spring forward) → fires once at 03:00.
    gap_day = [t for t in fires if t.month == 3 and t.day == 8]
    assert len(gap_day) == 1
    assert (gap_day[0].hour, gap_day[0].minute) == (3, 0)


def test_dst_ambiguous_wall_time_fires_once():
    """Fall-back fold: an ambiguous wall time executes once, never twice."""
    ny = ZoneInfo("America/New_York")
    trig = {"kind": "cron", "cron": "30 1 * * *", "timezone": "America/New_York"}
    fires = [
        datetime.fromisoformat(f).astimezone(ny)
        for f in svc.preview_occurrences(trig, 3, after=datetime(2026, 10, 31, 0, 0, tzinfo=UTC))
    ]
    # 2026-11-01 01:30 exists twice (EDT + EST) — only one fire on Nov 1.
    nov1 = [t for t in fires if t.month == 11 and t.day == 1]
    assert len(nov1) == 1
    assert nov1[0].utcoffset() == timedelta(hours=-4)  # first pass (EDT)
    # Next fire resumes on Nov 2 at the ordinary wall time.
    assert fires[2].day == 2 and (fires[2].hour, fires[2].minute) == (1, 30)


def test_preview_occurrences_bounded():
    trig = {"kind": "interval", "every_seconds": 60}
    fires = svc.preview_occurrences(trig, 3, after=NOW)
    assert len(fires) == 3
    instants = [datetime.fromisoformat(f) for f in fires]
    assert instants == sorted(instants)


# -- validation ----------------------------------------------------------------


def test_validate_config():
    assert svc.validate_config(_cfg({"kind": "cron", "cron": "not a cron", "timezone": "UTC"}))
    assert svc.validate_config(
        _cfg({"kind": "cron", "cron": "0 9 * * *", "timezone": "Mars/Olympus"})
    )
    assert svc.validate_config(_cfg({"kind": "interval", "every_seconds": 10}))
    assert svc.validate_config(_cfg({"kind": "interval", "every_seconds": 60}, task=""))
    assert svc.validate_config(
        _cfg(
            {"kind": "interval", "every_seconds": 60},
            policies={"missed": "bogus", "overlap": "skip", "failure": {"mode": "no_retry"}},
        )
    )
    assert svc.validate_config(_cfg({"kind": "interval", "every_seconds": 60}, task="ok")) == []


# -- revisions -----------------------------------------------------------------


@pytest.mark.asyncio
async def test_revisions_are_immutable_and_numbered(db, agent):
    sched = Schedule(agent_id=agent.id, name="S", enabled=True)
    db.add(sched)
    await db.flush()

    rev1 = await svc.write_revision(db, sched, _cfg({"kind": "interval", "every_seconds": 60}))
    rev2 = await svc.write_revision(db, sched, _cfg({"kind": "interval", "every_seconds": 120}))
    assert rev1.revision_number == 1 and rev2.revision_number == 2
    assert sched.current_revision_id == rev2.id
    # rev1 content untouched — active work keeps its captured revision
    assert svc._rev_config(rev1)["trigger"]["every_seconds"] == 60


@pytest.mark.asyncio
async def test_occurrence_pins_its_revision(db, agent):
    """Editing a schedule does not mutate an occurrence's captured revision."""
    sched = Schedule(agent_id=agent.id, name="S", enabled=True)
    db.add(sched)
    await db.flush()
    rev1 = await svc.write_revision(db, sched, _cfg({"kind": "interval", "every_seconds": 60}))
    occ = await svc._record_occurrence(db, sched, rev1, NOW, status="running")
    await svc.write_revision(db, sched, _cfg({"kind": "interval", "every_seconds": 999}))
    await db.commit()
    assert occ.revision_id == rev1.id


# -- missed-run policies --------------------------------------------------------


@pytest.mark.asyncio
async def test_missed_skip_advances_and_records(db, agent):
    sched = await _mk_schedule(
        db, agent, policies={"missed": "skip", "overlap": "skip", "failure": {"mode": "no_retry"}}
    )
    sched.next_fire_at = NOW - timedelta(minutes=30)  # 6 instants missed
    await db.commit()

    await svc._sweep_schedule(db, sched, NOW)

    skipped = (
        (
            await db.execute(
                select(ScheduleOccurrence).where(
                    ScheduleOccurrence.schedule_id == sched.id,
                    ScheduleOccurrence.status == "skipped_missed",
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(skipped) == 1
    assert "missed" in skipped[0].error
    assert sched.next_fire_at > NOW


@pytest.mark.asyncio
async def test_missed_run_once_queues_latest(db, agent):
    sched = await _mk_schedule(db, agent)  # default policies: run_once
    sched.next_fire_at = NOW - timedelta(minutes=30)
    await db.commit()

    await svc._sweep_schedule(db, sched, NOW)

    queued = (
        (
            await db.execute(
                select(ScheduleOccurrence).where(
                    ScheduleOccurrence.schedule_id == sched.id,
                    ScheduleOccurrence.status == "queued",
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(queued) == 1
    assert queued[0].scheduled_for == NOW - timedelta(minutes=5)  # latest missed instant
    assert sched.next_fire_at > NOW


@pytest.mark.asyncio
async def test_missed_catch_up_enqueues_each(db, agent):
    sched = await _mk_schedule(
        db,
        agent,
        policies={"missed": "catch_up", "overlap": "queue", "failure": {"mode": "no_retry"}},
    )
    sched.next_fire_at = NOW - timedelta(minutes=15)  # 3 instants at 300s
    await db.commit()

    await svc._sweep_schedule(db, sched, NOW)

    queued = (
        (
            await db.execute(
                select(ScheduleOccurrence).where(
                    ScheduleOccurrence.schedule_id == sched.id,
                    ScheduleOccurrence.status == "queued",
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(queued) == 3
    assert [o.scheduled_for for o in queued] == sorted(o.scheduled_for for o in queued)


# -- overlap policies -----------------------------------------------------------


async def _running_occ(db, sched) -> ScheduleOccurrence:
    rev = await svc.current_revision(db, sched)
    occ = await svc._record_occurrence(db, sched, rev, NOW, status="running")
    occ.started_at = NOW
    return occ


@pytest.mark.asyncio
async def test_overlap_skip(db, agent):
    sched = await _mk_schedule(
        db, agent, policies={"missed": "skip", "overlap": "skip", "failure": {"mode": "no_retry"}}
    )
    await _running_occ(db, sched)
    sched.next_fire_at = NOW
    await db.commit()

    result = await svc._fire_due(db, sched, NOW)
    assert result is None
    skipped = (
        (
            await db.execute(
                select(ScheduleOccurrence).where(
                    ScheduleOccurrence.schedule_id == sched.id,
                    ScheduleOccurrence.status == "skipped_overlap",
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(skipped) == 1
    assert sched.next_fire_at == NOW + timedelta(seconds=300)


@pytest.mark.asyncio
async def test_overlap_queue(db, agent):
    sched = await _mk_schedule(
        db, agent, policies={"missed": "skip", "overlap": "queue", "failure": {"mode": "no_retry"}}
    )
    await _running_occ(db, sched)
    sched.next_fire_at = NOW
    await db.commit()

    assert await svc._fire_due(db, sched, NOW) is None
    queued = (
        (
            await db.execute(
                select(ScheduleOccurrence).where(
                    ScheduleOccurrence.schedule_id == sched.id,
                    ScheduleOccurrence.status == "queued",
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(queued) == 1


@pytest.mark.asyncio
async def test_overlap_cancel_previous(db, agent):
    sched = await _mk_schedule(
        db,
        agent,
        policies={"missed": "skip", "overlap": "cancel_previous", "failure": {"mode": "no_retry"}},
    )
    old = await _running_occ(db, sched)
    sched.next_fire_at = NOW
    await db.commit()

    new_occ = await svc._fire_due(db, sched, NOW)
    assert new_occ is not None and new_occ.status == "running"
    assert old.status == "cancelled"


@pytest.mark.asyncio
async def test_overlap_allow_parallel(db, agent):
    sched = await _mk_schedule(
        db,
        agent,
        policies={
            "missed": "skip",
            "overlap": "allow_parallel",
            "failure": {"mode": "no_retry"},
        },
    )
    old = await _running_occ(db, sched)
    sched.next_fire_at = NOW
    await db.commit()

    new_occ = await svc._fire_due(db, sched, NOW)
    assert new_occ is not None and new_occ.status == "running"
    assert old.status == "running"  # untouched — still executing


# -- execution + retry ----------------------------------------------------------


@pytest.mark.asyncio
async def test_execute_success_updates_counters(db, agent, monkeypatch):
    sched = await _mk_schedule(db, agent)
    rev = await svc.current_revision(db, sched)
    occ = await svc._record_occurrence(db, sched, rev, NOW, status="running")
    sched.consecutive_failures = 2
    await db.commit()

    async def fake_run(**kwargs):
        return {"run_id": "run-x", "status": "completed", "cost": 0.01, "error": None}

    monkeypatch.setattr(svc, "run_agent", fake_run)
    await svc._execute(occ.id)

    await db.refresh(occ)
    await db.refresh(sched)
    assert occ.status == "completed" and occ.run_id == "run-x"
    assert sched.consecutive_failures == 0
    assert sched.last_status == "completed"


@pytest.mark.asyncio
async def test_bounded_retry_enqueues_next_attempt(db, agent, monkeypatch):
    sched = await _mk_schedule(
        db,
        agent,
        policies={
            "missed": "skip",
            "overlap": "skip",
            "failure": {"mode": "bounded_retry", "max_attempts": 3, "backoff_seconds": 10},
        },
    )
    rev = await svc.current_revision(db, sched)
    occ = await svc._record_occurrence(db, sched, rev, NOW, status="running")
    await db.commit()

    async def fake_fail(**kwargs):
        return {"run_id": "run-f", "status": "failed", "cost": 0, "error": "boom"}

    monkeypatch.setattr(svc, "run_agent", fake_fail)
    await svc._execute(occ.id)

    await db.refresh(occ)
    await db.refresh(sched)
    assert occ.status == "failed"
    assert sched.consecutive_failures == 1

    retries = (
        (
            await db.execute(
                select(ScheduleOccurrence).where(
                    ScheduleOccurrence.schedule_id == sched.id,
                    ScheduleOccurrence.retry_of == occ.id,
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(retries) == 1
    assert retries[0].attempt == 2
    assert retries[0].status == "queued"
    assert retries[0].scheduled_for > occ.finished_at  # backoff


@pytest.mark.asyncio
async def test_bounded_retry_stops_at_max_attempts(db, agent, monkeypatch):
    sched = await _mk_schedule(
        db,
        agent,
        policies={
            "missed": "skip",
            "overlap": "skip",
            "failure": {"mode": "bounded_retry", "max_attempts": 2, "backoff_seconds": 10},
        },
    )
    rev = await svc.current_revision(db, sched)
    occ = await svc._record_occurrence(db, sched, rev, NOW, status="running", attempt=2)
    await db.commit()

    async def fake_fail(**kwargs):
        return {"run_id": "", "status": "failed", "cost": 0, "error": "still broken"}

    monkeypatch.setattr(svc, "run_agent", fake_fail)
    await svc._execute(occ.id)

    retries = (
        (
            await db.execute(
                select(ScheduleOccurrence).where(
                    ScheduleOccurrence.schedule_id == sched.id,
                    ScheduleOccurrence.retry_of == occ.id,
                )
            )
        )
        .scalars()
        .all()
    )
    assert retries == []


@pytest.mark.asyncio
async def test_no_retry_policy_never_retries(db, agent, monkeypatch):
    sched = await _mk_schedule(db, agent)  # default: no_retry
    rev = await svc.current_revision(db, sched)
    occ = await svc._record_occurrence(db, sched, rev, NOW, status="running")
    await db.commit()

    async def fake_fail(**kwargs):
        return {"run_id": "", "status": "failed", "cost": 0, "error": "nope"}

    monkeypatch.setattr(svc, "run_agent", fake_fail)
    await svc._execute(occ.id)
    count = await db.scalar(
        select(func.count())
        .select_from(ScheduleOccurrence)
        .where(ScheduleOccurrence.schedule_id == sched.id)
    )
    assert count == 1


@pytest.mark.asyncio
async def test_run_now_materializes_and_executes(db, agent, monkeypatch):
    sched = await _mk_schedule(db, agent)
    await db.commit()

    async def fake_run(**kwargs):
        assert kwargs["trigger"] == "schedule"
        assert kwargs["new_session"] is True
        assert kwargs["schedule_context"]["revision_id"] == sched.current_revision_id
        return {"run_id": "run-now-1", "status": "completed", "cost": 0, "error": None}

    monkeypatch.setattr(svc, "run_agent", fake_run)
    result = await svc.run_now(sched.id)
    assert result["run_id"] == "run-now-1"
    assert result["status"] == "completed"


# -- startup reconcile ----------------------------------------------------------


@pytest.mark.asyncio
async def test_reconcile_stale_occurrences(db, agent):
    sched = await _mk_schedule(db, agent)
    rev = await svc.current_revision(db, sched)
    occ = await svc._record_occurrence(db, sched, rev, NOW, status="running")
    occ.started_at = NOW
    await db.commit()

    await svc._reconcile_stale_occurrences()

    await db.refresh(occ)
    assert occ.status == "cancelled"
    assert "restarted" in occ.error


@pytest.mark.asyncio
async def test_restart_persistence_no_loss(db, agent):
    """Future next_fire survives a restart — sweep leaves it untouched."""
    sched = await _mk_schedule(db, agent)
    future = NOW + timedelta(minutes=30)
    sched.next_fire_at = future
    await db.commit()

    await svc._sweep_schedule(db, sched, NOW)
    assert sched.next_fire_at == future  # unchanged — nothing missed


# -- heartbeat facade ------------------------------------------------------------


@pytest.mark.asyncio
async def test_heartbeat_revision_tracks_config(db, agent):
    config = await get_active_config(db, agent.id)
    config.heartbeat.enabled = True
    config.heartbeat.interval_minutes = 15
    config.heartbeat.task_prompt = "Ping me"
    await save_agent(db, config)

    sched = await svc.sync_heartbeat_schedule(db, agent.id)
    rev = await svc.current_revision(db, sched)
    cfg = svc._rev_config(rev)
    assert cfg["trigger"]["every_seconds"] == 900
    assert cfg["task_prompt"] == "Ping me"
    assert cfg["limits"]["max_cost"] == config.heartbeat.max_cost_per_heartbeat

    # An interval change writes a new revision, not a mutation
    config.heartbeat.interval_minutes = 30
    await save_agent(db, config)
    await svc.sync_heartbeat_schedule(db, agent.id)
    rev2 = await svc.current_revision(db, sched)
    assert rev2.revision_number == 2
    assert svc._rev_config(rev2)["trigger"]["every_seconds"] == 1800


# -- manifest + auto-approve plumbing --------------------------------------------


@pytest.mark.asyncio
async def test_manifest_pins_schedule_revision(db, agent):
    from agentos.manifest import capture_execution_manifest
    from agentos.models.contact import Contact
    from agentos.models.run import Run
    from agentos.models.session import Session

    contact = Contact(id="c-1", channel="dashboard_chat", bot_id=agent.id, external_user_id="e")
    session = Session(id="s-1", contact_id=contact.id, agent_id=agent.id)
    run = Run(id="r-1", session_id=session.id, contact_id=contact.id, agent_id=agent.id)
    db.add_all([contact, session, run])
    await db.commit()

    manifest = await capture_execution_manifest(
        db,
        run_id=run.id,
        agent_id=agent.id,
        agent_config=None,
        schedule_revision_id="rev-42",
    )
    assert manifest.schedule_revision_id == "rev-42"


@pytest.mark.asyncio
async def test_schedule_auto_approve_skips_prompt(db, workspace, monkeypatch):
    """auto_approve capabilities in a scheduled run execute without the operator prompt."""
    from types import SimpleNamespace

    from agentos.config_schema import CapabilityGrant, ModelConfig
    from agentos.syscall.mediator import SyscallHandler
    from agentos.syscall.protocol import ToolCall

    agent_config = AgentConfig(
        id="a",
        name="A",
        model=ModelConfig(provider_id="test", name="m"),
        capabilities=[CapabilityGrant(name="terminal", require_approval=True)],
    )
    session = SimpleNamespace(id="sess-1", channel=None, contact_id="c1")
    handler = SyscallHandler(db=db, workspace_path=workspace)
    handler._schedule_auto_approve = {"terminal"}

    called = []

    async def _probe(*args, **kwargs):
        called.append(True)
        return False

    monkeypatch.setattr(handler, "_await_approval", _probe)
    result = await handler.mediate(
        call=ToolCall(id="t1", name="terminal", args={"command": "echo hi"}),
        session=session,
        agent_config=agent_config,
        run_id="r-aa",
    )
    assert called == []  # approval prompt never invoked
    assert result.allowed is True


@pytest.mark.asyncio
async def test_schedule_auto_approve_outside_scope_still_prompts(db, workspace, monkeypatch):
    """A capability not in auto_approve still goes through the operator approval."""
    from types import SimpleNamespace

    from agentos.config_schema import CapabilityGrant, ModelConfig
    from agentos.syscall.mediator import SyscallHandler
    from agentos.syscall.protocol import ToolCall

    agent_config = AgentConfig(
        id="a",
        name="A",
        model=ModelConfig(provider_id="test", name="m"),
        capabilities=[CapabilityGrant(name="terminal", require_approval=True)],
    )
    session = SimpleNamespace(id="sess-2", channel=None, contact_id="c1")
    handler = SyscallHandler(db=db, workspace_path=workspace)
    handler._schedule_auto_approve = {"read_file"}  # terminal not covered

    calls = []

    async def _probe(*args, **kwargs):
        calls.append(True)
        return True  # pretend approved

    monkeypatch.setattr(handler, "_await_approval", _probe)
    await handler.mediate(
        call=ToolCall(id="t2", name="terminal", args={"command": "echo hi"}),
        session=session,
        agent_config=agent_config,
        run_id="r-ab",
    )
    assert calls == [True]


# -- W8 defect regressions (B29–B33) -------------------------------------------


@pytest.mark.asyncio
async def test_execute_preserves_materialization_note(db, agent, monkeypatch):
    """run_once's 'N earlier occurrence(s) skipped' note survives a successful
    run — _execute must not clobber occ.error with a None result error (B30)."""
    sched = await _mk_schedule(db, agent)  # default missed=run_once
    sched.next_fire_at = NOW - timedelta(minutes=15)  # 3 missed instants @300s
    await db.commit()

    await svc._sweep_schedule(db, sched, NOW)
    occ = (
        await db.execute(
            select(ScheduleOccurrence).where(ScheduleOccurrence.schedule_id == sched.id)
        )
    ).scalar_one()
    assert "earlier occurrence(s) skipped" in (occ.error or "")

    # Simulate the tick draining the queued row
    occ.status = "running"
    occ.started_at = NOW
    await db.commit()

    async def fake_run(**kwargs):
        return {"run_id": "r1", "status": "completed", "cost": 0, "error": None}

    monkeypatch.setattr(svc, "run_agent", fake_run)
    await svc._execute(occ.id)

    await db.refresh(occ)
    assert occ.status == "completed"
    assert "earlier occurrence(s) skipped" in occ.error  # note preserved


@pytest_asyncio.fixture
async def sched_client(db):
    """HTTP client wired to the test DB with a stub operator."""
    from httpx import ASGITransport, AsyncClient

    from agentos.auth import require_operator
    from agentos.db import get_db
    from agentos.main import app
    from agentos.models.operator import Operator

    async def fake_operator():
        return Operator(id="test-operator", username="test", password_hash="x")

    app.dependency_overrides[require_operator] = fake_operator
    app.dependency_overrides[get_db] = lambda: db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        yield http
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_duplicate_reports_clone_revision(sched_client, agent):
    """duplicate response serializes the clone's own revision_number — not the
    source's (B33)."""
    create = await sched_client.post(
        "/api/schedules",
        json={
            "agent_id": agent.id,
            "name": "dup-src",
            "enabled": False,
            "trigger": {"kind": "interval", "every_seconds": 60},
            "task_prompt": "v1",
        },
    )
    assert create.status_code == 201, create.text
    sid = create.json()["id"]

    # Bump the source to revision 2
    edit = await sched_client.put(
        f"/api/schedules/{sid}",
        json={
            "agent_id": agent.id,
            "name": "dup-src",
            "enabled": False,
            "trigger": {"kind": "interval", "every_seconds": 60},
            "task_prompt": "v2",
        },
    )
    assert edit.status_code == 200 and edit.json()["revision_number"] == 2

    dup = await sched_client.post(f"/api/schedules/{sid}/duplicate")
    assert dup.status_code == 200, dup.text
    body = dup.json()
    assert body["enabled"] is False
    assert body["revision_number"] == 1  # the clone's own rev, not the source's


@pytest.mark.asyncio
async def test_test_run_auto_approves_gated_capability(db, workspace, monkeypatch):
    """_is_test_run: a scripted run never parks on the approval prompt (B29)."""
    from types import SimpleNamespace

    from agentos.config_schema import CapabilityGrant, ModelConfig
    from agentos.syscall.mediator import SyscallHandler
    from agentos.syscall.protocol import ToolCall

    agent_config = AgentConfig(
        id="a",
        name="A",
        model=ModelConfig(provider_id="test", name="m"),
        capabilities=[CapabilityGrant(name="terminal", require_approval=True)],
    )
    session = SimpleNamespace(id="sess-t", channel=None, contact_id="c1")
    handler = SyscallHandler(db=db, workspace_path=workspace)
    handler._is_test_run = True

    called = []

    async def _probe(*args, **kwargs):
        called.append(True)
        return False

    monkeypatch.setattr(handler, "_await_approval", _probe)
    result = await handler.mediate(
        call=ToolCall(id="t-t", name="terminal", args={"command": "echo hi"}),
        session=session,
        agent_config=agent_config,
        run_id="r-t",
    )
    assert called == []  # approval prompt never invoked
    assert result.allowed is True


@pytest.mark.asyncio
async def test_test_run_auto_answers_elicitation(db, workspace, agent):
    """_is_test_run: agent_ask_user resolves immediately with the first option —
    a headless scripted run can never park waiting for a user (B29)."""
    import asyncio as _aio
    from types import SimpleNamespace

    from agentos.config_schema import CapabilityGrant, ModelConfig
    from agentos.models.contact import Contact
    from agentos.models.elicitation import ElicitationRequest
    from agentos.models.run import Run
    from agentos.models.session import Session
    from agentos.syscall.mediator import SyscallHandler
    from agentos.syscall.protocol import ToolCall

    # FK rows for the ElicitationRequest
    db.add(Contact(id="tc", channel="dashboard_chat", bot_id=agent.id, external_user_id="e"))
    db.add(Session(id="tsess", contact_id="tc", agent_id=agent.id))
    db.add(
        Run(
            id="trun",
            session_id="tsess",
            contact_id="tc",
            agent_id=agent.id,
            status="running",
            trigger="schedule",
        )
    )
    await db.commit()

    agent_config = AgentConfig(
        id=agent.id,
        name="A",
        model=ModelConfig(provider_id="test", name="m"),
        capabilities=[CapabilityGrant(name="agent_ask_user", require_approval=False)],
    )
    session = SimpleNamespace(id="tsess", channel=None, contact_id="tc")
    handler = SyscallHandler(db=db, workspace_path=workspace)
    handler._is_test_run = True

    result = await _aio.wait_for(
        handler.mediate(
            call=ToolCall(
                id="t-e",
                name="agent_ask_user",
                args={
                    "question": "How much detail?",
                    "options": [{"label": "Brief overview", "description": "quick"}],
                },
            ),
            session=session,
            agent_config=agent_config,
            run_id="trun",
        ),
        timeout=10,
    )
    assert result.allowed is True
    assert result.output == {"response": "Brief overview"}

    row = (await db.execute(select(ElicitationRequest))).scalar_one()
    assert row.status == "answered"
    assert row.responded_by == "test"


@pytest.mark.asyncio
async def test_run_status_committed_before_harness(db, agent, workspace):
    """B31: run.status='running' must be committed (visible to other sessions)
    before the harness/model call begins — not held in an open write txn."""
    import agentos.db as db_module
    from agentos.harness.loop import RunResult
    from agentos.models.run import Run
    from agentos.pipeline import InboundMessage, Pipeline

    observed: list[str] = []

    class FakeHarness:
        async def run(self, *, run_id, event_emitter=None, **kw):
            # A fresh session sees the committed status — 'running' post-fix,
            # 'pending' if the status write were still uncommitted.
            async with db_module.async_session_factory() as fresh:
                row = await fresh.get(Run, run_id)
                observed.append(row.status if row else "missing")
            return RunResult(final_answer="done", total_turns=1, status="completed")

    pipeline = Pipeline(db=db, harness=FakeHarness())
    msg = InboundMessage(
        channel="schedule",
        bot_id=agent.id,
        external_user_id="system",
        text="probe",
        message_id="m-b31",
        is_test=True,
    )
    run = await pipeline.handle_inbound(msg, trigger="schedule", is_test=True)
    assert run.status == "completed"
    assert observed == ["running"]


@pytest.mark.asyncio
async def test_approval_park_persists_status_and_notification(db, agent, workspace):
    """B32: a tool_call parked at pending_approval flips the run row to
    awaiting_approval and emits an approval_required notification — even when
    no SSE/run-manager transport is attached (scheduled runs)."""
    import agentos.db as db_module
    from agentos.harness.loop import RunResult
    from agentos.models.notification import Notification
    from agentos.models.run import Run
    from agentos.pipeline import InboundMessage, Pipeline

    parked_at: list[str] = []

    class FakeHarness:
        async def run(self, *, run_id, event_emitter=None, **kw):
            await event_emitter(
                "tool_call",
                {
                    "id": "tc-1",
                    "capability": "terminal",
                    "args": {"command": "rm -rf /"},
                    "status": "pending_approval",
                    "approval_id": "ap-1",
                },
            )
            async with db_module.async_session_factory() as fresh:
                row = await fresh.get(Run, run_id)
                parked_at.append(row.status)
            # Simulate the approval resolving — run proceeds to completion
            await event_emitter(
                "tool_call",
                {"id": "tc-1", "capability": "terminal", "status": "denied"},
            )
            return RunResult(final_answer="done", total_turns=1, status="completed")

    pipeline = Pipeline(db=db, harness=FakeHarness())
    msg = InboundMessage(
        channel="schedule",
        bot_id=agent.id,
        external_user_id="system",
        text="probe",
        message_id="m-b32",
        is_test=True,
    )
    run = await pipeline.handle_inbound(msg, trigger="schedule", is_test=True)
    assert run.status == "completed"
    assert parked_at == ["awaiting_approval"]  # committed while parked

    import asyncio as _aio

    await _aio.sleep(0.2)  # let the notification task land
    notif = (
        await db.execute(
            select(Notification).where(
                Notification.notification_type == "approval_required",
                Notification.entity_id == run.id,
            )
        )
    ).scalar_one_or_none()
    assert notif is not None


@pytest.mark.asyncio
async def test_write_lock_free_during_tool_dispatch(tmp_path, monkeypatch):
    """B31 (reopened): no write txn may span tool execution — a sibling
    connection must be able to write while a tool call is in flight, and the
    model_call row must be committed (visible) before dispatch."""
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    import agentos.db as db_module

    # Real file DB — in-memory engines can't exercise cross-connection locking.
    import agentos.models  # noqa: F401  (register all tables on Base.metadata)
    from agentos.config_schema import AgentConfig, CapabilityGrant, ModelConfig
    from agentos.harness.loop import Harness
    from agentos.harness.scripted_model import ScriptedModel, ScriptedResponse
    from agentos.models.base import Base
    from agentos.models.model_call import ModelCall
    from agentos.syscall.mediator import SyscallHandler
    from agentos.syscall.protocol import SyscallResult

    url = f"sqlite+aiosqlite:///{tmp_path}/locktest.db"
    engine = create_async_engine(url)
    async with engine.begin() as conn:
        await conn.execute(text("PRAGMA journal_mode=WAL"))
        await conn.execute(text("PRAGMA busy_timeout=500"))
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(db_module, "async_session_factory", factory)

    async with factory() as db:
        db.add(Agent(id="lock-agent", name="Lock Agent", enabled=True))
        await db.commit()

        probes: list[str] = []
        model_call_seen: list[bool] = []
        run_id = str(uuid.uuid4())

        class ProbeSyscall(SyscallHandler):
            async def mediate(self, *, call, **kw):
                async with factory() as fresh:
                    await fresh.execute(text("PRAGMA busy_timeout=500"))
                    try:
                        await fresh.execute(text("UPDATE agents SET name=name WHERE 1=0"))
                        await fresh.commit()
                        probes.append("wrote")
                    except Exception as e:
                        probes.append(f"locked: {type(e).__name__}")
                    row = (
                        await fresh.execute(select(ModelCall).where(ModelCall.run_id == run_id))
                    ).scalar_one_or_none()
                    model_call_seen.append(row is not None)
                return SyscallResult(output={"stdout": "ok"}, allowed=True)

        config = AgentConfig(
            id="lock-agent",
            name="Lock Free Dispatch Test",
            model=ModelConfig(provider_id="test", name="scripted"),
            capabilities=[CapabilityGrant(name="terminal", require_approval=False)],
        )
        model = ScriptedModel(
            [
                ScriptedResponse(
                    tool_calls=[{"id": "c1", "name": "terminal", "args": {"command": "echo x"}}]
                ),
                ScriptedResponse(content="done"),
            ]
        )
        result = await Harness(model=model).run(
            agent_config=config,
            session=None,
            message="probe",
            syscall_handler=ProbeSyscall(db=db, workspace_path=str(tmp_path)),
            run_id=run_id,
        )
        assert result.status == "completed"
        assert probes == ["wrote"]  # sibling write went through mid-dispatch
        assert model_call_seen == [True]  # model_call row committed pre-dispatch


@pytest.mark.asyncio
async def test_model_call_record_self_heals_on_write_error(db, workspace, agent):
    """B31 (reopened): a failed model_calls write must roll the session back —
    never leave it poisoned for every later statement."""
    from sqlalchemy import text

    from agentos.config_schema import AgentConfig, ModelConfig
    from agentos.harness.loop import Harness
    from agentos.models.contact import Contact
    from agentos.models.run import Run
    from agentos.models.session import Session
    from agentos.syscall.mediator import SyscallHandler

    contact = Contact(id="c-heal", channel="schedule", bot_id=agent.id, external_user_id="sys")
    session_row = Session(id="s-heal", contact_id="c-heal", agent_id=agent.id)
    db.add_all([contact, session_row])
    await db.commit()

    config = AgentConfig(
        id="mc-self-heal",
        name="MC Self Heal Test",
        model=ModelConfig(provider_id="test", name="scripted"),
        capabilities=[],
    )
    handler = SyscallHandler(db=db, workspace_path=workspace)
    harness = Harness(model=None)

    await db.execute(
        text(
            "CREATE TRIGGER fail_mc BEFORE INSERT ON model_calls"
            " BEGIN SELECT RAISE(ABORT, 'database is locked'); END"
        )
    )
    try:
        await harness._record_model_call(
            handler,
            run_id=str(uuid.uuid4()),
            agent_config=config,
            turn=1,
            model_str="scripted",
            streamed=False,
            latency_ms=0,
            status="ok",
        )
        # Session must be usable — the run continues after a lost audit row.
        db.add(
            Run(
                id=str(uuid.uuid4()),
                session_id="s-heal",
                contact_id="c-heal",
                agent_id=agent.id,
                status="running",
                trigger="schedule",
            )
        )
        await db.commit()
    finally:
        await db.execute(text("DROP TRIGGER fail_mc"))
        await db.commit()


@pytest.mark.asyncio
async def test_db_lock_section_commits_on_exit(tmp_path):
    """B31 (write-section seam): `async with db_lock` must close the write
    transaction on exit — a bare flush would leave the file's writer lock
    held across a sibling tool call's whole execution."""
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    import agentos.models  # noqa: F401  (register all tables)
    from agentos.models.base import Base
    from agentos.syscall.mediator import SyscallHandler

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/locksec.db")
    async with engine.begin() as conn:
        await conn.execute(text("PRAGMA journal_mode=WAL"))
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with factory() as db:
        handler = SyscallHandler(db=db, workspace_path=str(tmp_path))
        async with handler._db_lock:
            db.add(Agent(id="sec-agent", name="Sec", enabled=True))
            await db.flush()
        # After the section, the txn is closed — a sibling connection can
        # see and write the row without hitting the write lock.
        async with factory() as probe:
            await probe.execute(text("PRAGMA busy_timeout=500"))
            row = await probe.execute(text("UPDATE agents SET name='Sec2' WHERE id='sec-agent'"))
            await probe.commit()
            assert row.rowcount == 1


@pytest.mark.asyncio
async def test_db_lock_section_rolls_back_on_error(db, tmp_path):
    """B31 (write-section seam): an exception inside `async with db_lock`
    rolls back so the shared session stays usable — no PendingRollbackError
    cascade killing the run."""
    from agentos.syscall.mediator import SyscallHandler

    handler = SyscallHandler(db=db, workspace_path=str(tmp_path))
    with pytest.raises(RuntimeError):
        async with handler._db_lock:
            db.add(Agent(id="doomed-agent", name="D", enabled=True))
            await db.flush()
            raise RuntimeError("boom")

    db.add(Agent(id="survivor-agent", name="S", enabled=True))
    await db.commit()
    assert (await db.scalar(select(Agent.id).where(Agent.id == "doomed-agent"))) is None
    assert (
        await db.scalar(select(Agent.id).where(Agent.id == "survivor-agent"))
    ) == "survivor-agent"
