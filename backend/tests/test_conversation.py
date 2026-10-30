"""Conversation continuity — uncovered originals + coverage, deterministic order.

Covers the conversation-memory slice: a session replays ALL uncovered
parent-level records (no LIMIT cut), a stored summary renders exactly once,
and failed summarization never advances coverage or version.
"""

import json
import uuid
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select

from agentos.agent_service import create_agent
from agentos.config_schema import AgentConfig, CapabilityGrant, CompactionConfig, ModelConfig
from agentos.harness.conversation import Conversation
from agentos.harness.loop import Harness
from agentos.harness.scripted_model import ScriptedModel, ScriptedResponse
from agentos.models.run import Message
from agentos.models.session import Session
from agentos.pipeline import InboundMessage, Pipeline


def _agent_caps(*names: str) -> list[CapabilityGrant]:
    return [CapabilityGrant(name=n, require_approval=False) for n in names]


async def _make_agent(db, agent_id="conv-test", **kw):
    config = AgentConfig(
        id=agent_id,
        name="Conversation Test",
        model=ModelConfig(provider_id="test", name="scripted"),
        capabilities=kw.pop("capabilities", _agent_caps("terminal")),
        **kw,
    )
    await create_agent(db, config)


def _inbound(agent_id, text, session_id=None):
    return InboundMessage(
        channel="test",
        bot_id=agent_id,
        external_user_id="test-user",
        text=text,
        message_id=str(uuid.uuid4()),
        session_id=session_id,
    )


def _patch_ws(monkeypatch, tmp_path):
    from agentos.config import settings
    from agentos.sandbox.workspace import WorkspaceManager

    ws_dir = tmp_path / "ws"
    ws_dir.mkdir(exist_ok=True)
    monkeypatch.setattr(WorkspaceManager, "create_workspace", lambda self, aid: ws_dir)
    # MEMORY.md reads/writes land in tmp_path — never the real agent home.
    monkeypatch.setattr(settings, "agent_home_root", tmp_path / "agents")


@pytest.mark.asyncio
async def test_continuation_replays_goal_correction_and_all_tool_pairs(db, tmp_path, monkeypatch):
    """12+ tool records + correction survive into the NEXT run — the old
    LIMIT=10 replay silently dropped exactly this history."""
    _patch_ws(monkeypatch, tmp_path)
    await _make_agent(db)

    model = ScriptedModel(
        [
            # run 1: thinking + 12 tool calls then answer
            ScriptedResponse(
                thinking="planning",
                tool_calls=[
                    {"id": f"c{i}", "name": "terminal", "args": {"command": f"echo {i}"}}
                    for i in range(12)
                ],
            ),
            ScriptedResponse(content="done with twelve"),
            # run 2 (correction): plain answer
            ScriptedResponse(content="understood, corrected"),
            # run 3 (continue): plain answer — inspectable via seen_calls
            ScriptedResponse(content="continuing"),
        ]
    )
    pipeline = Pipeline(db=db, harness=Harness(model=model))

    run1 = await pipeline.handle_inbound(
        _inbound("conv-test", "original goal — remember it"), trigger="user_message", is_test=True
    )
    run2 = await pipeline.handle_inbound(
        _inbound("conv-test", "correction: that was wrong", session_id=run1.session_id),
        trigger="user_message",
        is_test=True,
    )
    run3 = await pipeline.handle_inbound(
        _inbound("conv-test", "continue", session_id=run2.session_id),
        trigger="user_message",
        is_test=True,
    )
    assert run3.status == "completed"

    # The model's third-run input is a deep copy taken at dispatch time.
    seen = model.seen_calls[-1]["messages"]
    contents = [m.get("content", "") or "" for m in seen]

    # Goal + correction appear exactly once each
    assert sum("original goal" in c for c in contents) == 1
    assert sum("correction: that was wrong" in c for c in contents) == 1
    # All 12 tool pairs replayed (assistant call + tool result per call)
    tool_rows = [m for m in seen if m.get("role") == "tool"]
    assert len(tool_rows) == 12
    # No thinking row reached the model
    assert all(m.get("role") != "thinking" for m in seen)
    # Ordering: goal precedes correction precedes continue
    goal_i = next(i for i, c in enumerate(contents) if "original goal" in c)
    corr_i = next(i for i, c in enumerate(contents) if "correction:" in c)
    cont_i = next(i for i, c in enumerate(contents) if c == "continue")
    assert goal_i < corr_i < cont_i


