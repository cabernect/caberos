"""Session close lifecycle — full-transcript summary + durable learner.

Vertical slice: close_session over multiple terminal runs uses the FULL
session history (no 20-row/500-char clipping), the learner sees every
terminal run's parent rows and clears per-run scratch, failures never mark
the session closed, and concurrent/repeat closes stay idempotent.
"""

import json
import uuid

import pytest
from sqlalchemy import select, text, update

from agentos.config_schema import AgentConfig, Limits, ModelConfig
from agentos.memory.episodic import close_session
from agentos.models.contact import Contact
from agentos.models.memory import MemoryEntry
from agentos.models.run import Message, Run
from agentos.models.session import Session


def _cfg() -> AgentConfig:
    return AgentConfig(
        id="qa-agent",
        name="QA",
        model=ModelConfig(provider_id="p", name="m"),
        soul="s",
        persona="p",
        task="t",
        limits=Limits(),
    )


class FakeAdapter:
    """Queued `complete` responses; records every dispatched input."""

    def __init__(self, outputs):
        self.outputs = list(outputs)
        self.calls: list[dict] = []

    async def get_model_info(self, model):
        return {
            "model_str": "qa/m",
            "resolved_model": {"context_window_tokens": 32768},
        }

    async def complete(self, agent_model=None, messages=None, tools=None):
        self.calls.append({"messages": messages})
        out = self.outputs.pop(0)
        if isinstance(out, BaseException):
            raise out
        from agentos.harness.scripted_model import ScriptedResponse

        return ScriptedResponse(content=out, tokens_in=50, tokens_out=10)


def _fake_registry(monkeypatch, adapter):
    from agentos.providers import ProviderRegistry

    monkeypatch.setattr(ProviderRegistry, "for_model", lambda self, pid: _Return(adapter))


class _Return:
    def __init__(self, adapter):
        self._a = adapter

    async def __aenter__(self):
        return self._a

    async def __aexit__(self, *a):
        pass

    # for_model returns awaitable adapter — support direct await too
    def __await__(self):
        async def _go():
            return self._a

        return _go().__await__()


async def _seed_session(db, *, runs=2, early_prefix="", tail_pad=600):
    """Two completed runs of user/assistant rows; run2's user message puts
    a late correction after `tail_pad` characters of filler."""
    from agentos.agent_service import create_agent

    cfg = _cfg()
    await create_agent(db, cfg)
    db.add(Contact(id="c1", channel="dashboard", bot_id="qa-agent", external_user_id="u1"))
    db.add(Session(id="s1", contact_id="c1", agent_id="qa-agent"))
    await db.commit()

    msgs = []
    for r in range(runs):
        rid = f"run-{r}"
        db.add(
            Run(
                id=rid,
                session_id="s1",
                contact_id="c1",
                agent_id="qa-agent",
                status="completed",
                trigger="user_message",
            )
        )
        u = Message(
            id=f"{rid}-u",
            run_id=rid,
            role="user",
            content=(early_prefix + f"question-{r} " + "z" * tail_pad + f" correction-{r}"),
            seq=0,
        )
        a = Message(id=f"{rid}-a", run_id=rid, role="assistant", content=f"answer-{r}", seq=1)
        db.add_all([u, a])
        msgs += [u, a]
    # Excluded rows: a tool row, a thinking row, a subagent row, a test run.
    db.add_all(
        [
            Message(id="t1", run_id="run-0", role="tool", content="tool out", seq=2),
            Message(
                id="s1t",
                run_id="run-0",
                role="user",
                content="thinking",
                seq=3,
                subagent_id="sub-1",
            ),
            Run(
                id="run-test",
                session_id="s1",
                contact_id="c1",
                agent_id="qa-agent",
                status="completed",
                trigger="user_message",
                is_test=True,
            ),
            Message(id="tt", run_id="run-test", role="user", content="test-only", seq=0),
        ]
    )
    await db.commit()
    session = await db.get(Session, "s1")
    return cfg, session


EXTRACT_OK = json.dumps(
    {
        "memories": [
            {
                "text": "user prefers green tea",
                "kind": "preference",
                "source_ids": ["run-0-u", "run-1-u"],
            }
        ],
        "clarifications": [],
        "core_markdown": None,
        "core_source_ids": [],
    }
)


