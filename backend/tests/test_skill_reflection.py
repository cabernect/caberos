"""Reflection runtime — ScriptedModel drives the REAL Harness + SyscallHandler
(restrictions + SkillEditSession delegation) through agentos.reflection;
no real provider."""

import asyncio
import uuid

import pytest
from sqlalchemy import select

from agentos.config_schema import AgentConfig, CapabilityGrant, Limits, ModelConfig
from agentos.harness.scripted_model import ScriptedModel, ScriptedResponse
from agentos.models.contact import Contact
from agentos.models.model_call import ModelCall
from agentos.models.run import Message, Run
from agentos.models.session import Session
from agentos.models.skill import SkillRevision
from agentos.models.skill_usage import SkillActivation


def _mkcall(name, args):
    return {"id": f"c-{uuid.uuid4().hex[:8]}", "name": name, "args": args}


def _patch_provider(monkeypatch, model):
    from agentos.providers import ProviderRegistry

    async def _for_model(self, _pid):
        return model

    monkeypatch.setattr(ProviderRegistry, "for_model", _for_model)


async def _seed(db, tmp_path, monkeypatch, capabilities):
    from agentos.agent_service import create_agent
    from agentos.config import settings

    cfg = AgentConfig(
        id="qa-agent",
        name="QA",
        model=ModelConfig(provider_id="p", name="m"),
        limits=Limits(),
        capabilities=capabilities,
    )
    await create_agent(db, cfg)
    db.add(Contact(id="c1", channel="dashboard_chat", bot_id="qa-agent", external_user_id="u1"))
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
    db.add(Message(id="m1", run_id="r1", role="user", content="use pdf", seq=0))
    db.add(Message(id="m2", run_id="r1", role="assistant", content="ok", seq=1))
    await db.commit()
    monkeypatch.setattr(settings, "workspace_root", tmp_path / "ws")
    # evolve must resolve — provide it as a live agent-local skill.
    live = tmp_path / "ws" / "qa-agent" / "skills" / "evolve"
    live.mkdir(parents=True)
    (live / "SKILL.md").write_text(
        "---\nname: evolve\ndescription: ev\nlicense: Apache-2.0\n"
        "compatibility: c\nallowed-tools: read_file write_file\n---\nPROC",
        encoding="utf-8",
    )
    return cfg


@pytest.mark.asyncio
async def test_reflect_read_then_edit_creates_local_revision(db, tmp_path, monkeypatch):
    """read_file (absent-new baseline) → write_file (staged) → final →
    publish produces a local revision; outcome 'changed'."""
    cfg = await _seed(
        db,
        tmp_path,
        monkeypatch,
        [CapabilityGrant(name="read_file"), CapabilityGrant(name="write_file")],
    )
    session = await db.get(Session, "s1")

    model = ScriptedModel(
        [
            ScriptedResponse(
                tool_calls=[_mkcall("read_file", {"path": "skills/newskill/SKILL.md"})]
            ),
            ScriptedResponse(
                tool_calls=[
                    _mkcall(
                        "write_file",
                        {
                            "path": "skills/newskill/SKILL.md",
                            "content": (
                                "---\nname: newskill\ndescription: n\nlicense: x\n"
                                "compatibility: c\nallowed-tools: read_file\n---\nBody"
                            ),
                        },
                    )
                ]
            ),
            ScriptedResponse(content="created newskill from the session feedback"),
        ]
    )
    _patch_provider(monkeypatch, model)

    from agentos.reflection import reflect_session

    refl = await reflect_session(db, cfg, session, "c1", ["r1"])
    assert refl is not None
    assert refl.outcome == "changed"
    assert refl.revision_ids, "no revision recorded"
    rev = await db.get(SkillRevision, refl.revision_ids[0])
    assert rev is not None and rev.source_run_id == refl.run_id
    # The local file landed.
    p = tmp_path / "ws" / "qa-agent" / "skills" / "newskill" / "SKILL.md"
    assert p.exists()
    # Reflection run is terminal and distinctly triggered.
    run = await db.get(Run, refl.run_id)
    assert run.status == "completed" and run.trigger == "reflection"
    # Model calls ledgered with purpose=reflection and session linkage.
    calls = list(await db.scalars(select(ModelCall).where(ModelCall.run_id == refl.run_id)))
    assert calls and all(c.purpose == "reflection" for c in calls)
    assert all(c.session_id == "s1" for c in calls)
    # The evidence view actually reached the model.
    user_msgs = [m for m in model.seen_calls[0]["messages"] if m.get("role") == "user"]
    assert any("use pdf" in m.get("content", "") for m in user_msgs)