@pytest.mark.asyncio
async def test_malformed_tool_call_row_is_skipped_not_invented(db, tmp_path, monkeypatch):
    """A legacy row with unparseable tool_call JSON must not become a
    fabricated record."""
    _patch_ws(monkeypatch, tmp_path)
    await _make_agent(db)

    model = ScriptedModel([ScriptedResponse(content="ok")])
    pipeline = Pipeline(db=db, harness=Harness(model=model))
    run = await pipeline.handle_inbound(
        _inbound("conv-test", "hello"), trigger="user_message", is_test=True
    )

    # Inject a malformed tool_call row into the same session's earlier run
    db.add(
        Message(
            id=str(uuid.uuid4()),
            run_id=run.id,
            role="tool_call",
            content="{not json",
            seq=99,
        )
    )
    await db.commit()

    conv = await Conversation.load(db, await db.get(Session, run.session_id))
    rendered = conv.render()
    # The malformed row contributes nothing — the healthy rows still load.
    assert all("{not json" not in (m.get("content") or "") for m in rendered)
    assert any(m["role"] == "user" and "hello" in m["content"] for m in rendered)


@pytest.mark.asyncio
async def test_nested_subagent_rows_never_enter_parent_context(db, tmp_path, monkeypatch):
    _patch_ws(monkeypatch, tmp_path)
    await _make_agent(db)
    model = ScriptedModel([ScriptedResponse(content="parent"), ScriptedResponse(content="next")])
    pipeline = Pipeline(db=db, harness=Harness(model=model))
    run1 = await pipeline.handle_inbound(
        _inbound("conv-test", "parent turn"), trigger="user_message", is_test=True
    )
    db.add(
        Message(
            id=str(uuid.uuid4()),
            run_id=run1.id,
            role="assistant",
            content="nested sub-agent reply",
            seq=50,
            subagent_id="sub-1",
        )
    )
    await db.commit()
    conv = await Conversation.load(db, await db.get(Session, run1.session_id))
    assert all("nested sub-agent" not in (m.get("content") or "") for m in conv.messages)


@pytest.mark.asyncio
async def test_prior_summary_renders_exactly_once(db, tmp_path, monkeypatch):
    """Stored summary + uncovered originals reach the model once each —
    the summary is not duplicated and no dummy user row appears."""
    _patch_ws(monkeypatch, tmp_path)
    await _make_agent(db)

    model = ScriptedModel([ScriptedResponse(content="first"), ScriptedResponse(content="second")])
    pipeline = Pipeline(db=db, harness=Harness(model=model))
    run1 = await pipeline.handle_inbound(
        _inbound("conv-test", "turn one"), trigger="user_message", is_test=True
    )

    session = await db.get(Session, run1.session_id)
    session.conversation_summary = "## Goal\nSomething happened"
    session.conversation_summary_version = 1
    await db.commit()

    run2 = await pipeline.handle_inbound(
        _inbound("conv-test", "turn two", session_id=run1.session_id),
        trigger="user_message",
        is_test=True,
    )
    assert run2.status == "completed"
    seen = model.seen_calls[-1]["messages"]
    summary_rows = [m for m in seen if "Previous conversation summary" in (m.get("content") or "")]
    assert len(summary_rows) == 1
    assert "Something happened" in summary_rows[0]["content"]
    # No blank dummy user message
    assert all(m.get("role") != "user" or m.get("content", "").strip() for m in seen)