@pytest.mark.asyncio
async def test_close_summarizes_and_learns_full_session(db, monkeypatch):
    """12 runs / 24 parent rows — the LAST correction lands past row 20;
    both model inputs carry it, plus the real scratch values, and every
    scratch entry clears only after the durable write succeeds."""
    cfg, session = await _seed_session(db, runs=12, tail_pad=80)
    from agentos.memory import recall as _recall

    for rid in ("run-0", "run-1"):
        await _recall.store_snippet(
            db,
            contact_id="c1",
            agent_id="qa-agent",
            key=f"scratch-{rid}",
            value=f"scratch value for {rid}",
            run_id=rid,
        )
    await db.commit()

    adapter = FakeAdapter(["Session summary text.", EXTRACT_OK])
    _fake_registry(monkeypatch, adapter)

    await close_session(db, cfg, session, "c1")

    await db.refresh(session)
    assert session.closed is True
    assert session.status == "closed"
    assert session.summary == "Session summary text."

    assert len(adapter.calls) == 2
    summary_prompt = adapter.calls[0]["messages"][0]["content"]
    extract_prompt = adapter.calls[1]["messages"][0]["content"]
    # Every run's full rows reach both — the past-row-20 correction survives.
    for r in range(12):
        for text_ in (f"correction-{r}", f"answer-{r}", f"question-{r}"):
            assert text_ in summary_prompt, "summary prompt lost " + text_
            assert text_ in extract_prompt, "extract prompt lost " + text_
    assert "scratch value for run-0" in extract_prompt
    assert "scratch value for run-1" in extract_prompt
    assert "tool out" not in summary_prompt
    assert "thinking" not in summary_prompt
    assert "test-only" not in summary_prompt
    # Scratch cleared only after success.
    scratch = (
        (await db.execute(select(MemoryEntry).where(MemoryEntry.run_id.isnot(None))))
        .scalars()
        .all()
    )
    assert scratch == []

    rows = (await db.execute(select(MemoryEntry))).scalars().all()
    durable = [e for e in rows if e.run_id is None]
    assert len(durable) == 1
    assert set(json.loads(durable[0].source_refs)) == {"run-0-u", "run-1-u"}

    # FTS row indexed.
    fts = await db.execute(text("SELECT summary FROM session_summaries_fts WHERE session_id='s1'"))
    assert fts.scalar_one() == "Session summary text."

    # Repeat close — no further model calls, no duplicate entry/FTS row.
    await close_session(db, cfg, session, "c1")
    assert len(adapter.calls) == 2
    durable = [
        e for e in (await db.execute(select(MemoryEntry))).scalars().all() if e.run_id is None
    ]
    assert len(durable) == 1


@pytest.mark.asyncio
async def test_close_failure_leaves_open_with_scratch(db, monkeypatch):
    """Invalid extraction JSON → session stays open; a retry dedups
    durable entries and replaces the FTS row."""
    cfg, session = await _seed_session(db)

    # Seed scratch for both runs — cleared only on a clean close.
    for rid in ("run-0", "run-1"):
        db.add(
            MemoryEntry(
                id=str(uuid.uuid4()),
                run_id=rid,
                agent_id="qa-agent",
                contact_id="c1",
                key=f"scratch-{rid}",
                value=f"scratch for {rid}",
            )
        )
    await db.commit()

    adapter = FakeAdapter(["summary v1", "not-json", "summary v2", EXTRACT_OK])
    _fake_registry(monkeypatch, adapter)

    with pytest.raises(RuntimeError):
        await close_session(db, cfg, session, "c1")
    await db.refresh(session)
    assert session.closed is False
    scratch = (
        (await db.execute(select(MemoryEntry).where(MemoryEntry.run_id.isnot(None))))
        .scalars()
        .all()
    )
    assert len(scratch) == 2  # retained for retry

    # Retry — regenerated summary, FTS replaced, scratch cleared on clean.
    await close_session(db, cfg, session, "c1")
    await db.refresh(session)
    assert session.closed is True
    assert session.summary == "summary v2"
    fts = await db.execute(text("SELECT summary FROM session_summaries_fts WHERE session_id='s1'"))
    assert fts.scalars().all() == ["summary v2"]
    scratch = (
        (await db.execute(select(MemoryEntry).where(MemoryEntry.run_id.isnot(None))))
        .scalars()
        .all()
    )
    assert scratch == []


@pytest.mark.asyncio
async def test_active_run_skips_close(db, monkeypatch):
    cfg, session = await _seed_session(db)
    db.add(
        Run(
            id="live",
            session_id="s1",
            contact_id="c1",
            agent_id="qa-agent",
            status="running",
            trigger="user_message",
        )
    )
    await db.commit()
    adapter = FakeAdapter(["summary", EXTRACT_OK])
    _fake_registry(monkeypatch, adapter)
    await close_session(db, cfg, session, "c1")
    await db.refresh(session)
    assert session.closed is False
    assert adapter.calls == []


@pytest.mark.asyncio
async def test_wrong_scope_rejected(db, monkeypatch):
    cfg, session = await _seed_session(db)
    with pytest.raises(ValueError):
        await close_session(db, cfg, session, "other-contact")


@pytest.mark.asyncio
async def test_empty_session_closes_without_model_calls(db, monkeypatch):
    from agentos.agent_service import create_agent

    cfg = _cfg()
    await create_agent(db, cfg)
    db.add(Contact(id="c1", channel="dashboard", bot_id="qa-agent", external_user_id="u1"))
    db.add(Session(id="empty-s", contact_id="c1", agent_id="qa-agent"))
    await db.commit()
    adapter = FakeAdapter(["summary", EXTRACT_OK])
    _fake_registry(monkeypatch, adapter)
    session = await db.get(Session, "empty-s")
    await close_session(db, cfg, session, "c1")
    await db.refresh(session)
    assert session.closed is True
    assert adapter.calls == []


@pytest.mark.asyncio
async def test_concurrent_closes_run_once(db, monkeypatch):
    """Two overlapping close calls → one lock → a single summary+extract
    pair and one durable entry."""
    import asyncio

    cfg, session = await _seed_session(db)
    adapter = FakeAdapter(["summary", EXTRACT_OK, "summary", EXTRACT_OK])
    _fake_registry(monkeypatch, adapter)
    s2 = await db.get(Session, "s1")
    await asyncio.gather(
        close_session(db, cfg, session, "c1"),
        close_session(db, cfg, s2, "c1"),
    )
    await db.refresh(session)
    assert session.closed is True
    assert len(adapter.calls) == 2
    durable = [
        e for e in (await db.execute(select(MemoryEntry))).scalars().all() if e.run_id is None
    ]
    assert len(durable) == 1


