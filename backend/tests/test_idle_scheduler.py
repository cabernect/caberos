"""Deadline-driven idle scheduler — wake/poke wiring, deadline math, and
the retry pass for reflections skipped while the agent was busy."""

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from agentos.config_schema import AgentConfig, Limits, ModelConfig
from agentos.models.contact import Contact
from agentos.models.run import Message, Run
from agentos.models.session import Session


def _cfg(timeout_min: int = 30) -> AgentConfig:
    cfg = AgentConfig(
        id="qa-agent",
        name="QA",
        model=ModelConfig(provider_id="p", name="m"),
        limits=Limits(),
    )
    cfg.limits.session_idle_timeout_min = timeout_min
    return cfg


async def _seed_agent(db, timeout_min: int = 30) -> AgentConfig:
    from agentos.agent_service import create_agent

    cfg = _cfg(timeout_min)
    await create_agent(db, cfg)
    db.add(Contact(id="c1", channel="dashboard_chat", bot_id="qa-agent", external_user_id="u1"))
    await db.commit()
    return cfg


def _open_session(sid: str, *, minutes_ago: float) -> Session:
    return Session(
        id=sid,
        contact_id="c1",
        agent_id="qa-agent",
        last_activity_at=datetime.now(UTC) - timedelta(minutes=minutes_ago),
    )


@pytest.mark.asyncio
async def test_poke_wakes_registered_event(db):
    from agentos.memory import episodic

    ev = asyncio.Event()
    episodic.register_session_wake(ev)
    try:
        episodic.poke_session_sweeper()
        assert ev.is_set()
    finally:
        episodic.register_session_wake(None)
    # Unregistered — a poke is a no-op, not an error.
    episodic.poke_session_sweeper()


@pytest.mark.asyncio
async def test_sweep_once_returns_next_deadline(db, monkeypatch):
    """A not-yet-due session stays open and its remaining time drives the
    sleep; an overdue session is closed in the same pass."""
    import agentos.main as main_mod
    from tests.test_session_close_learning import EMPTY_EXTRACT, FakeAdapter, _fake_registry

    await _seed_agent(db, timeout_min=30)
    db.add(_open_session("s-due", minutes_ago=60))
    db.add(_open_session("s-fresh", minutes_ago=29))
    db.add(
        Run(
            id="r1",
            session_id="s-due",
            contact_id="c1",
            agent_id="qa-agent",
            status="completed",
            trigger="user_message",
        )
    )
    db.add_all(
        [
            Message(id="m1", run_id="r1", role="user", content="q", seq=0),
            Message(id="m2", run_id="r1", role="assistant", content="a", seq=1),
        ]
    )
    await db.commit()

    _fake_registry(monkeypatch, FakeAdapter(["summary", EMPTY_EXTRACT]))
    wait_seconds = await main_mod._sweep_once()

    due = await db.get(Session, "s-due", populate_existing=True)
    fresh = await db.get(Session, "s-fresh", populate_existing=True)
    assert due.closed is True
    assert fresh.closed is False
    # Next wake lands at the fresh session's deadline (~1 min out).
    assert main_mod._SWEEP_MIN_SLEEP_SECONDS < wait_seconds <= 60


@pytest.mark.asyncio
async def test_busy_session_is_never_due(db, monkeypatch):
    """A session with an in-flight run is not idle no matter its age — the
    sweep must not even attempt a close on it (no model calls, stays open).
    Its real deadline becomes run-end + timeout via the run-finish poke."""
    import agentos.main as main_mod
    from agentos.memory.episodic import find_idle_sessions
    from tests.test_session_close_learning import FakeAdapter, _fake_registry

    await _seed_agent(db, timeout_min=30)
    db.add(_open_session("s-busy", minutes_ago=120))
    db.add(
        Run(
            id="r-live",
            session_id="s-busy",
            contact_id="c1",
            agent_id="qa-agent",
            status="running",
            trigger="user_message",
        )
    )
    await db.commit()

    assert [s.id for s in await find_idle_sessions(db)] == []
    adapter = FakeAdapter([])
    _fake_registry(monkeypatch, adapter)
    wait_seconds = await main_mod._sweep_once()

    assert adapter.calls == []
    session = await db.get(Session, "s-busy", populate_existing=True)
    assert session.closed is False
    assert wait_seconds == main_mod._SWEEP_FALLBACK_SECONDS