@pytest.mark.asyncio
async def test_successful_compaction_covers_middle_ids_only(db, tmp_path, monkeypatch):
    """Mocked summary persists coverage of the middle slice ONLY — the next
    run replays uncovered head/tail and the stored summary, never the
    covered originals."""
    _patch_ws(monkeypatch, tmp_path)
    await _make_agent(
        db,
        compaction=CompactionConfig(
            auto_compaction=True,
            protect_first_n=2,
            protect_last_n=2,
            tail_budget_fraction=0.01,
            threshold=0.01,
        ),
    )

    from agentos.harness import compaction as compaction_mod

    summary_calls = []

    async def fake_summary(middle, previous_summary, **kw):
        summary_calls.append(len(middle))
        return "## Goal\ncompact summary"

    monkeypatch.setattr(compaction_mod, "generate_summary", fake_summary)
    # Tiny input budget → forced compaction on next run.
    monkeypatch.setattr("agentos.harness.compaction.get_model_max_tokens", lambda *a, **k: 20000)
    monkeypatch.setattr(
        "agentos.providers.catalog_policy.resolve_input_budget",
        lambda *a, **k: {"tokens": 20000, "source": "test"},
    )

    model = ScriptedModel(
        [ScriptedResponse(content="first run done"), ScriptedResponse(content="second run done")]
    )
    pipeline = Pipeline(db=db, harness=Harness(model=model))

    # Seed a session with stored originals (12 alternating rows).
    run1 = await pipeline.handle_inbound(
        _inbound("conv-test", "seed turn"), trigger="user_message", is_test=True
    )
    session = await db.get(Session, run1.session_id)
    covered_markers = []
    for i in range(12):
        mid = str(uuid.uuid4())
        m = Message(
            id=mid,
            run_id=run1.id,
            role="user" if i % 2 == 0 else "assistant",
            content=f"historic {i} " + "z" * 300,
            seq=10 + i,
        )
        db.add(m)
        covered_markers.append(mid)
    await db.commit()

    run2 = await pipeline.handle_inbound(
        _inbound("conv-test", "after compaction", session_id=run1.session_id),
        trigger="user_message",
        is_test=True,
    )
    assert run2.status == "completed"
    assert summary_calls, "compaction should have run"

    # Coverage persisted on the session — middle ids only, version bumped.
    await db.refresh(session)
    assert session.conversation_summary == "## Goal\ncompact summary"
    assert session.conversation_summary_version >= 1
    coverage = json.loads(session.conversation_summary_coverage or "[]")
    assert coverage and all(cid in covered_markers for cid in coverage)
    # Only a strict subset of the seeded rows was covered — head+tail stay.
    assert len(coverage) < len(covered_markers)

    # Next run replays the summary ONCE plus uncovered originals — literal
    # markers check the actual recorded model input, not just DB state.
    # Summary generation is forced to fail for run3 so re-compaction can't
    # shrink the replay — uncovered originals go through intact.
    async def run3_boom(*a, **kw):
        raise RuntimeError("offline")

    monkeypatch.setattr(compaction_mod, "generate_summary", run3_boom)
    model2 = ScriptedModel([ScriptedResponse(content="third")])
    pipeline2 = Pipeline(db=db, harness=Harness(model=model2))
    run3 = await pipeline2.handle_inbound(
        _inbound("conv-test", "third", session_id=run2.session_id),
        trigger="user_message",
        is_test=True,
    )
    assert run3.status == "completed"
    seen = model2.seen_calls[-1]["messages"]
    texts = [m.get("content", "") or "" for m in seen]
    assert sum("Previous conversation summary" in c for c in texts) == 1
    assert "compact summary" in " ".join(texts)
    # Covered middle markers never replay; uncovered head/tail survive.
    replayed = [t for t in texts if t.startswith("historic ")]
    assert len(replayed) == len(covered_markers) - len(coverage)
    # The uncovered tail markers survive; a covered middle marker is gone.
    assert "historic 11" in " ".join(texts)
    assert "historic 5" not in " ".join(texts)