@pytest.mark.asyncio
async def test_reactivation_during_close_stays_open(db, db_engine, monkeypatch):
    """A run that lands mid-close makes the final conditional update miss —
    the session stays open even though the summary/extraction succeeded."""
    from datetime import UTC, datetime

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    cfg, session = await _seed_session(db)
    adapter = FakeAdapter(["summary", EXTRACT_OK])
    _fake_registry(monkeypatch, adapter)

    other = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)()

    # On the LAST model call (extraction), reopen the session under a
    # separate DB session — deterministic interleaving, no sleeps.
    real_complete = adapter.complete

    async def _complete_and_reopen(**kw):
        resp = await real_complete(**kw)
        if not adapter.outputs:  # queue exhausted — the extract call
            async with other:
                other.add(
                    Run(
                        id="sneaky",
                        session_id="s1",
                        contact_id="c1",
                        agent_id="qa-agent",
                        status="running",
                        trigger="user_message",
                    )
                )
                s2 = await other.get(Session, "s1")
                s2.last_activity_at = datetime.now(UTC)
                await other.commit()
        return resp

    adapter.complete = _complete_and_reopen  # type: ignore[method-assign]

    await close_session(db, cfg, session, "c1")
    await db.refresh(session)
    assert session.closed is False


@pytest.mark.asyncio
async def test_overbudget_transcript_sends_no_model_call(db, monkeypatch):
    """Full transcript larger than the resolved input budget → visible
    failure BEFORE dispatch; session stays open."""
    from agentos.config_schema import Limits

    cfg, session = await _seed_session(db, tail_pad=20000)
    # Tiny context window → the full transcript cannot fit.
    cfg.limits = Limits(max_context_tokens=128)
    adapter = FakeAdapter(["summary", EXTRACT_OK])
    _fake_registry(monkeypatch, adapter)
    with pytest.raises(RuntimeError, match="input budget"):
        await close_session(db, cfg, session, "c1")
    await db.refresh(session)
    assert session.closed is False
    assert adapter.calls == []  # refused before dispatch — nothing sent


@pytest.mark.asyncio
async def test_explicit_resume_reopens_closed_session(db, monkeypatch, tmp_path):
    """Resuming a closed session by id reopens it; a later close learns
    from the new rows too."""
    from agentos.agent_service import create_agent
    from agentos.pipeline import InboundMessage, Pipeline
    from agentos.sandbox.workspace import WorkspaceManager

    cfg = _cfg()
    await create_agent(db, cfg)
    db.add(Contact(id="c1", channel="dashboard", bot_id="qa-agent", external_user_id="u1"))
    db.add(
        Session(
            id="s1",
            contact_id="c1",
            agent_id="qa-agent",
            closed=True,
            status="closed",
        )
    )
    await db.commit()

    ws_dir = tmp_path / "ws"
    ws_dir.mkdir(exist_ok=True)
    monkeypatch.setattr(WorkspaceManager, "create_workspace", lambda self, aid: ws_dir)
    from agentos.config import settings

    monkeypatch.setattr(settings, "agent_home_root", tmp_path / "agents")

    from agentos.harness.scripted_model import ScriptedModel, ScriptedResponse

    model = ScriptedModel([ScriptedResponse(content="ok", tokens_in=5, tokens_out=5)])
    monkeypatch.setattr("agentos.providers.ProviderRegistry.for_model", lambda self, pid: model)
    from agentos.harness.loop import Harness

    pipe = Pipeline(db, Harness(model=model))
    await pipe.handle_inbound(
        InboundMessage(
            channel="dashboard",
            bot_id="qa-agent",
            external_user_id="u1",
            text="hello",
            message_id="m1",
            session_id="s1",
        )
    )
    session = await db.get(Session, "s1")
    assert session.closed is False
    assert session.status == "active"


@pytest.mark.asyncio
async def test_normal_run_does_not_trigger_extraction(db, monkeypatch, tmp_path):
    """Pipeline.run no longer fires per-run extraction — close owns it."""
    from agentos.agent_service import create_agent
    from agentos.pipeline import InboundMessage, Pipeline
    from agentos.sandbox.workspace import WorkspaceManager

    cfg = _cfg()
    await create_agent(db, cfg)
    db.add(Contact(id="c1", channel="dashboard", bot_id="qa-agent", external_user_id="u1"))
    db.add(Session(id="s1", contact_id="c1", agent_id="qa-agent"))
    await db.commit()
    ws_dir = tmp_path / "ws"
    ws_dir.mkdir(exist_ok=True)
    monkeypatch.setattr(WorkspaceManager, "create_workspace", lambda self, aid: ws_dir)
    from agentos.config import settings

    monkeypatch.setattr(settings, "agent_home_root", tmp_path / "agents")

    from agentos.harness.scripted_model import ScriptedModel, ScriptedResponse

    model = ScriptedModel([ScriptedResponse(content="done", tokens_in=5, tokens_out=5)])
    monkeypatch.setattr("agentos.providers.ProviderRegistry.for_model", lambda self, pid: model)

    called = []

    async def _extract_spy(*a, **kw):
        called.append(True)
        return {}

    monkeypatch.setattr("agentos.memory.auto_extract.auto_extract_memory", _extract_spy)
    import agentos.pipeline as pipeline_mod

    # Also spy on the module attribute if pipeline re-imports it.
    monkeypatch.setattr(pipeline_mod, "auto_extract_memory", _extract_spy, raising=False)

    from agentos.harness.loop import Harness

    pipe = Pipeline(db, Harness(model=model))
    await pipe.handle_inbound(
        InboundMessage(
            channel="dashboard",
            bot_id="qa-agent",
            external_user_id="u1",
            text="hi",
            message_id="m1",
            session_id="s1",
        )
    )
    import asyncio

    await asyncio.sleep(0.2)  # allow any stray background task to fire
    assert called == []