@pytest.mark.asyncio
async def test_sweep_once_no_sessions_sleeps_fallback(db):
    import agentos.main as main_mod

    wait_seconds = await main_mod._sweep_once()
    assert wait_seconds == main_mod._SWEEP_FALLBACK_SECONDS


@pytest.mark.asyncio
async def test_retry_pending_reflections_skips_busy_agent(db, tmp_path, monkeypatch):
    """Closed session + a running non-reflection run → the retry pass
    leaves the fingerprint unclaimed (no SkillReflection row)."""
    import agentos.main as main_mod
    from agentos.harness.scripted_model import ScriptedModel, ScriptedResponse
    from agentos.models.skill_reflection import SkillReflection
    from agentos.providers import ProviderRegistry

    await _seed_agent(db)
    db.add(Session(id="s1", contact_id="c1", agent_id="qa-agent", closed=True))
    db.add(
        Run(
            id="r1",
            session_id="s1",
            contact_id="c1",
            agent_id="qa-agent",
            status="completed",
            trigger="user_message",
        )
    )
    db.add_all(
        [
            Message(id="m1", run_id="r1", role="user", content="use pdf", seq=0),
            Message(id="m2", run_id="r1", role="assistant", content="ok", seq=1),
        ]
    )
    # The agent is mid-task — a running run in another session.
    db.add(
        Run(
            id="r-live",
            session_id="s1",
            contact_id="c1",
            agent_id="qa-agent",
            status="running",
            trigger="user_message",
        )
    )
    await db.commit()

    model = ScriptedModel([ScriptedResponse(content="no change")])
    monkeypatch.setattr(ProviderRegistry, "for_model", lambda self, _pid: _Awaitable(model))
    from agentos.config import settings

    monkeypatch.setattr(settings, "workspace_root", tmp_path / "ws")

    await main_mod._retry_pending_reflections()
    assert list(await db.scalars(select(SkillReflection))) == []
    assert model.seen_calls == []


class _Awaitable:
    def __init__(self, model):
        self._m = model

    def __await__(self):
        async def _go():
            return self._m

        return _go().__await__()


@pytest.mark.asyncio
async def test_retry_pending_reflections_runs_when_idle(db, tmp_path, monkeypatch):
    """Agent idle → the retry pass claims the closed session's fingerprint
    and completes the reflection."""
    import agentos.main as main_mod
    from agentos.harness.scripted_model import ScriptedModel, ScriptedResponse
    from agentos.models.skill_reflection import SkillReflection
    from agentos.providers import ProviderRegistry

    await _seed_agent(db)
    db.add(Session(id="s1", contact_id="c1", agent_id="qa-agent", closed=True))
    db.add(
        Run(
            id="r1",
            session_id="s1",
            contact_id="c1",
            agent_id="qa-agent",
            status="completed",
            trigger="user_message",
        )
    )
    db.add_all(
        [
            Message(id="m1", run_id="r1", role="user", content="use pdf", seq=0),
            Message(id="m2", run_id="r1", role="assistant", content="ok", seq=1),
        ]
    )
    await db.commit()

    model = ScriptedModel([ScriptedResponse(content="nothing reusable")])
    monkeypatch.setattr(ProviderRegistry, "for_model", lambda self, _pid: _Awaitable(model))
    from agentos.config import settings

    monkeypatch.setattr(settings, "workspace_root", tmp_path / "ws")
    # evolve must resolve — provide it as a live agent-local skill.
    live = tmp_path / "ws" / "qa-agent" / "skills" / "evolve"
    live.mkdir(parents=True)
    (live / "SKILL.md").write_text(
        "---\nname: evolve\ndescription: ev\nlicense: Apache-2.0\n"
        "compatibility: c\nallowed-tools: read_file\n---\nPROC",
        encoding="utf-8",
    )
    await main_mod._retry_pending_reflections()

    refls = list(await db.scalars(select(SkillReflection)))
    assert len(refls) == 1
    assert refls[0].session_id == "s1" and refls[0].outcome == "no_change"
    # Claimed — a second pass exits early without another model call.
    before = len(model.seen_calls)
    await main_mod._retry_pending_reflections()
    assert len(model.seen_calls) == before