@pytest.mark.asyncio
async def test_failed_summary_never_advances_coverage_or_version(db, tmp_path, monkeypatch):
    """A provider failure mid-run leaves coverage/version untouched and the
    run continues on the original history when it still fits the hard cap."""
    _patch_ws(monkeypatch, tmp_path)
    await _make_agent(
        db,
        compaction=CompactionConfig(
            auto_compaction=True, protect_first_n=1, protect_last_n=1, threshold=0.01
        ),
    )

    from agentos.harness import compaction as compaction_mod

    async def boom(*a, **kw):
        raise RuntimeError("provider down — sk-secret")

    monkeypatch.setattr(compaction_mod, "generate_summary", boom)
    monkeypatch.setattr("agentos.harness.compaction.get_model_max_tokens", lambda *a, **k: 20000)
    monkeypatch.setattr(
        "agentos.providers.catalog_policy.resolve_input_budget",
        lambda *a, **k: {"tokens": 20000, "source": "test"},
    )

    model = ScriptedModel([ScriptedResponse(content="seed"), ScriptedResponse(content="after")])
    pipeline = Pipeline(db=db, harness=Harness(model=model))
    run1 = await pipeline.handle_inbound(
        _inbound("conv-test", "seed"), trigger="user_message", is_test=True
    )
    for i in range(8):
        db.add(
            Message(
                id=str(uuid.uuid4()),
                run_id=run1.id,
                role="user" if i % 2 == 0 else "assistant",
                content=f"h{i} " + "z" * 300,
                seq=10 + i,
            )
        )
    await db.commit()
    session = await db.get(Session, run1.session_id)
    assert session.conversation_summary_version == 0

    run2 = await pipeline.handle_inbound(
        _inbound("conv-test", "after", session_id=run1.session_id),
        trigger="user_message",
        is_test=True,
    )
    # Under the hard limit → continue on intact originals, run completes.
    assert run2.status == "completed"
    seen = model.seen_calls[-1]["messages"]
    texts = [m.get("content", "") or "" for m in seen]
    assert "h0" in " ".join(texts) and "h7" in " ".join(texts)
    assert "seed" in " ".join(texts)
    await db.refresh(session)
    # Failed summary → coverage/version untouched, no fabricated summary.
    assert session.conversation_summary_version == 0
    assert session.conversation_summary is None
    assert session.conversation_summary_coverage is None


@pytest.mark.asyncio
async def test_fixed_system_and_tools_over_budget_fails_without_dispatch(db, tmp_path, monkeypatch):
    """When system prompt + tool schemas alone exceed the hard input budget,
    the run fails with a generic error and the model is never called."""
    _patch_ws(monkeypatch, tmp_path)
    await _make_agent(db)

    monkeypatch.setattr(
        "agentos.providers.catalog_policy.resolve_input_budget",
        lambda *a, **k: {"tokens": 1, "source": "test"},
    )
    monkeypatch.setattr("agentos.harness.compaction.get_model_max_tokens", lambda *a, **k: 1)
    # Token counting must reflect real sizes — tiny budget 1 → always over.
    model = ScriptedModel([ScriptedResponse(content="never")])
    pipeline = Pipeline(db=db, harness=Harness(model=model))
    run = await pipeline.handle_inbound(
        _inbound("conv-test", "hi"), trigger="user_message", is_test=True
    )
    assert run.status == "failed"
    assert model.seen_calls == []  # zero dispatches