# --- Closeout regressions -------------------------------------------------


@pytest.mark.asyncio
async def test_two_orm_sessions_close_once(db, db_engine, monkeypatch):
    """Two INDEPENDENT AsyncSessions both holding a closed=False snapshot —
    the lock + a persisted re-read must stop the second call pair."""
    import asyncio

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    cfg, session = await _seed_session(db)
    factory = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as db2:
        await db2.get(Session, "s1")  # preload closed=False in its cache
    adapter = FakeAdapter(["summary", EXTRACT_OK, "summary", EXTRACT_OK])
    _fake_registry(monkeypatch, adapter)
    async with factory() as db2:
        s2 = await db2.get(Session, "s1")
        await asyncio.gather(
            close_session(db, cfg, session, "c1"),
            close_session(db2, cfg, s2, "c1"),
        )
    await db.refresh(session)
    assert session.closed is True
    assert len(adapter.calls) == 2  # one summary + one extraction only
    durable = [
        e for e in (await db.execute(select(MemoryEntry))).scalars().all() if e.run_id is None
    ]
    assert len(durable) == 1


@pytest.mark.asyncio
async def test_same_second_activity_change_stays_open(db, db_engine, monkeypatch):
    """Same-second activity change (different microseconds) plus a newly
    COMPLETED run must still defeat the close — not only active runs."""
    from datetime import datetime

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    cfg, session = await _seed_session(db)
    await db.execute(
        update(Session)
        .where(Session.id == "s1")
        .values(last_activity_at=datetime(2026, 1, 1, 12, 0, 0, 100000))
    )
    await db.commit()
    adapter = FakeAdapter(["summary", EXTRACT_OK])
    _fake_registry(monkeypatch, adapter)

    factory = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)
    real_complete = adapter.complete

    async def _complete_then_shift(**kw):
        resp = await real_complete(**kw)
        if not adapter.outputs:  # extract call — land a mid-flight change
            async with factory() as other:
                other.add(
                    Run(
                        id="late-terminal",
                        session_id="s1",
                        contact_id="c1",
                        agent_id="qa-agent",
                        status="completed",
                        trigger="user_message",
                    )
                )
                other.add(
                    Message(
                        id="late-u",
                        run_id="late-terminal",
                        role="user",
                        content="late correction",
                        seq=0,
                    )
                )
                s2 = await other.get(Session, "s1")
                s2.last_activity_at = datetime(2026, 1, 1, 12, 0, 0, 200000)
                await other.commit()
        return resp

    adapter.complete = _complete_then_shift  # type: ignore[method-assign]

    await close_session(db, cfg, session, "c1")
    await db.refresh(session)
    assert session.closed is False


@pytest.mark.asyncio
async def test_frozen_terminal_run_set_excludes_late_run(db, db_engine, monkeypatch):
    """A run that completes DURING the summary call must not leak into the
    extraction sources or have its scratch deleted — the terminal-run set
    is frozen at close start."""
    from datetime import UTC, datetime

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    cfg, session = await _seed_session(db)
    adapter = FakeAdapter(["summary", EXTRACT_OK])
    _fake_registry(monkeypatch, adapter)

    factory = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)
    real_complete = adapter.complete

    async def _complete_then_new_run(**kw):
        resp = await real_complete(**kw)
        if adapter.outputs:  # during the FIRST (summary) call
            async with factory() as other:
                other.add(
                    Run(
                        id="mid-terminal",
                        session_id="s1",
                        contact_id="c1",
                        agent_id="qa-agent",
                        status="completed",
                        trigger="user_message",
                    )
                )
                other.add(
                    Message(
                        id="mid-u",
                        run_id="mid-terminal",
                        role="user",
                        content="mid-flight message",
                        seq=0,
                    )
                )
                other.add(
                    MemoryEntry(
                        id="mid-scratch",
                        run_id="mid-terminal",
                        agent_id="qa-agent",
                        contact_id="c1",
                        key="mid",
                        value="mid-flight scratch",
                    )
                )
                s2 = await other.get(Session, "s1")
                s2.last_activity_at = datetime.now(UTC)
                await other.commit()
        return resp

    adapter.complete = _complete_then_new_run  # type: ignore[method-assign]

    await close_session(db, cfg, session, "c1")
    extract_prompt = adapter.calls[1]["messages"][0]["content"]
    assert "mid-flight message" not in extract_prompt
    # Mid-flight scratch retained — never snapshotted, never cleared.
    e = await db.get(MemoryEntry, "mid-scratch")
    assert e is not None
    await db.refresh(session)
    assert session.closed is False  # activity changed mid-flight