@pytest.mark.asyncio
async def test_reflect_no_change_and_fingerprint_dedup(db, tmp_path, monkeypatch):
    cfg = await _seed(db, tmp_path, monkeypatch, [CapabilityGrant(name="read_file")])
    session = await db.get(Session, "s1")
    model = ScriptedModel([ScriptedResponse(content="nothing reusable to change")])
    _patch_provider(monkeypatch, model)

    from agentos.reflection import reflect_session

    r1 = await reflect_session(db, cfg, session, "c1", ["r1"])
    assert r1.outcome == "no_change"
    # Same evidence again — the fingerprint claim refuses a second pass
    # before the model is ever invoked.
    before = len(model.seen_calls)
    r2 = await reflect_session(db, cfg, session, "c1", ["r1"])
    assert r2 is None and len(model.seen_calls) == before


@pytest.mark.asyncio
async def test_reflect_denied_tool_and_failure_finalize(db, tmp_path, monkeypatch):
    """A capability outside the restricted set is denied by mediation;
    a provider failure still finalizes the activity + run as failed."""
    cfg = await _seed(db, tmp_path, monkeypatch, [CapabilityGrant(name="read_file")])
    session = await db.get(Session, "s1")

    class _Failing(ScriptedModel):
        # The harness prefers complete_stream when present — inject there.
        async def complete_stream(self, **kw):
            if self._index == 1:
                self._index += 1
                raise RuntimeError("provider died")
            async for item in super().complete_stream(**kw):
                yield item

    model = _Failing([ScriptedResponse(tool_calls=[_mkcall("terminal", {"command": "rm -rf /"})])])
    _patch_provider(monkeypatch, model)

    from agentos.reflection import reflect_session

    refl = await reflect_session(db, cfg, session, "c1", ["r1"])
    assert refl.outcome == "failed" and refl.error
    assert refl.completed_at is not None
    run = await db.get(Run, refl.run_id)
    assert run.status == "failed"
    # The denied call was persisted as a tool_call record, not executed.
    tool_msgs = list(
        await db.scalars(
            select(Message).where(Message.run_id == refl.run_id, Message.role == "tool_call")
        )
    )
    assert any("terminal" in (m.content or "") for m in tool_msgs)


@pytest.mark.asyncio
async def test_reflect_inspection_does_not_count_as_activation(db, tmp_path, monkeypatch):
    """skills_load during a reflection run is inspection — no SkillActivation."""
    cfg = await _seed(
        db,
        tmp_path,
        monkeypatch,
        [CapabilityGrant(name="read_file"), CapabilityGrant(name="skills_load")],
    )
    session = await db.get(Session, "s1")
    model = ScriptedModel(
        [
            ScriptedResponse(tool_calls=[_mkcall("skills_load", {"name": "evolve"})]),
            ScriptedResponse(content="procedure reviewed, no change needed"),
        ]
    )
    _patch_provider(monkeypatch, model)

    from agentos.reflection import reflect_session

    refl = await reflect_session(db, cfg, session, "c1", ["r1"])
    assert refl.outcome == "no_change"
    activations = list(await db.scalars(select(SkillActivation)))
    assert activations == []