@pytest.mark.asyncio
async def test_summary_failure_over_hard_budget_fails_without_dispatch(db, tmp_path, monkeypatch):
    """Summarization failure + still-over-limit → generic failure, zero
    dispatches — never send oversized input."""
    _patch_ws(monkeypatch, tmp_path)
    await _make_agent(
        db,
        compaction=CompactionConfig(
            auto_compaction=True, protect_first_n=1, protect_last_n=1, threshold=0.01
        ),
    )

    from agentos.harness import compaction as compaction_mod

    async def boom(*a, **kw):
        raise RuntimeError("no model")

    model = ScriptedModel([ScriptedResponse(content="seed")])
    pipeline = Pipeline(db=db, harness=Harness(model=model))
    run1 = await pipeline.handle_inbound(
        _inbound("conv-test", "seed"), trigger="user_message", is_test=True
    )
    assert run1.status == "completed"
    for i in range(8):
        db.add(
            Message(
                id=str(uuid.uuid4()),
                run_id=run1.id,
                role="user",
                content="z" * 400,
                seq=10 + i,
            )
        )
    await db.commit()

    # Now the budget collapses below the full conversation — summary fails,
    # dispatch count for run2 stays zero.
    monkeypatch.setattr(compaction_mod, "generate_summary", boom)
    monkeypatch.setattr("agentos.harness.compaction.get_model_max_tokens", lambda *a, **k: 50)
    monkeypatch.setattr(
        "agentos.providers.catalog_policy.resolve_input_budget",
        lambda *a, **k: {"tokens": 50, "source": "test"},
    )
    run2 = await pipeline.handle_inbound(
        _inbound("conv-test", "after", session_id=run1.session_id),
        trigger="user_message",
        is_test=True,
    )
    assert run2.status == "failed"
    assert "budget" in (run2.error or "").lower()
    # Only run1's dispatch happened — run2 never reached the model.
    assert len(model.seen_calls) == 1


@pytest.mark.asyncio
async def test_parallel_tool_batch_survives_head_alignment(db, tmp_path, monkeypatch):
    """A multi-tool assistant batch must never split across the head
    boundary — head extends forward over the batch's tool results."""

    msgs = [
        {"role": "user", "content": "goal"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {"id": "a", "type": "function", "function": {"name": "t", "arguments": "{}"}},
                {"id": "b", "type": "function", "function": {"name": "t", "arguments": "{}"}},
                {"id": "c", "type": "function", "function": {"name": "t", "arguments": "{}"}},
            ],
        },
        {"role": "tool", "tool_call_id": "a", "content": "ra"},
        {"role": "tool", "tool_call_id": "b", "content": "rb"},
        {"role": "tool", "tool_call_id": "c", "content": "rc"},
    ] + [{"role": "user", "content": f"turn {i} " + "x" * 200} for i in range(12)]

    # Head=2 would land ON the tool result at index 2 — forward alignment
    # must pull the whole batch into the head instead of splitting it.
    from agentos.harness.compaction import _align_boundary_forward

    head_end = _align_boundary_forward(msgs, 2)
    assert head_end == 5  # assistant call + 3 results all inside head


@pytest.mark.asyncio
async def test_complete_parallel_batch_never_splits_in_public_compaction():
    """A 3-call assistant batch stays atomic through compact_context —
    all real pairs intact, no injected 'not available' stub."""
    from agentos.harness.compaction import compact_context

    batch = [
        {"role": "user", "content": "goal"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": f"call_{c}",
                    "type": "function",
                    "function": {"name": "t", "arguments": "{}"},
                }
                for c in "abc"
            ],
        },
        *[{"role": "tool", "tool_call_id": f"call_{c}", "content": f"result_{c}"} for c in "abc"],
    ]
    tail = [
        {"role": "user" if i % 2 == 0 else "assistant", "content": "x" * 800} for i in range(12)
    ]
    msgs = batch + tail
    config = AgentConfig(
        id="t",
        name="t",
        model=ModelConfig(provider_id="t", name="m"),
        compaction=CompactionConfig(
            auto_compaction=True, protect_first_n=2, protect_last_n=2, threshold=0.01
        ),
    )
    with (
        patch("agentos.harness.compaction.generate_summary", new_callable=AsyncMock) as mock,
        patch("agentos.harness.compaction.get_model_max_tokens", return_value=20000),
    ):
        mock.return_value = "## Goal\ns"
        result = await compact_context(msgs, config, "m", force=True)
    assert result.compacted
    out = result.messages
    # Every real pair in the output is complete: call + its real result.
    for cid in "abc":
        has_call = any(
            m.get("role") == "assistant"
            and any(tc.get("id") == f"call_{cid}" for tc in m.get("tool_calls", []))
            for m in out
        )
        has_result = any(
            m.get("role") == "tool" and m.get("tool_call_id") == f"call_{cid}" for m in out
        )
        # Either both sides kept together, or neither (summarized).
        assert has_call == has_result
    # No manufactured stub anywhere — valid complete groups never need one.
    assert all("not available after compaction" not in (m.get("content") or "") for m in out)