@pytest.mark.asyncio
async def test_summary_provider_error_leaves_open(db, monkeypatch):
    cfg, session = await _seed_session(db)
    adapter = FakeAdapter([RuntimeError("provider down"), EXTRACT_OK])
    _fake_registry(monkeypatch, adapter)
    with pytest.raises(RuntimeError, match="provider down"):
        await close_session(db, cfg, session, "c1")
    await db.refresh(session)
    assert session.closed is False
    assert adapter.calls == [{"messages": adapter.calls[0]["messages"]}]


@pytest.mark.asyncio
async def test_empty_summary_refuses_close(db, monkeypatch):
    cfg, session = await _seed_session(db)
    adapter = FakeAdapter(["   ", EXTRACT_OK])
    _fake_registry(monkeypatch, adapter)
    with pytest.raises(RuntimeError, match="empty"):
        await close_session(db, cfg, session, "c1")
    await db.refresh(session)
    assert session.closed is False


@pytest.mark.asyncio
async def test_extraction_provider_error_then_retry(db, monkeypatch):
    cfg, session = await _seed_session(db)
    adapter = FakeAdapter(["summary", RuntimeError("extract down"), "summary", EXTRACT_OK])
    _fake_registry(monkeypatch, adapter)
    with pytest.raises(RuntimeError, match="extract down"):
        await close_session(db, cfg, session, "c1")
    await db.refresh(session)
    assert session.closed is False
    await close_session(db, cfg, session, "c1")
    await db.refresh(session)
    assert session.closed is True
    durable = [
        e for e in (await db.execute(select(MemoryEntry))).scalars().all() if e.run_id is None
    ]
    assert len(durable) == 1


@pytest.mark.asyncio
async def test_core_conflict_then_retry_deduped(db, monkeypatch):
    """First close hits a CoreConflict (close fails, originals kept);
    retry publishes nothing twice."""
    cfg, session = await _seed_session(db)
    extract_with_core = json.dumps(
        {
            "memories": [
                {
                    "text": "user prefers green tea",
                    "kind": "preference",
                    "source_ids": ["run-0-u", "run-1-u"],
                }
            ],
            "clarifications": [],
            "core_markdown": "- prefers green tea",
            "core_source_ids": ["run-0-u"],
        }
    )
    adapter = FakeAdapter(["summary", extract_with_core, "summary", extract_with_core])
    _fake_registry(monkeypatch, adapter)

    from agentos.memory import core as core_mod

    real_update = core_mod.update_core
    calls = []

    async def _flaky(*a, **kw):
        calls.append(1)
        if len(calls) == 1:
            raise core_mod.CoreConflict("stale")
        return await real_update(*a, **kw)

    monkeypatch.setattr(core_mod, "update_core", _flaky)
    with pytest.raises(RuntimeError):
        await close_session(db, cfg, session, "c1")
    await db.refresh(session)
    assert session.closed is False

    await close_session(db, cfg, session, "c1")
    await db.refresh(session)
    assert session.closed is True
    durable = [
        e for e in (await db.execute(select(MemoryEntry))).scalars().all() if e.run_id is None
    ]
    assert len(durable) == 1


@pytest.mark.asyncio
async def test_store_snippet_failure_retry_no_dup(db, monkeypatch):
    """Persistence failure inside extraction → close fails; retry must not
    duplicate the durable entry."""
    cfg, session = await _seed_session(db)
    adapter = FakeAdapter(["summary", EXTRACT_OK, "summary", EXTRACT_OK])
    _fake_registry(monkeypatch, adapter)

    from agentos.memory import recall

    real_store = recall.store_snippet
    calls = []

    async def _flaky(*a, **kw):
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("db hiccup")
        return await real_store(*a, **kw)

    monkeypatch.setattr(recall, "store_snippet", _flaky)
    with pytest.raises(RuntimeError, match="db hiccup"):
        await close_session(db, cfg, session, "c1")
    await db.rollback()  # persistence failure may leave a dirty txn
    await db.refresh(session)
    assert session.closed is False

    await close_session(db, cfg, session, "c1")
    await db.refresh(session)
    assert session.closed is True
    durable = [
        e for e in (await db.execute(select(MemoryEntry))).scalars().all() if e.run_id is None
    ]
    assert len(durable) == 1


# --- Caller isolation regressions ------------------------------------------

EMPTY_EXTRACT = json.dumps(
    {"memories": [], "clarifications": [], "core_markdown": None, "core_source_ids": []}
)


async def _seed_idle_session(db, sid: str, with_messages: bool = True, minutes_ago=None):
    """One idle session owned by qa-agent/c1 (default: activity years ago)."""
    from datetime import UTC, datetime, timedelta

    last = (
        datetime(2020, 1, 1, tzinfo=UTC)
        if minutes_ago is None
        else datetime.now(UTC) - timedelta(minutes=minutes_ago)
    )
    db.add(
        Session(
            id=sid,
            contact_id="c1",
            agent_id="qa-agent",
            last_activity_at=last,
        )
    )
    if with_messages:
        db.add(
            Run(
                id=f"{sid}-run",
                session_id=sid,
                contact_id="c1",
                agent_id="qa-agent",
                status="completed",
                trigger="user_message",
            )
        )
        db.add(
            Message(
                id=f"{sid}-u",
                run_id=f"{sid}-run",
                role="user",
                content=f"question from {sid}",
                seq=0,
            )
        )
        db.add(
            Message(
                id=f"{sid}-a",
                run_id=f"{sid}-run",
                role="assistant",
                content=f"answer for {sid}",
                seq=1,
            )
        )
    await db.commit()