@pytest.mark.asyncio
async def test_reflect_oversized_tool_batch_drains_not_fails(db, tmp_path, monkeypatch):
    """A restricted reflection turn returning >4 tool calls must not hit the
    fatal per-turn cap — calls drain through bounded concurrency and the
    model still sees one matched result per call."""
    cfg = await _seed(db, tmp_path, monkeypatch, [CapabilityGrant(name="read_file")])
    session = await db.get(Session, "s1")

    calls = [_mkcall("read_file", {"path": "skills/evolve/SKILL.md"}) for _ in range(6)]
    model = ScriptedModel(
        [ScriptedResponse(tool_calls=calls), ScriptedResponse(content="no change needed")]
    )
    _patch_provider(monkeypatch, model)

    from agentos.reflection import reflect_session

    refl = await asyncio.wait_for(reflect_session(db, cfg, session, "c1", ["r1"]), timeout=10)
    assert refl is not None
    assert refl.outcome == "no_change", refl.error
    run = await db.get(Run, refl.run_id)
    assert run.status == "completed"

    # The model received a matched tool-result row for every call id, each
    # carrying the real read output (no placeholder empties).
    second = model.seen_calls[1]["messages"]
    results = {m["tool_call_id"]: m for m in second if m.get("role") == "tool"}
    assert set(results) == {c["id"] for c in calls}
    assert all("PROC" in m["content"] for m in results.values())
    # Persisted: 6 tool_call rows + real mediation AuditRecords on the run.
    tool_msgs = list(
        await db.scalars(
            select(Message).where(Message.run_id == refl.run_id, Message.role == "tool_call")
        )
    )
    assert len(tool_msgs) == 6
    from agentos.models.audit import AuditRecord

    audits = list(await db.scalars(select(AuditRecord).where(AuditRecord.run_id == refl.run_id)))
    assert len(audits) >= 6
    # Ledgered as reflection-purpose model calls on the reflection run.
    ledger = list(await db.scalars(select(ModelCall).where(ModelCall.run_id == refl.run_id)))
    assert ledger and all(c.purpose == "reflection" for c in ledger)


@pytest.mark.asyncio
async def test_reflect_batch_denies_out_of_scope_calls_individually(db, tmp_path, monkeypatch):
    """Out-of-capability calls inside a big batch are denied per call —
    allowed reads still land, no workspace escape."""
    cfg = await _seed(
        db,
        tmp_path,
        monkeypatch,
        [CapabilityGrant(name="read_file"), CapabilityGrant(name="write_file")],
    )
    session = await db.get(Session, "s1")

    calls = [
        _mkcall("read_file", {"path": "skills/evolve/SKILL.md"}),
        _mkcall("terminal", {"command": "echo hi"}),
        _mkcall("write_file", {"path": "../escape.txt", "content": "x"}),
        _mkcall("read_file", {"path": "skills/evolve/SKILL.md"}),
        _mkcall("read_file", {"path": "skills/evolve/SKILL.md"}),
    ]
    model = ScriptedModel([ScriptedResponse(tool_calls=calls), ScriptedResponse(content="done")])
    _patch_provider(monkeypatch, model)

    from agentos.reflection import reflect_session

    refl = await asyncio.wait_for(reflect_session(db, cfg, session, "c1", ["r1"]), timeout=10)
    assert refl is not None
    second = model.seen_calls[1]["messages"]
    results = {m["tool_call_id"]: m for m in second if m.get("role") == "tool"}
    assert len(results) == len(calls)
    # Terminal call was denied by the capability ceiling, not executed.
    term = results[calls[1]["id"]]
    assert "denied" in term["content"].lower() or "not permitted" in term["content"].lower()
    # The ../escape write is rejected at the boundary, not executed —
    # the staged-edit path validator refuses it as an invalid resource path.
    write = results[calls[2]["id"]]
    assert (
        "denied" in write["content"].lower()
        or "not permitted" in write["content"].lower()
        or "invalid" in write["content"].lower()
        or "error" in write["content"].lower()
    )
    assert not (tmp_path / "ws" / "escape.txt").exists()
    assert not (tmp_path / "escape.txt").exists()