@pytest.mark.asyncio
async def test_auto_compaction_off_still_renders_prior_summary(db, tmp_path, monkeypatch):
    """auto_compaction=False: no summarization, but the stored summary still
    reaches the model exactly once."""
    _patch_ws(monkeypatch, tmp_path)
    await _make_agent(db, compaction=CompactionConfig(auto_compaction=False))
    model = ScriptedModel([ScriptedResponse(content="one"), ScriptedResponse(content="two")])
    pipeline = Pipeline(db=db, harness=Harness(model=model))
    run1 = await pipeline.handle_inbound(
        _inbound("conv-test", "turn one"), trigger="user_message", is_test=True
    )
    session = await db.get(Session, run1.session_id)
    session.conversation_summary = "## Goal\nearlier work"
    session.conversation_summary_version = 3
    await db.commit()
    run2 = await pipeline.handle_inbound(
        _inbound("conv-test", "turn two", session_id=run1.session_id),
        trigger="user_message",
        is_test=True,
    )
    assert run2.status == "completed"
    seen = model.seen_calls[-1]["messages"]
    texts = [m.get("content", "") or "" for m in seen]
    assert sum("earlier work" in c for c in texts) == 1


@pytest.mark.asyncio
async def test_equal_timestamps_order_by_seq(db, tmp_path, monkeypatch):
    """Rows with identical Run.started_at/created_at still replay in seq order."""
    _patch_ws(monkeypatch, tmp_path)
    await _make_agent(db)
    model = ScriptedModel([ScriptedResponse(content="one"), ScriptedResponse(content="two")])
    pipeline = Pipeline(db=db, harness=Harness(model=model))
    run1 = await pipeline.handle_inbound(
        _inbound("conv-test", "seed"), trigger="user_message", is_test=True
    )
    db.add(
        Message(id=str(uuid.uuid4()), run_id=run1.id, role="user", content="first-marker", seq=10)
    )
    db.add(
        Message(
            id=str(uuid.uuid4()), run_id=run1.id, role="assistant", content="second-marker", seq=11
        )
    )
    db.add(
        Message(id=str(uuid.uuid4()), run_id=run1.id, role="user", content="third-marker", seq=12)
    )
    await db.commit()
    run2 = await pipeline.handle_inbound(
        _inbound("conv-test", "next", session_id=run1.session_id),
        trigger="user_message",
        is_test=True,
    )
    assert run2.status == "completed"
    seen = model.seen_calls[-1]["messages"]
    texts = [m.get("content", "") or "" for m in seen]
    i1 = texts.index("first-marker")
    i2 = texts.index("second-marker")
    i3 = texts.index("third-marker")
    assert i1 < i2 < i3


@pytest.mark.asyncio
async def test_valid_json_but_malformed_tool_call_is_dropped(db, tmp_path, monkeypatch):
    """Valid JSON that isn't a valid tool call (empty dict, missing id) is
    dropped from replay — never surfaces as an invented record."""
    _patch_ws(monkeypatch, tmp_path)
    await _make_agent(db)
    model = ScriptedModel([ScriptedResponse(content="one"), ScriptedResponse(content="two")])
    pipeline = Pipeline(db=db, harness=Harness(model=model))
    run1 = await pipeline.handle_inbound(
        _inbound("conv-test", "seed"), trigger="user_message", is_test=True
    )
    for bad in ["{}", "[]", '{"capability":"t"}', '{"id":"x"}', '"just-a-string"']:
        db.add(
            Message(
                id=str(uuid.uuid4()),
                run_id=run1.id,
                role="tool_call",
                content=bad,
                seq=10,
            )
        )
    await db.commit()
    conv = await Conversation.load(db, await db.get(Session, run1.session_id))
    assert len(conv.dropped_rows) == 5
    assert all(m.get("role") != "tool" for m in conv.messages)
    assert all("tool_calls" not in m for m in conv.messages if m.get("role") == "assistant")