@pytest.mark.asyncio
async def test_lazy_close_failure_does_not_starve_or_break_run(
    db, db_engine, monkeypatch, tmp_path
):
    """A failing close attempt (provider error) must not abort later idle
    sessions, must not rollback self.db, and must not break the new run."""

    from agentos.agent_service import create_agent
    from agentos.models.contact import Contact
    from agentos.pipeline import InboundMessage, Pipeline

    cfg = _cfg()
    await create_agent(db, cfg)
    db.add(Contact(id="c1", channel="dashboard_chat", bot_id="qa-agent", external_user_id="u1"))
    await db.commit()
    await _seed_idle_session(db, "old-fail")
    await _seed_idle_session(db, "old-ok")

    # Foreground harness — scripted, no provider.
    from agentos.harness.loop import Harness
    from agentos.harness.scripted_model import ScriptedModel, ScriptedResponse

    model = ScriptedModel([ScriptedResponse(content="done", tokens_in=5, tokens_out=5)])

    # Close calls hit FakeAdapter: first close attempt (old-fail) summary
    # raises; second (old-ok) gets summary + empty-valid extraction.
    adapter = FakeAdapter([RuntimeError("provider down"), "summary for old-ok", EMPTY_EXTRACT])
    _fake_registry(monkeypatch, adapter)

    # Route close-time provider lookups to FakeAdapter but leave the
    # scripted harness model alone.
    from agentos.providers import ProviderRegistry

    def _fm(self, pid):
        return _Return(adapter)

    monkeypatch.setattr(ProviderRegistry, "for_model", _fm)

    from agentos.config import settings

    monkeypatch.setattr(settings, "agent_home_root", tmp_path / "agents")
    from agentos.sandbox.workspace import WorkspaceManager

    monkeypatch.setattr(WorkspaceManager, "create_workspace", lambda self, aid: tmp_path / "ws")
    (tmp_path / "ws").mkdir(exist_ok=True)

    # Lazy closes spawn background tasks — the in-memory test engine shares
    # ONE connection across sessions, so concurrent tasks would corrupt
    # each other's transactions (a production file DB uses WAL + busy
    # timeout instead). Defer the spawn and run the same coroutines
    # sequentially after the run lands.
    pending = []
    from agentos.memory import episodic as _ep

    monkeypatch.setattr(_ep, "spawn_close_task", lambda coro: pending.append(coro))

    pipe = Pipeline(db, Harness(model=model))
    run = await pipe.handle_inbound(
        InboundMessage(
            channel="dashboard_chat",
            bot_id="qa-agent",
            external_user_id="u1",
            text="hello",
            message_id="m-new",
            new_session=True,
        ),
        trigger="user_message",
        is_test=True,
    )
    assert run.status == "completed"
    while pending:
        await pending.pop(0)

    old_fail = await db.get(Session, "old-fail", populate_existing=True)
    old_ok = await db.get(Session, "old-ok", populate_existing=True)
    assert old_fail.closed is False  # failed close stays open
    assert old_ok.closed is True  # a later session still closes


@pytest.mark.asyncio
async def test_sweeper_failure_does_not_abort_pass(db, db_engine, monkeypatch):
    """_sweep_once: one failed close doesn't starve the next session."""
    import agentos.main as main_mod
    from agentos.agent_service import create_agent

    cfg = _cfg()
    await create_agent(db, cfg)
    db.add(Contact(id="c1", channel="dashboard_chat", bot_id="qa-agent", external_user_id="u1"))
    await db.commit()
    await _seed_idle_session(db, "sw-fail")
    await _seed_idle_session(db, "sw-ok")

    adapter = FakeAdapter([RuntimeError("provider down"), "summary for sw-ok", EMPTY_EXTRACT])
    _fake_registry(monkeypatch, adapter)

    wait_seconds = await main_mod._sweep_once()
    assert isinstance(wait_seconds, float) and wait_seconds > 0

    async with db_engine.connect() as conn:
        sw_fail = (
            await conn.execute(text("SELECT closed FROM sessions WHERE id='sw-fail'"))
        ).scalar()
        sw_ok = (await conn.execute(text("SELECT closed FROM sessions WHERE id='sw-ok'"))).scalar()
    assert sw_fail == 0 or sw_fail is False
    assert sw_ok == 1 or sw_ok is True


# --- Activity events + idle-timeout wiring ---------------------------------


@pytest.mark.asyncio
async def test_close_emits_activity_events_and_flag(db, monkeypatch):
    """A subscribed dashboard sees started→finished for one close attempt,
    and the `learning` flag is visible while the model calls run."""
    from agentos import session_activity
    from agentos.memory.episodic import closing_session_ids

    cfg, session = await _seed_session(db)
    adapter = FakeAdapter(["summary", EXTRACT_OK])
    _fake_registry(monkeypatch, adapter)

    flag_during_calls = []
    real_complete = adapter.complete

    async def _spy(**kw):
        flag_during_calls.append("s1" in closing_session_ids())
        return await real_complete(**kw)

    adapter.complete = _spy  # type: ignore[method-assign]

    queue = session_activity.subscribe()
    try:
        await close_session(db, cfg, session, "c1")
        events = []
        while not queue.empty():
            events.append(queue.get_nowait())
    finally:
        session_activity.unsubscribe(queue)

    assert flag_during_calls == [True, True]
    assert [e["phase"] for e in events] == ["started", "finished"]
    assert all(e["type"] == "session_activity" for e in events)
    assert all(e["session_id"] == "s1" and e["agent_id"] == "qa-agent" for e in events)
    assert "s1" not in closing_session_ids()  # cleared after close