@pytest.mark.asyncio
async def test_orphaned_coverage_without_summary_is_ignored(db, tmp_path, monkeypatch):
    """coverage JSON with no summary must never filter history."""
    _patch_ws(monkeypatch, tmp_path)
    await _make_agent(db)
    model = ScriptedModel([ScriptedResponse(content="one")])
    pipeline = Pipeline(db=db, harness=Harness(model=model))
    run1 = await pipeline.handle_inbound(
        _inbound("conv-test", "seed"), trigger="user_message", is_test=True
    )
    db.add(Message(id="covered-1", run_id=run1.id, role="user", content="marker-x", seq=10))
    await db.commit()
    session = await db.get(Session, run1.session_id)
    session.conversation_summary_coverage = json.dumps(["covered-1"])
    session.conversation_summary = None  # orphaned coverage — no summary
    session.conversation_summary_version = 1
    await db.commit()
    conv = await Conversation.load(db, session)
    # No nonempty summary → coverage is "known" (nothing was summarized)
    # and the orphaned covered-ids list must not filter the marker out.
    assert conv.coverage_known
    assert not conv.covered_ids
    contents = " ".join(m.get("content", "") or "" for m in conv.messages)
    assert "marker-x" in contents


@pytest.mark.asyncio
async def test_cas_loser_run_fails_instead_of_dispatching(db, tmp_path, monkeypatch):
    """A concurrent summary write (CAS loss) must fail the run clearly —
    the model is not dispatched on unsaved bookkeeping."""
    _patch_ws(monkeypatch, tmp_path)
    await _make_agent(
        db,
        compaction=CompactionConfig(
            auto_compaction=True,
            protect_first_n=1,
            protect_last_n=1,
            tail_budget_fraction=0.01,
            threshold=0.01,
        ),
    )
    from agentos.harness import compaction as compaction_mod

    async def fake_summary(middle, previous_summary=None, **kw):
        return "## Goal\ns"

    monkeypatch.setattr(compaction_mod, "generate_summary", fake_summary)
    monkeypatch.setattr(
        "agentos.providers.catalog_policy.resolve_input_budget",
        lambda *a, **k: {"tokens": 20000, "source": "test"},
    )
    # CAS always loses
    monkeypatch.setattr(Conversation, "store_summary", AsyncMock(return_value=False))

    model = ScriptedModel([ScriptedResponse(content="never")])
    pipeline = Pipeline(db=db, harness=Harness(model=model))
    run1 = await pipeline.handle_inbound(
        _inbound("conv-test", "seed"), trigger="user_message", is_test=True
    )
    for i in range(8):
        db.add(
            Message(
                id=str(uuid.uuid4()),
                run_id=run1.id,
                role="user" if i % 2 == 0 else "assistant",
                content=f"h{i} " + "z" * 300,
                seq=10 + i,
            )
        )
    await db.commit()
    run2 = await pipeline.handle_inbound(
        _inbound("conv-test", "after", session_id=run1.session_id),
        trigger="user_message",
        is_test=True,
    )
    assert run2.status == "failed"
    assert "concurrent" in (run2.error or "").lower() or "compaction" in (run2.error or "").lower()
    assert len(model.seen_calls) == 1  # only run1 dispatched