@pytest.mark.asyncio
async def test_close_failure_emits_failed(db, monkeypatch):
    from agentos import session_activity

    cfg, session = await _seed_session(db)
    adapter = FakeAdapter([RuntimeError("provider down")])
    _fake_registry(monkeypatch, adapter)

    queue = session_activity.subscribe()
    try:
        with pytest.raises(RuntimeError):
            await close_session(db, cfg, session, "c1")
        events = []
        while not queue.empty():
            events.append(queue.get_nowait())
    finally:
        session_activity.unsubscribe(queue)
    assert [e["phase"] for e in events] == ["started", "failed"]


async def _run_one_sweep(db_engine, monkeypatch):
    """Drive one sweep pass — _sweep_once is the schedulable unit the
    deadline-driven loop calls each wake."""
    import agentos.main as main_mod

    await main_mod._sweep_once()


@pytest.mark.asyncio
async def test_sweeper_respects_agent_idle_timeout(db, db_engine, monkeypatch):
    """Agent's configured limit governs: a 40-min-idle session does NOT close
    while limits.session_idle_timeout_min is 120 — no model calls fire."""
    from agentos.agent_service import create_agent

    cfg = _cfg()
    cfg.limits = Limits(session_idle_timeout_min=120)
    await create_agent(db, cfg)
    db.add(Contact(id="c1", channel="dashboard_chat", bot_id="qa-agent", external_user_id="u1"))
    await db.commit()
    await _seed_idle_session(db, "under-limit", minutes_ago=40)

    adapter = FakeAdapter(["summary", EMPTY_EXTRACT])
    _fake_registry(monkeypatch, adapter)
    await _run_one_sweep(db_engine, monkeypatch)

    async with db_engine.connect() as conn:
        closed = (
            await conn.execute(text("SELECT closed FROM sessions WHERE id='under-limit'"))
        ).scalar()
    assert closed == 0 or closed is False
    assert adapter.calls == []


@pytest.mark.asyncio
async def test_sweeper_agent_timeout_wins_over_session_column(db, db_engine, monkeypatch):
    """The legacy per-session column is ignored: idle_timeout_min=9999 must
    not protect a session past the agent's configured 10-minute limit."""
    from agentos.agent_service import create_agent

    cfg = _cfg()
    cfg.limits = Limits(session_idle_timeout_min=10)
    await create_agent(db, cfg)
    db.add(Contact(id="c1", channel="dashboard_chat", bot_id="qa-agent", external_user_id="u1"))
    await db.commit()
    await _seed_idle_session(db, "col-override", minutes_ago=40)
    await db.execute(
        update(Session).where(Session.id == "col-override").values(idle_timeout_min=9999)
    )
    await db.commit()

    adapter = FakeAdapter(["summary", EMPTY_EXTRACT])
    _fake_registry(monkeypatch, adapter)
    await _run_one_sweep(db_engine, monkeypatch)

    async with db_engine.connect() as conn:
        closed = (
            await conn.execute(text("SELECT closed FROM sessions WHERE id='col-override'"))
        ).scalar()
    assert closed == 1 or closed is True
    assert len(adapter.calls) == 2  # summary + extraction ran


@pytest.mark.asyncio
async def test_close_ledger_rows_link_session_and_last_run(db, monkeypatch):
    """Close-time summary + extract receipts carry session_id and the latest
    frozen run id — surfacing them in that run's trace instead of nowhere."""
    from agentos.models.model_call import ModelCall

    cfg, session = await _seed_session(db)
    adapter = FakeAdapter(["summary", EXTRACT_OK])
    _fake_registry(monkeypatch, adapter)
    await close_session(db, cfg, session, "c1")

    rows = (
        (
            await db.execute(
                select(ModelCall).where(ModelCall.session_id == "s1").order_by(ModelCall.created_at)
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 2
    assert {r.kind for r in rows} == {"chat", "extract"}
    # frozen_run_ids orders by started_at + id — run-1 is the latest.
    assert all(r.run_id == "run-1" for r in rows)


def _extract_payload(calls):
    """Parse the JSON payload out of the last adapter call's request text."""
    content = calls[-1]["messages"][0]["content"]
    return json.loads(content[content.index('{"messages"') :])


async def _reopen_with_run(db, rid="run-2"):
    """Reopen session s1 and append a new terminal run with u/a rows."""
    db.add(
        Run(
            id=rid,
            session_id="s1",
            contact_id="c1",
            agent_id="qa-agent",
            status="completed",
            trigger="user_message",
        )
    )
    db.add_all(
        [
            Message(id=f"{rid}-u", run_id=rid, role="user", content="actually I have a cat", seq=0),
            Message(id=f"{rid}-a", run_id=rid, role="assistant", content="nice", seq=1),
        ]
    )
    await db.execute(update(Session).where(Session.id == "s1").values(closed=False))
    await db.commit()


@pytest.mark.asyncio
async def test_close_marks_learned_coverage(db, monkeypatch):
    """A clean close pins every presented parent message id — the
    incremental-learning watermark."""
    cfg, session = await _seed_session(db)
    adapter = FakeAdapter(["summary", EXTRACT_OK])
    _fake_registry(monkeypatch, adapter)
    await close_session(db, cfg, session, "c1")

    s = await db.get(Session, "s1", populate_existing=True)
    cov = set(json.loads(s.learned_coverage))
    assert {"run-0-u", "run-0-a", "run-1-u", "run-1-a"} <= cov
    # Tool/subagent rows were never presented — they stay uncovered-forever.
    assert "t1" not in cov and "s1t" not in cov


@pytest.mark.asyncio
async def test_second_close_learns_only_new_messages(db, monkeypatch):
    """Re-close feeds only the uncovered tail; covered history arrives as
    non-citable context_tail, stored entries ride as prior_entries."""
    cfg, session = await _seed_session(db)
    adapter = FakeAdapter(["summary", EXTRACT_OK])
    _fake_registry(monkeypatch, adapter)
    await close_session(db, cfg, session, "c1")
    await _reopen_with_run(db)

    extract_v2 = json.dumps(
        {
            "memories": [{"text": "user has a cat", "kind": "fact", "source_ids": ["run-2-u"]}],
            "clarifications": [],
            "core_markdown": None,
            "core_source_ids": [],
        }
    )
    adapter.outputs = ["summary", extract_v2]
    await close_session(db, cfg, await db.get(Session, "s1"), "c1")

    payload = _extract_payload(adapter.calls)
    assert [m["id"] for m in payload["messages"]] == ["run-2-u", "run-2-a"]
    assert [m["id"] for m in payload["context_tail"]] == [
        "run-0-u",
        "run-0-a",
        "run-1-u",
        "run-1-a",
    ]
    assert payload["prior_entries"]
    assert "green tea" in payload["prior_entries"][0]["value"]

    s = await db.get(Session, "s1", populate_existing=True)
    cov = set(json.loads(s.learned_coverage))
    assert {"run-0-u", "run-1-u", "run-2-u", "run-2-a"} <= cov


@pytest.mark.asyncio
async def test_failed_second_close_preserves_coverage(db, monkeypatch):
    """A failed re-close never extends the watermark — the retry presents
    the same uncovered set."""
    cfg, session = await _seed_session(db)
    adapter = FakeAdapter(["summary", EXTRACT_OK])
    _fake_registry(monkeypatch, adapter)
    await close_session(db, cfg, session, "c1")
    before = (await db.get(Session, "s1", populate_existing=True)).learned_coverage

    await _reopen_with_run(db)
    adapter.outputs = ["summary", RuntimeError("extract down")]
    with pytest.raises(RuntimeError, match="extract down"):
        await close_session(db, cfg, await db.get(Session, "s1"), "c1")

    after = (await db.get(Session, "s1", populate_existing=True)).learned_coverage
    assert after == before


@pytest.mark.asyncio
async def test_fully_learned_close_skips_extraction(db, monkeypatch):
    """With nothing uncovered and no scratch, close runs only the summary
    call — the extract call never fires."""
    cfg, session = await _seed_session(db)
    adapter = FakeAdapter(["summary", EXTRACT_OK])
    _fake_registry(monkeypatch, adapter)
    await close_session(db, cfg, session, "c1")
    assert len(adapter.calls) == 2

    # Reopen without any new messages. One summary output is all the close
    # may consume — an extract call would pop from an empty list.
    await db.execute(update(Session).where(Session.id == "s1").values(closed=False))
    await db.commit()
    adapter.outputs = ["summary"]
    await close_session(db, cfg, await db.get(Session, "s1"), "c1")

    assert len(adapter.calls) == 3  # summary only — no extract call


@pytest.mark.asyncio
async def test_close_summary_uses_rollup_plus_uncovered_tail(db, monkeypatch):
    """A mid-run compaction rollup stands in for covered rows in the close
    summary input — only the uncovered tail ships verbatim, so the input
    stays bounded on a session that outgrew its context window."""
    cfg, session = await _seed_session(db, runs=2, tail_pad=40)
    session.conversation_summary = "The pair discussed the opening topic."
    session.conversation_summary_coverage = json.dumps(["run-0-u", "run-0-a"])
    session.conversation_summary_version = 1
    session.conversation_summary_coverage_known = True
    await db.commit()

    adapter = FakeAdapter(["Session summary text.", EXTRACT_OK])
    _fake_registry(monkeypatch, adapter)

    await close_session(db, cfg, session, "c1")

    await db.refresh(session)
    assert session.closed is True
    assert session.summary == "Session summary text."

    summary_prompt = adapter.calls[0]["messages"][0]["content"]
    assert "Earlier conversation summary:" in summary_prompt
    assert "The pair discussed the opening topic." in summary_prompt
    assert "Later messages:" in summary_prompt
    # Uncovered tail ships verbatim…
    for text_ in ("correction-1", "answer-1", "question-1"):
        assert text_ in summary_prompt, "summary prompt lost " + text_
    # …covered rows do not — the rollup stands in for them.
    for text_ in ("correction-0", "answer-0", "question-0"):
        assert text_ not in summary_prompt, "covered row leaked: " + text_
    # learned_coverage is a separate watermark — still NULL, so the learner
    # sees the full transcript including the rollup-covered rows.
    extract_prompt = adapter.calls[1]["messages"][0]["content"]
    for text_ in ("correction-0", "answer-0", "question-0"):
        assert text_ in extract_prompt, "extract prompt lost " + text_