@pytest.mark.asyncio
async def test_current_user_row_survives_deep_history_protection():
    """protected_tail_start keeps the current-turn row uncovered even when
    buried behind 20+ tool result rows."""
    from agentos.harness.compaction import compact_context

    head = [{"role": "user", "content": "old " + "z" * 800}]
    tools = []
    for i in range(20):
        tools.append(
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": f"c{i}",
                        "type": "function",
                        "function": {"name": "t", "arguments": "{}"},
                    }
                ],
            }
        )
        tools.append({"role": "tool", "tool_call_id": f"c{i}", "content": "r" * 400})
    current = {"role": "user", "content": "the current ask"}
    msgs = head + tools + [current]
    idx = len(msgs) - 1
    config = AgentConfig(
        id="t",
        name="t",
        model=ModelConfig(provider_id="t", name="m"),
        compaction=CompactionConfig(
            auto_compaction=True,
            protect_first_n=0,
            protect_last_n=0,
            tail_budget_fraction=0.0,
            threshold=0.01,
        ),
    )
    with (
        patch("agentos.harness.compaction.generate_summary", new_callable=AsyncMock) as mock,
        patch("agentos.harness.compaction.get_model_max_tokens", return_value=20000),
    ):
        mock.return_value = "## Goal\ns"
        result = await compact_context(msgs, config, "m", force=True, protected_tail_start=idx)
    # The current user row stays in the output verbatim and uncovered.
    assert result.messages[-1] is current
    # Every tool result in the tail still has its call (no split pairs).
    call_ids_out = {tc["id"] for m in result.messages for tc in (m.get("tool_calls") or [])}
    result_ids_out = {m["tool_call_id"] for m in result.messages if m.get("role") == "tool"}
    assert result_ids_out <= call_ids_out


@pytest.mark.asyncio
async def test_two_tool_turns_second_narration_does_not_leak(db, tmp_path, monkeypatch):
    """Two tool-call turns: per-call receipts resolve their own narration —
    a second turn without narration must not claim the first turn's row."""
    _patch_ws(monkeypatch, tmp_path)
    await _make_agent(db)
    model = ScriptedModel(
        [
            # turn 1: thinking + tool call
            ScriptedResponse(
                thinking="first reasoning",
                tool_calls=[{"id": "t1", "name": "terminal", "args": {"command": "a"}}],
            ),
            # turn 2: second tool call — no narration this turn
            ScriptedResponse(
                tool_calls=[{"id": "t2", "name": "terminal", "args": {"command": "b"}}],
            ),
            ScriptedResponse(content="done"),
        ]
    )
    pipeline = Pipeline(db=db, harness=Harness(model=model))
    run = await pipeline.handle_inbound(
        _inbound("conv-test", "two tool turns"), trigger="user_message", is_test=True
    )
    assert run.status == "completed"
    # Both tool_call rows persisted independently — no sharing.
    rows = (
        (
            await db.execute(
                select(Message).where(Message.run_id == run.id, Message.role == "tool_call")
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 2
    payloads = [json.loads(m.content) for m in rows]
    assert {p["id"] for p in payloads} == {"t1", "t2"}


@pytest.mark.asyncio
async def test_grown_tool_schemas_trigger_budget_check_on_short_conversation(
    db, tmp_path, monkeypatch
):
    """A one-message conversation still hits the per-dispatch gate: freshly
    assembled tool schemas exceeding the fixed budget fail clearly."""
    _patch_ws(monkeypatch, tmp_path)
    await _make_agent(db)

    # Fixed section grows beyond the resolved input budget at dispatch time.
    monkeypatch.setattr(
        "agentos.harness.compaction.count_tool_tokens", lambda tools, m=None: 50_000
    )
    monkeypatch.setattr(
        "agentos.providers.catalog_policy.resolve_input_budget",
        lambda *a, **k: {"tokens": 10_000, "source": "test"},
    )
    model = ScriptedModel([ScriptedResponse(content="never")])
    pipeline = Pipeline(db=db, harness=Harness(model=model))
    run = await pipeline.handle_inbound(
        _inbound("conv-test", "hi"), trigger="user_message", is_test=True
    )
    assert run.status == "failed"
    assert "budget" in (run.error or "").lower()
    assert model.seen_calls == []
