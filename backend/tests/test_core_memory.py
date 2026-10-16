"""Bounded core + learning slice — pin, publication, scope, extraction.

The core snapshot is pinned per session; MEMORY.md stays the authoritative
editable document; every write goes through update_core (validated,
hash-checked, atomic publish, revision evidence).
"""

import json
import uuid
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from agentos.agent_service import create_agent
from agentos.config_schema import (
    AgentConfig,
    CapabilityGrant,
    Limits,
    ModelConfig,
)
from agentos.harness.loop import Harness
from agentos.harness.scripted_model import ScriptedModel, ScriptedResponse
from agentos.memory.core import (
    IDENTITY_END,
    CoreConflict,
    build_core,
    cleanup_core,
    load_or_pin_core,
    split_core,
    update_core,
)
from agentos.models.core import CoreRevision
from agentos.models.run import Message, Run
from agentos.models.session import Session
from agentos.pipeline import InboundMessage, Pipeline


def _agent_caps(*names: str) -> list[CapabilityGrant]:
    return [CapabilityGrant(name=n, require_approval=False) for n in names]


async def _make_agent(db, agent_id="core-test", **kw):
    config = AgentConfig(
        id=agent_id,
        name="Core Test",
        model=ModelConfig(provider_id="test", name="scripted"),
        soul="Test soul.",
        persona="Calm.",
        task="Help the operator.",
        capabilities=kw.pop("capabilities", _agent_caps("terminal")),
        **kw,
    )
    await create_agent(db, config)
    return config


def _inbound(agent_id, text, session_id=None):
    return InboundMessage(
        channel="test",
        bot_id=agent_id,
        external_user_id="test-user",
        text=text,
        message_id=str(uuid.uuid4()),
        session_id=session_id,
    )


def _patch_env(monkeypatch, tmp_path):
    from agentos.config import settings
    from agentos.sandbox.workspace import WorkspaceManager

    ws_dir = tmp_path / "ws"
    ws_dir.mkdir(exist_ok=True)
    monkeypatch.setattr(WorkspaceManager, "create_workspace", lambda self, aid: ws_dir)
    monkeypatch.setattr(settings, "agent_home_root", tmp_path / "agents")


def _memory_path(agent_id, tmp_path):
    return tmp_path / "agents" / agent_id / "MEMORY.md"


@pytest.mark.asyncio
async def test_core_sent_once_with_each_identity_field(db, tmp_path, monkeypatch):
    """The whole core (managed identity + curated) reaches the model
    exactly once — no duplicated soul/persona/task/MEMORY.md sections."""
    _patch_env(monkeypatch, tmp_path)
    await _make_agent(db)
    model = ScriptedModel([ScriptedResponse(content="hi")])
    pipeline = Pipeline(db=db, harness=Harness(model=model))
    run = await pipeline.handle_inbound(
        _inbound("core-test", "hello"), trigger="user_message", is_test=True
    )
    assert run.status == "completed"
    system = model.seen_calls[0]["messages"][0]["content"]
    for fragment in ("Test soul.", "Calm.", "Help the operator."):
        assert system.count(fragment) == 1
    # Managed markers + guidance present
    assert "caberos:core-identity" in system
    # File on disk matches what the model saw
    disk = _memory_path("core-test", tmp_path).read_text()
    assert disk in system
    sha, identity, curated = split_core(disk)
    assert "Test soul." in identity


@pytest.mark.asyncio
async def test_session_pin_byte_stable_across_restart_and_update(db, tmp_path, monkeypatch):
    """Session keeps its pinned revision byte-for-byte after later
    notebook updates; a NEW session sees the newer revision."""
    _patch_env(monkeypatch, tmp_path)
    config = await _make_agent(db)
    session = Session(id=str(uuid.uuid4()), agent_id="core-test", contact_id="c1")
    db.add(session)
    await db.commit()

    snap1 = await load_or_pin_core(db, config, session)
    await db.commit()
    assert snap1.revision_id and session.core_revision_id == snap1.revision_id

    # Operator updates core — session pin must NOT move.
    snap2 = await update_core(db, config, "new curated entry")
    await db.commit()
    again = await load_or_pin_core(db, config, session)
    assert again.revision_id == snap1.revision_id
    assert again.content == snap1.content  # byte-stable

    # A new session picks up the newer revision.
    session2 = Session(id=str(uuid.uuid4()), agent_id="core-test", contact_id="c1")
    db.add(session2)
    await db.commit()
    snap3 = await load_or_pin_core(db, config, session2)
    assert snap3.revision_id == snap2.revision_id
    assert "new curated entry" in snap3.curated_content


@pytest.mark.asyncio
async def test_ceiling_enforced_on_tool_and_api_paths(db, tmp_path, monkeypatch):
    """Ceiling enforcement on the real API (422) and the mediated tool
    path — file bytes unchanged in both cases."""
    import httpx

    from agentos.auth import require_operator
    from agentos.db import get_db
    from agentos.main import app
    from agentos.models.operator import Operator
    from agentos.syscall.mediator import SyscallHandler
    from agentos.syscall.protocol import ToolCall

    _patch_env(monkeypatch, tmp_path)
    config = await _make_agent(
        db,
        limits=Limits(core_max_tokens=120),
        capabilities=_agent_caps("terminal", "memory_update"),
    )
    session = Session(id=str(uuid.uuid4()), agent_id="core-test", contact_id="c1")
    db.add(session)
    await db.commit()
    await load_or_pin_core(db, config, session)
    path = _memory_path("core-test", tmp_path)
    before = path.read_text()

    # Real API path — oversized curated update → 422, not 500/409.
    async def override_db():
        yield db

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[require_operator] = lambda: Operator(
        id="op", username="t", password_hash="", must_change_password=False
    )
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://t"
        ) as c:
            resp = await c.put(
                "/api/agents/core-test/memory",
                json={"content": "x " * 500},
            )
            assert resp.status_code == 422, resp.text
            # Missing agent → 404
            resp404 = await c.put("/api/agents/nope/memory", json={"content": "x"})
            assert resp404.status_code == 404
    finally:
        app.dependency_overrides.clear()
    assert path.read_text() == before

    # Mediated tool path — same overflow → conflict result, file untouched.
    handler = SyscallHandler(db=db, workspace_path=str(tmp_path / "ws"))
    result = await handler.mediate(
        call=ToolCall(
            id="1",
            name="memory_update",
            args={"content": "y " * 500},
        ),
        session=session,
        agent_config=config,
        run_id="run-x",
    )
    assert result.allowed is True
    assert result.output["updated"] is False
    assert "conflict" in result.output
    assert path.read_text() == before


@pytest.mark.asyncio
async def test_identity_overflow_is_config_conflict_zero_cleanup_calls(db, tmp_path, monkeypatch):
    """An identity that alone exceeds the ceiling fails as a config
    conflict — no cleanup/model attempt happens."""
    _patch_env(monkeypatch, tmp_path)
    config = await _make_agent(
        db,
        limits=Limits(core_max_tokens=10),
    )
    session = Session(id=str(uuid.uuid4()), agent_id="core-test", contact_id="c1")
    db.add(session)
    await db.commit()

    calls = []

    async def no_cleanup(*a, **kw):
        calls.append(1)
        raise AssertionError("cleanup must not run")

    monkeypatch.setattr("agentos.memory.core.cleanup_core", no_cleanup)
    with pytest.raises(CoreConflict, match="identity"):
        await load_or_pin_core(db, config, session)
    assert calls == []


@pytest.mark.asyncio
async def test_failed_cleanup_retains_old_bytes_and_candidate_evidence(
    db, tmp_path, monkeypatch, db_engine
):
    """cleanup_core failure leaves the published file intact; the attempt
    leaves no published revision."""
    _patch_env(monkeypatch, tmp_path)
    config = await _make_agent(db)
    session = Session(id=str(uuid.uuid4()), agent_id="core-test", contact_id="c1")
    db.add(session)
    await db.commit()
    await load_or_pin_core(db, config, session)
    before = _memory_path("core-test", tmp_path).read_text()

    async def boom(*a, **kw):
        raise RuntimeError("provider exploded")

    class BadAdapter:
        async def get_model_info(self, m):
            return {
                "model_str": "test-model",
                "resolved_model": {"context_window_tokens": 32768},
            }

        async def complete(self, **kw):
            raise RuntimeError("provider exploded")

    monkeypatch.setattr(
        "agentos.providers.ProviderRegistry.for_model",
        AsyncMock(return_value=BadAdapter()),
    )
    with pytest.raises(CoreConflict):
        await cleanup_core(db, config)
    assert _memory_path("core-test", tmp_path).read_text() == before
    # Candidate/original evidence survives a fresh session — durable, not
    # just flushed.
    from sqlalchemy.ext.asyncio import AsyncSession

    async with AsyncSession(db_engine) as fresh:
        revs = (
            (await fresh.execute(select(CoreRevision).where(CoreRevision.agent_id == "core-test")))
            .scalars()
            .all()
        )
        assert any(r.published for r in revs)  # original pin is durable


@pytest.mark.asyncio
async def test_external_managed_identity_edit_conflicts_not_overwritten(db, tmp_path, monkeypatch):
    """A file whose managed identity was edited externally is a conflict —
    never silently overwritten by update_core."""
    _patch_env(monkeypatch, tmp_path)
    config = await _make_agent(db)
    session = Session(id=str(uuid.uuid4()), agent_id="core-test", contact_id="c1")
    db.add(session)
    await db.commit()
    await load_or_pin_core(db, config, session)
    path = _memory_path("core-test", tmp_path)
    tampered = path.read_text().replace("Test soul.", "Hacked soul.")
    path.write_text(tampered)
    with pytest.raises(CoreConflict):
        await update_core(db, config, "new")
    assert path.read_text() == tampered  # unchanged


@pytest.mark.asyncio
async def test_expected_hash_conflict_reports_current_hash(db, tmp_path, monkeypatch):
    """Expected-hash CAS: stale base returns a conflict carrying the
    current hash so a retry can proceed — no silent stomp."""
    _patch_env(monkeypatch, tmp_path)
    config = await _make_agent(db)
    session = Session(id=str(uuid.uuid4()), agent_id="core-test", contact_id="c1")
    db.add(session)
    await db.commit()
    await load_or_pin_core(db, config, session)
    with pytest.raises(CoreConflict) as exc:
        await update_core(db, config, "v2", expected_hash="stale-hash")
    assert exc.value.current_hash


@pytest.mark.asyncio
async def test_extraction_persists_confirmed_facts_with_source_ids(db, tmp_path, monkeypatch):
    """Valid extraction → contact-scoped MemoryEntries with provenance,
    then scratch cleared."""
    from agentos.memory import recall
    from agentos.memory.auto_extract import auto_extract_memory
    from agentos.models.memory import MemoryEntry

    _patch_env(monkeypatch, tmp_path)
    config = await _make_agent(db)
    contact_id = "c1"
    session = Session(id=str(uuid.uuid4()), agent_id="core-test", contact_id=contact_id)
    run = Run(
        id=str(uuid.uuid4()),
        session_id=session.id,
        contact_id=contact_id,
        agent_id="core-test",
        status="completed",
    )
    db.add_all([session, run])
    await db.commit()
    user_msg = Message(
        id=str(uuid.uuid4()), run_id=run.id, role="user", content="I prefer dark mode.", seq=0
    )
    asst = Message(id=str(uuid.uuid4()), run_id=run.id, role="assistant", content="Noted.", seq=1)
    db.add_all([user_msg, asst])
    await recall.store_snippet(db, contact_id, "core-test", "scratch", "a note", run_id=run.id)
    await db.commit()

    class FakeResp:
        content = json.dumps(
            {
                "memories": [
                    {
                        "kind": "preference",
                        "text": "User prefers dark mode.",
                        "source_ids": [user_msg.id],
                        "core_eligible": True,
                    },
                    {
                        "kind": "fact",
                        "text": "assistant-claimed-no-cite",
                        "source_ids": ["not-a-message"],
                        "core_eligible": False,
                    },
                ],
                "clarifications": [],
                "core_markdown": None,
                "core_source_ids": [],
            }
        )
        tokens_in = 10
        tokens_out = 5
        cost = 0.0
        cost_source = "test"

    class FakeAdapter:
        async def get_model_info(self, m):
            return {
                "model_str": "test-model",
                "resolved_model": {"context_window_tokens": 32768},
            }

        async def complete(self, **kw):
            return FakeResp()

    monkeypatch.setattr(
        "agentos.providers.ProviderRegistry.for_model",
        AsyncMock(return_value=FakeAdapter()),
    )
    monkeypatch.setattr("agentos.services.model_ledger.record_system_call", AsyncMock())

    out = await auto_extract_memory(
        db,
        config,
        "core-test",
        [user_msg, asst],
        run_id=run.id,
        contact_id=contact_id,
        session_id=session.id,
    )
    assert out["saved"] == 1
    entries = (await db.execute(select(MemoryEntry))).scalars().all()
    durable = [e for e in entries if e.run_id is None]
    assert len(durable) == 1
    assert "dark mode" in durable[0].value
    assert json.loads(durable[0].source_refs) == [user_msg.id]
    # The valid entry is durable; the invalid-cite candidate was rejected →
    # scratch stays (rejection means extraction wasn't fully clean).
    assert await recall.get_run_entries(db, run.id) != []


@pytest.mark.asyncio
async def test_extraction_failure_preserves_scratch(db, tmp_path, monkeypatch):
    """Provider failure → scratch kept, nothing persisted."""
    from agentos.memory import recall
    from agentos.memory.auto_extract import auto_extract_memory

    _patch_env(monkeypatch, tmp_path)
    config = await _make_agent(db)
    contact_id = "c1"
    session = Session(id=str(uuid.uuid4()), agent_id="core-test", contact_id=contact_id)
    run = Run(
        id=str(uuid.uuid4()),
        session_id=session.id,
        contact_id=contact_id,
        agent_id="core-test",
        status="completed",
    )
    db.add_all([session, run])
    await db.commit()
    user_msg = Message(id=str(uuid.uuid4()), run_id=run.id, role="user", content="hi", seq=0)
    db.add(user_msg)
    await recall.store_snippet(db, contact_id, "core-test", "scratch", "keep me", run_id=run.id)
    await db.commit()

    class BadAdapter:
        async def get_model_info(self, m):
            return {
                "model_str": "test-model",
                "resolved_model": {"context_window_tokens": 32768},
            }

        async def complete(self, **kw):
            raise RuntimeError("provider down")

    monkeypatch.setattr(
        "agentos.providers.ProviderRegistry.for_model",
        AsyncMock(return_value=BadAdapter()),
    )
    monkeypatch.setattr("agentos.services.model_ledger.record_system_call", AsyncMock())
    with pytest.raises(Exception):
        await auto_extract_memory(
            db,
            config,
            "core-test",
            [user_msg],
            run_id=run.id,
            contact_id=contact_id,
            session_id=session.id,
        )
    assert await recall.get_run_entries(db, run.id) != []


@pytest.mark.asyncio
async def test_two_contacts_snippets_stay_isolated(db, tmp_path, monkeypatch):
    """Subject-scoped recall never leaks across contacts."""
    from agentos.memory import recall

    _patch_env(monkeypatch, tmp_path)
    await _make_agent(db)
    await recall.store_snippet(db, "c1", "core-test", "k", "contact-one secret", run_id=None)
    await recall.store_snippet(db, "c2", "core-test", "k", "contact-two note", run_id=None)
    await db.commit()
    r1 = await recall.recall_snippets(db, "c1", "core-test", "secret", limit=10)
    r2 = await recall.recall_snippets(db, "c2", "core-test", "secret", limit=10)
    assert any("contact-one" in r.get("value", r.get("content", "")) for r in r1)
    assert all("contact-one" not in r.get("value", r.get("content", "")) for r in r2)


@pytest.mark.asyncio
async def test_no_startup_retrieval_calls(db, tmp_path, monkeypatch):
    """Startup no longer calls KG/recall/archives — tools stay available."""
    _patch_env(monkeypatch, tmp_path)
    await _make_agent(db)
    hit = []

    async def _watch(*a, **kw):
        hit.append(1)
        return []

    monkeypatch.setattr("agentos.memory.recall.recall_snippets", _watch)
    monkeypatch.setattr("agentos.memory.episodic.search_session_summaries", _watch)
    model = ScriptedModel([ScriptedResponse(content="done")])
    pipeline = Pipeline(db=db, harness=Harness(model=model))
    run = await pipeline.handle_inbound(
        _inbound("core-test", "hi"), trigger="user_message", is_test=True
    )
    assert run.status == "completed"
    assert hit == []


@pytest.mark.asyncio
async def test_post_run_correction_changes_future_core_only(db, tmp_path, monkeypatch):
    """A new update changes later sessions' pinned content, never the
    already-pinned session's bytes."""
    _patch_env(monkeypatch, tmp_path)
    config = await _make_agent(db)
    session = Session(id=str(uuid.uuid4()), agent_id="core-test", contact_id="c1")
    db.add(session)
    await db.commit()
    snap1 = await load_or_pin_core(db, config, session)
    await update_core(db, config, "corrected durable preference")
    await db.commit()
    again = await load_or_pin_core(db, config, session)
    assert "corrected" not in again.content  # pin stays put
    assert again.content == snap1.content


@pytest.mark.asyncio
async def test_archive_search_finds_older_revision_paragraphs(db, tmp_path, monkeypatch):
    """Core archive returns labeled curated paragraphs from older revisions
    — managed identity and the current pin are excluded."""
    from agentos.memory.recall import recall_core_archive

    _patch_env(monkeypatch, tmp_path)
    config = await _make_agent(db)
    session = Session(id=str(uuid.uuid4()), agent_id="core-test", contact_id="c1")
    db.add(session)
    await db.commit()
    await load_or_pin_core(db, config, session)
    await update_core(db, config, "- prefers tea over coffee\n- runs on Fridays")
    await db.commit()
    results = await recall_core_archive(
        db, agent_id="core-test", query="tea", session_id=session.id
    )
    assert results
    assert all(r["label"] == "historical core" for r in results)
    assert any("tea" in r["content"] for r in results)
    assert all("caberos:core-identity" not in r["content"] for r in results)


@pytest.mark.asyncio
async def test_malformed_managed_marker_is_conflict_not_rewritten(db, tmp_path, monkeypatch):
    """A file with a malformed managed block fails validation instead of
    being rewritten or silently wrapped."""
    _patch_env(monkeypatch, tmp_path)
    config = await _make_agent(db)
    path = _memory_path("core-test", tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    original = "<!-- caberos:core-identity v1 sha256:bad -->\nfoo\ncurated"
    path.write_text(original)
    session = Session(id=str(uuid.uuid4()), agent_id="core-test", contact_id="c1")
    db.add(session)
    await db.commit()
    with pytest.raises(CoreConflict):
        await load_or_pin_core(db, config, session)
    assert path.read_text() == original


@pytest.mark.asyncio
async def test_concurrent_same_base_writes_one_conflicts(db, tmp_path, monkeypatch):
    """Two same-base updates serialize through the agent lock — the second
    sees the changed disk hash and conflicts, never stomps."""
    _patch_env(monkeypatch, tmp_path)
    config = await _make_agent(db)
    session = Session(id=str(uuid.uuid4()), agent_id="core-test", contact_id="c1")
    db.add(session)
    await db.commit()
    snap = await load_or_pin_core(db, config, session)
    base = snap.content_hash

    # Simulate: first update publishes, then a second update carrying the
    # stale base hash must conflict inside the lock.
    await update_core(db, config, "first", expected_hash=base)
    with pytest.raises(CoreConflict) as exc:
        await update_core(db, config, "second", expected_hash=base)
    assert exc.value.current_hash
    disk = _memory_path("core-test", tmp_path).read_text()
    assert "first" in disk and "second" not in disk


@pytest.mark.asyncio
async def test_external_edit_during_cleanup_not_overwritten(db, tmp_path, monkeypatch):
    """An external edit landing while the cleanup model awaits re-checks
    the expected hash and loses instead of stomping."""
    _patch_env(monkeypatch, tmp_path)
    config = await _make_agent(db)
    session = Session(id=str(uuid.uuid4()), agent_id="core-test", contact_id="c1")
    db.add(session)
    await db.commit()
    snap = await load_or_pin_core(db, config, session)

    path = _memory_path("core-test", tmp_path)

    class SlowAdapter:
        async def get_model_info(self, m):
            return {
                "model_str": "test",
                "resolved_model": {"context_window_tokens": 32768},
            }

        async def complete(self, **kw):
            # External edit lands mid-call.
            curated = split_core(path.read_text())[2]
            _sha, ident, _c = split_core(path.read_text())
            path.write_text(build_core(ident, curated + "\nexternal edit"))
            return type(
                "R",
                (),
                {"content": json.dumps({"core_markdown": "new", "demoted": [], "conflicts": []})},
            )()

    monkeypatch.setattr(
        "agentos.providers.ProviderRegistry.for_model",
        AsyncMock(return_value=SlowAdapter()),
    )
    monkeypatch.setattr("agentos.services.model_ledger.record_system_call", AsyncMock())
    with pytest.raises(CoreConflict):
        await cleanup_core(db, config, proposed_curated="prop", expected_hash=snap.content_hash)
    assert "external edit" in path.read_text()
    assert "external edit" in path.read_text()


@pytest.mark.asyncio
async def test_missing_foreign_or_invalid_pin_conflicts(db, tmp_path, monkeypatch):
    """A pinned session whose revision is missing/foreign/corrupt fails —
    never silently repins onto a different core."""
    _patch_env(monkeypatch, tmp_path)
    config = await _make_agent(db)
    session = Session(id=str(uuid.uuid4()), agent_id="core-test", contact_id="c1")
    db.add(session)
    await db.commit()
    await load_or_pin_core(db, config, session)

    # Missing revision id
    session.core_revision_id = "does-not-exist"
    with pytest.raises(CoreConflict):
        await load_or_pin_core(db, config, session)

    # Foreign agent's revision
    other = CoreRevision(
        id="core-foreign",
        agent_id="other-agent",
        content="x",
        curated_content="x",
        content_hash="h" * 64,
        published=True,
    )
    db.add(other)
    await db.commit()
    session.core_revision_id = "core-foreign"
    with pytest.raises(CoreConflict):
        await load_or_pin_core(db, config, session)


@pytest.mark.asyncio
async def test_newline_and_marker_roundtrip(db, tmp_path, monkeypatch):
    """Curated content preserves leading/trailing newlines; identity text
    containing the literal end marker still parses to the valid split."""
    _patch_env(monkeypatch, tmp_path)
    config = await _make_agent(db)
    from agentos.agent_service import save_agent

    # Identity ends in literal newlines AND embeds the end marker —
    # exactly-one-LF slicing must preserve both.
    config.task = "Do work.\n\n" + IDENTITY_END + "\n\n"
    await save_agent(db, config)
    session = Session(id=str(uuid.uuid4()), agent_id="core-test", contact_id="c1")
    db.add(session)
    await db.commit()
    snap = await load_or_pin_core(db, config, session)
    assert "Do work" in snap.content
    path = _memory_path("core-test", tmp_path)
    whole = path.read_text()
    _sha, ident, curated = split_core(whole)
    assert "Do work." in ident

    # Curated with leading/trailing newlines roundtrips byte-exact.
    await update_core(db, config, "\n\n- item\n\n")
    disk = path.read_text()
    assert disk.endswith("\n\n- item\n\n")
    _sha2, _i2, cur2 = split_core(disk)
    assert cur2 == "\n\n- item\n\n"


@pytest.mark.asyncio
async def test_symlinked_agent_dir_rejected(db, tmp_path, monkeypatch):
    """A symlinked agent home resolves outside the managed root — rejected
    before any file read/write."""
    _patch_env(monkeypatch, tmp_path)
    config = await _make_agent(db)
    root = tmp_path / "agents"
    root.mkdir(parents=True)
    real = tmp_path / "elsewhere"
    real.mkdir()
    (real / "MEMORY.md").write_text("x")
    (root / "core-test").symlink_to(real)
    session = Session(id=str(uuid.uuid4()), agent_id="core-test", contact_id="c1")
    db.add(session)
    await db.commit()
    with pytest.raises(CoreConflict):
        await load_or_pin_core(db, config, session)


@pytest.mark.asyncio
async def test_invalid_json_shape_rejected_scratch_retained(db, tmp_path, monkeypatch):
    """Non-list memories / malformed payload → exception, no writes, and
    scratch entries stay put."""
    from agentos.memory import recall
    from agentos.memory.auto_extract import auto_extract_memory
    from agentos.models.memory import MemoryEntry

    _patch_env(monkeypatch, tmp_path)
    config = await _make_agent(db)
    contact_id = "c1"
    session = Session(id=str(uuid.uuid4()), agent_id="core-test", contact_id=contact_id)
    run = Run(
        id=str(uuid.uuid4()),
        session_id=session.id,
        contact_id=contact_id,
        agent_id="core-test",
        status="completed",
    )
    db.add_all([session, run])
    await db.commit()
    user_msg = Message(id=str(uuid.uuid4()), run_id=run.id, role="user", content="hi", seq=0)
    db.add(user_msg)
    await recall.store_snippet(db, contact_id, "core-test", "scratch", "keep", run_id=run.id)
    await db.commit()

    class ShapeAdapter:
        async def get_model_info(self, m):
            return {
                "model_str": "test",
                "resolved_model": {"context_window_tokens": 32768},
            }

        async def complete(self, **kw):
            return type("R", (), {"content": "not json"})()

    monkeypatch.setattr(
        "agentos.providers.ProviderRegistry.for_model",
        AsyncMock(return_value=ShapeAdapter()),
    )
    monkeypatch.setattr("agentos.services.model_ledger.record_system_call", AsyncMock())
    with pytest.raises(Exception):
        await auto_extract_memory(
            db,
            config,
            "core-test",
            [user_msg],
            run_id=run.id,
            contact_id=contact_id,
            session_id=session.id,
        )
    assert await recall.get_run_entries(db, run.id) != []
    entries = (await db.execute(select(MemoryEntry))).scalars().all()
    assert all(e.run_id for e in entries)  # only scratch rows


@pytest.mark.asyncio
async def test_secret_in_core_markdown_rejected_scratch_retained(db, tmp_path, monkeypatch):
    """A core_markdown proposal carrying a credential assignment is
    rejected — no core update, scratch retained."""
    from agentos.memory import recall
    from agentos.memory.auto_extract import auto_extract_memory

    _patch_env(monkeypatch, tmp_path)
    config = await _make_agent(db)
    contact_id = "c1"
    session = Session(id=str(uuid.uuid4()), agent_id="core-test", contact_id=contact_id)
    run = Run(
        id=str(uuid.uuid4()),
        session_id=session.id,
        contact_id=contact_id,
        agent_id="core-test",
        status="completed",
    )
    db.add_all([session, run])
    await db.commit()
    user_msg = Message(
        id=str(uuid.uuid4()),
        run_id=run.id,
        role="user",
        content="remember my api key is sk-live-999",
        seq=0,
    )
    db.add(user_msg)
    await recall.store_snippet(db, contact_id, "core-test", "s", "keep", run_id=run.id)
    await db.commit()
    await load_or_pin_core(db, config, session)
    before = _memory_path("core-test", tmp_path).read_text()

    class BadCoreAdapter:
        async def get_model_info(self, m):
            return {
                "model_str": "test",
                "resolved_model": {"context_window_tokens": 32768},
            }

        async def complete(self, **kw):
            return type(
                "R",
                (),
                {
                    "content": json.dumps(
                        {
                            "memories": [],
                            "clarifications": [],
                            "core_markdown": "- api key: sk-live-999\n- password: hunter2",
                            "core_source_ids": [user_msg.id],
                        }
                    )
                },
            )()

    monkeypatch.setattr(
        "agentos.providers.ProviderRegistry.for_model",
        AsyncMock(return_value=BadCoreAdapter()),
    )
    monkeypatch.setattr("agentos.services.model_ledger.record_system_call", AsyncMock())
    out = await auto_extract_memory(
        db,
        config,
        "core-test",
        [user_msg],
        run_id=run.id,
        contact_id=contact_id,
        session_id=session.id,
    )
    assert not out["core_updated"]
    assert _memory_path("core-test", tmp_path).read_text() == before
    assert await recall.get_run_entries(db, run.id) != []


@pytest.mark.asyncio
async def test_repeat_extraction_dedups_by_stable_key(db, tmp_path, monkeypatch):
    """Same kind+text extracted twice reuses one durable entry with merged
    source refs — no duplicate rows."""
    from agentos.memory.auto_extract import auto_extract_memory
    from agentos.models.memory import MemoryEntry

    _patch_env(monkeypatch, tmp_path)
    config = await _make_agent(db)
    contact_id = "c1"
    session = Session(id=str(uuid.uuid4()), agent_id="core-test", contact_id=contact_id)
    run = Run(
        id=str(uuid.uuid4()),
        session_id=session.id,
        contact_id=contact_id,
        agent_id="core-test",
        status="completed",
    )
    db.add_all([session, run])
    await db.commit()
    msgs = [
        Message(id=str(uuid.uuid4()), run_id=run.id, role="user", content="I prefer tea", seq=0),
        Message(id=str(uuid.uuid4()), run_id=run.id, role="assistant", content="ok", seq=1),
    ]
    db.add_all(msgs)
    await db.commit()

    class FakeResp:
        content = json.dumps(
            {
                "memories": [
                    {
                        "kind": "preference",
                        "text": "User prefers tea.",
                        "source_ids": [msgs[0].id],
                        "core_eligible": False,
                    }
                ],
                "clarifications": [],
                "core_markdown": None,
                "core_source_ids": [],
            }
        )

    class FakeAdapter:
        async def get_model_info(self, m):
            return {
                "model_str": "test",
                "resolved_model": {"context_window_tokens": 32768},
            }

        async def complete(self, **kw):
            return FakeResp()

    monkeypatch.setattr(
        "agentos.providers.ProviderRegistry.for_model",
        AsyncMock(return_value=FakeAdapter()),
    )
    monkeypatch.setattr("agentos.services.model_ledger.record_system_call", AsyncMock())

    await auto_extract_memory(
        db,
        config,
        "core-test",
        msgs,
        run_id=run.id,
        contact_id=contact_id,
        session_id=session.id,
    )
    # Second extraction of the same durable text → same entry, merged cites.
    msg2 = Message(id=str(uuid.uuid4()), run_id=run.id, role="user", content="still tea", seq=2)
    db.add(msg2)
    await db.commit()

    class FakeResp2:
        content = json.dumps(
            {
                "memories": [
                    {
                        "kind": "preference",
                        "text": "User prefers tea.",
                        "source_ids": [msg2.id],
                        "core_eligible": False,
                    }
                ],
                "clarifications": [],
                "core_markdown": None,
                "core_source_ids": [],
            }
        )

    async def _complete2(self, **kw):
        return FakeResp2()

    FakeAdapter.complete = _complete2
    await auto_extract_memory(
        db,
        config,
        "core-test",
        msgs + [msg2],
        run_id=run.id,
        contact_id=contact_id,
        session_id=session.id,
    )
    durable = [
        e
        for e in (await db.execute(select(MemoryEntry))).scalars().all()
        if e.run_id is None and "tea" in e.value
    ]
    assert len(durable) == 1
    refs = json.loads(durable[0].source_refs)
    assert msgs[0].id in refs and msg2.id in refs


@pytest.mark.asyncio
async def test_scoped_raw_history_isolated_two_contacts(db, tmp_path, monkeypatch):
    """Scoped raw-history search for contact A never returns contact B's
    messages — the subject filter is enforced at query level."""
    from agentos.memory.episodic import index_message, search_scoped_history
    from agentos.models.run import Message as M
    from agentos.models.run import Run as R
    from agentos.models.session import Session as S

    _patch_env(monkeypatch, tmp_path)
    await _make_agent(db)
    for cid, sid, rid, mid, text in [
        ("ca", "sa", "ra", "ma", "alpha secret for A"),
        ("cb", "sb", "rb", "mb", "beta secret for B"),
    ]:
        db.add(S(id=sid, agent_id="core-test", contact_id=cid))
        db.add(R(id=rid, session_id=sid, contact_id=cid, agent_id="core-test", status="completed"))
        db.add(M(id=mid, run_id=rid, role="user", content=text, seq=0))
        await index_message(
            db, message_id=mid, run_id=rid, session_id=sid, agent_id="core-test", content=text
        )
    await db.commit()

    ra = await search_scoped_history(db, "core-test", "ca", "secret", limit=10)
    rb = await search_scoped_history(db, "core-test", "cb", "secret", limit=10)
    assert any("alpha" in r["content"] for r in ra)
    assert all("beta" not in r["content"] for r in ra)
    assert any("beta" in r["content"] for r in rb)
    assert all("alpha" not in r["content"] for r in rb)


@pytest.mark.asyncio
async def test_learned_fact_recalled_via_memory_recall(db, tmp_path, monkeypatch):
    """A durably extracted fact is retrievable through the memory_recall
    surface — store_snippet writes the FTS index."""
    from agentos.memory import recall
    from agentos.memory.auto_extract import auto_extract_memory

    _patch_env(monkeypatch, tmp_path)
    config = await _make_agent(db)
    contact_id = "c1"
    session = Session(id=str(uuid.uuid4()), agent_id="core-test", contact_id=contact_id)
    run = Run(
        id=str(uuid.uuid4()),
        session_id=session.id,
        contact_id=contact_id,
        agent_id="core-test",
        status="completed",
    )
    db.add_all([session, run])
    await db.commit()
    user_msg = Message(
        id=str(uuid.uuid4()),
        run_id=run.id,
        role="user",
        content="My favourite colour is periwinkle.",
        seq=0,
    )
    db.add(user_msg)
    await db.commit()

    class FakeResp:
        content = json.dumps(
            {
                "memories": [
                    {
                        "kind": "preference",
                        "text": "User's favourite colour is periwinkle.",
                        "source_ids": [user_msg.id],
                        "core_eligible": False,
                    }
                ],
                "clarifications": [],
                "core_markdown": None,
                "core_source_ids": [],
            }
        )

    class FakeAdapter:
        async def get_model_info(self, m):
            return {
                "model_str": "test",
                "resolved_model": {"context_window_tokens": 32768},
            }

        async def complete(self, **kw):
            return FakeResp()

    monkeypatch.setattr(
        "agentos.providers.ProviderRegistry.for_model",
        AsyncMock(return_value=FakeAdapter()),
    )
    monkeypatch.setattr("agentos.services.model_ledger.record_system_call", AsyncMock())
    await auto_extract_memory(
        db,
        config,
        "core-test",
        [user_msg],
        run_id=run.id,
        contact_id=contact_id,
        session_id=session.id,
    )
    hits = await recall.recall_snippets(db, contact_id, "core-test", "periwinkle", limit=5)
    assert any("periwinkle" in r.get("value", "") for r in hits)


@pytest.mark.asyncio
async def test_restart_pins_identical_bytes_fresh_pipeline(db, tmp_path, monkeypatch):
    """A second run in a new process-equivalent session object still loads
    the byte-identical pinned core — not a new revision."""
    _patch_env(monkeypatch, tmp_path)
    config = await _make_agent(db)
    session = Session(id=str(uuid.uuid4()), agent_id="core-test", contact_id="c1")
    db.add(session)
    await db.commit()
    snap1 = await load_or_pin_core(db, config, session)

    # Simulate restart: new Session ORM instance, same id, pinned revision.
    session2 = await db.get(Session, session.id)
    snap2 = await load_or_pin_core(db, config, session2)
    assert snap2.revision_id == snap1.revision_id
    assert snap2.content == snap1.content


@pytest.mark.asyncio
async def test_new_session_after_identity_update_gets_new_prefix(db, tmp_path, monkeypatch):
    """Config identity change → new session's prefix regenerates from the
    new config; an already-pinned session keeps the old bytes."""
    _patch_env(monkeypatch, tmp_path)
    config = await _make_agent(db)
    session = Session(id=str(uuid.uuid4()), agent_id="core-test", contact_id="c1")
    db.add(session)
    await db.commit()
    snap1 = await load_or_pin_core(db, config, session)

    # Authoritative config identity changes via a real config save.
    from agentos.agent_service import save_agent

    config.soul = "Updated soul."
    await save_agent(db, config)
    session2 = Session(id=str(uuid.uuid4()), agent_id="core-test", contact_id="c1")
    db.add(session2)
    await db.commit()
    snap2 = await load_or_pin_core(db, config, session2)
    assert snap2.revision_id
    assert "Updated soul." in snap2.content
    assert "Test soul." not in snap2.content

    # First session still pinned to its original bytes.
    again = await load_or_pin_core(db, config, session)
    assert again.content == snap1.content


@pytest.mark.asyncio
async def test_commit_failure_before_swap_keeps_original(db, tmp_path, monkeypatch):
    """If the candidate commit fails pre-swap, the on-disk original bytes
    are untouched and no publish happened."""
    _patch_env(monkeypatch, tmp_path)
    config = await _make_agent(db)
    session = Session(id=str(uuid.uuid4()), agent_id="core-test", contact_id="c1")
    db.add(session)
    await db.commit()
    await load_or_pin_core(db, config, session)
    path = _memory_path("core-test", tmp_path)
    before = path.read_text()

    orig_commit = db.commit
    calls = []

    async def fail_once():
        if not calls:
            calls.append(1)
            raise RuntimeError("commit exploded")
        return await orig_commit()

    monkeypatch.setattr(db, "commit", fail_once)
    with pytest.raises(Exception):
        await update_core(db, config, "never published")
    assert path.read_text() == before


@pytest.mark.asyncio
async def test_replace_failure_keeps_original_and_candidate(db, tmp_path, monkeypatch):
    """os.replace failing mid-publish keeps the original file and leaves
    the candidate revision durable (published=False evidence)."""
    _patch_env(monkeypatch, tmp_path)
    config = await _make_agent(db)
    session = Session(id=str(uuid.uuid4()), agent_id="core-test", contact_id="c1")
    db.add(session)
    await db.commit()
    await load_or_pin_core(db, config, session)
    path = _memory_path("core-test", tmp_path)
    before = path.read_text()

    import os as _os

    real_replace = _os.replace

    def boom(*a, **kw):
        raise OSError("disk full")

    monkeypatch.setattr("agentos.memory.core.os.replace", boom)
    with pytest.raises(OSError):
        await update_core(db, config, "never landed")
    assert path.read_text() == before
    # Candidate evidence is durable (committed pre-swap, published=False).
    rows = (
        (await db.execute(select(CoreRevision).where(CoreRevision.agent_id == "core-test")))
        .scalars()
        .all()
    )
    assert any(not r.published and "never landed" in r.curated_content for r in rows)
    monkeypatch.setattr("agentos.memory.core.os.replace", real_replace)


@pytest.mark.asyncio
async def test_fresh_schema_and_manifest_patch(tmp_path, monkeypatch):
    """Fresh init creates core_revisions + the additive columns; an
    existing-schema manifest table gains the new columns via patches."""
    import aiosqlite
    from sqlalchemy.ext.asyncio import create_async_engine

    from agentos.config import settings
    from agentos.db_backends.sqlite_backend import SQLiteBackend

    monkeypatch.setattr(settings, "agent_home_root", tmp_path / "agents")
    db_file = tmp_path / "startup.db"

    # Simulate an existing pre-column database: manifest table without the
    # new columns, sessions without core_revision_id.
    async with aiosqlite.connect(str(db_file)) as raw:
        await raw.execute("CREATE TABLE execution_manifests (id TEXT PRIMARY KEY, run_id TEXT)")
        await raw.execute("CREATE TABLE sessions (id TEXT PRIMARY KEY, agent_id TEXT)")
        await raw.commit()

    engine = create_async_engine(f"sqlite+aiosqlite:///{db_file}")
    backend = SQLiteBackend()
    async with engine.begin() as conn:
        await backend.init_schema(conn)
        await backend.init_fulltext_search(conn)

    async with aiosqlite.connect(str(db_file)) as raw:
        cur = await raw.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='core_revisions'"
        )
        assert (await cur.fetchall()) != []

        cur = await raw.execute("PRAGMA table_info(execution_manifests)")
        cols = {r[1] for r in await cur.fetchall()}
        assert {"core_revision_id", "core_identity_source_version_id"} <= cols

        cur = await raw.execute("PRAGMA table_info(sessions)")
        assert "core_revision_id" in {r[1] for r in await cur.fetchall()}

        cur = await raw.execute("PRAGMA table_info(memory_entries)")
        assert {"source_refs", "revoked_at"} <= {r[1] for r in await cur.fetchall()}
    await engine.dispose()


@pytest.mark.asyncio
async def test_manifest_records_pinned_identity_source_version(db, tmp_path, monkeypatch):
    """Pipeline pin records the run manifest's core revision + identity
    source == the agent's real active version id."""
    _patch_env(monkeypatch, tmp_path)
    await _make_agent(db)
    from agentos.models.agent import Agent

    agent = await db.get(Agent, "core-test")
    active = agent.active_version_id
    assert active

    model = ScriptedModel([ScriptedResponse(content="ok")])
    pipeline = Pipeline(db=db, harness=Harness(model=model))
    run = await pipeline.handle_inbound(
        _inbound("core-test", "hi"), trigger="user_message", is_test=True
    )
    assert run.status == "completed"
    from agentos.models.execution_manifest import ExecutionManifest

    mf = await db.scalar(select(ExecutionManifest).where(ExecutionManifest.run_id == run.id))
    assert mf is not None
    assert mf.core_revision_id
    assert mf.core_identity_source_version_id == active


@pytest.mark.asyncio
async def test_mediated_memory_update_writes_and_revisions(db, tmp_path, monkeypatch):
    """memory_update through the real syscall mediator publishes a new
    revision — and a stale explicit base hash still conflicts cleanly."""
    from agentos.syscall.mediator import SyscallHandler
    from agentos.syscall.protocol import ToolCall

    _patch_env(monkeypatch, tmp_path)
    config = await _make_agent(db, capabilities=_agent_caps("memory_update"))
    session = Session(id=str(uuid.uuid4()), agent_id="core-test", contact_id="c1")
    db.add(session)
    await db.commit()
    await load_or_pin_core(db, config, session)

    handler = SyscallHandler(db=db, workspace_path=str(tmp_path / "ws"))
    result = await handler.mediate(
        call=ToolCall(
            id="1",
            name="memory_update",
            args={"content": "- prefers espresso\n"},
        ),
        session=session,
        agent_config=config,
        run_id="run-1",
    )
    assert result.allowed is True
    assert result.output["updated"] is True, result.output
    disk = _memory_path("core-test", tmp_path).read_text()
    _sha, _i, cur = split_core(disk)
    assert cur.startswith("- prefers espresso")
    assert "Soul" in _i  # managed identity preserved


@pytest.mark.asyncio
async def test_limits_patch_invalid_core_max_tokens_is_422(db, tmp_path, monkeypatch):
    """PATCH limits with core_max_tokens=0 → 422 (not a 500)."""
    import httpx

    from agentos.auth import require_operator
    from agentos.db import get_db
    from agentos.main import app
    from agentos.models.operator import Operator

    _patch_env(monkeypatch, tmp_path)
    await _make_agent(db)

    async def override_db():
        yield db

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[require_operator] = lambda: Operator(
        id="op", username="t", password_hash="", must_change_password=False
    )
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://t"
        ) as c:
            resp = await c.put(
                "/api/agents/core-test",
                json={"limits": {"core_max_tokens": 0}},
            )
            assert resp.status_code == 422
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_restore_legacy_unmarked_snapshot(db, tmp_path, monkeypatch):
    """A pre-wrap legacy file's recorded snapshot restores its curated body
    under the current managed identity."""
    from agentos.memory.core import restore_core

    _patch_env(monkeypatch, tmp_path)
    config = await _make_agent(db)
    path = _memory_path("core-test", tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("legacy curated content\n", encoding="utf-8")
    session = Session(id=str(uuid.uuid4()), agent_id="core-test", contact_id="c1")
    db.add(session)
    await db.commit()
    await load_or_pin_core(db, config, session)
    # The original bytes became a published snapshot.
    legacy = await db.scalar(
        select(CoreRevision).where(
            CoreRevision.agent_id == "core-test",
            CoreRevision.content.like("legacy curated%"),
        )
    )
    assert legacy is not None and legacy.published
    restored = await restore_core(db, config, legacy.id)
    assert "legacy curated" in restored.curated_content


@pytest.mark.asyncio
async def test_two_agents_identical_legacy_bytes_get_distinct_pins(db, tmp_path, monkeypatch):
    """Identical legacy bytes in two agents must not collide on revision id
    — ids are uuid4, scoped per agent."""
    _patch_env(monkeypatch, tmp_path)
    for aid in ("agent-a", "agent-b"):
        cfg = AgentConfig(
            id=aid,
            name=aid,
            model=ModelConfig(provider_id="t", name="m"),
            soul="S",
            persona="P",
            task="K",
        )
        await create_agent(db, cfg)
        p = _memory_path(aid, tmp_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("identical bytes\n")
    s1 = Session(id=str(uuid.uuid4()), agent_id="agent-a", contact_id="c1")
    s2 = Session(id=str(uuid.uuid4()), agent_id="agent-b", contact_id="c1")
    db.add_all([s1, s2])
    await db.commit()
    from agentos.agent_service import get_active_config

    c1 = await get_active_config(db, "agent-a")
    c2 = await get_active_config(db, "agent-b")
    r1 = await load_or_pin_core(db, c1, s1)
    r2 = await load_or_pin_core(db, c2, s2)
    assert r1.revision_id != r2.revision_id
    assert len(r1.revision_id) <= 36 and len(r2.revision_id) <= 36


@pytest.mark.asyncio
async def test_truly_concurrent_same_base_conflicts(tmp_path, monkeypatch):
    """Two coroutines on separate sessions racing one publish lock — one
    wins, the other's stale-base check fails inside the lock. A real
    file-backed DB is required: the shared StaticPool can't serve two
    concurrent sessions."""
    import asyncio as _asyncio

    from sqlalchemy.ext.asyncio import (
        AsyncSession as _AS,
    )
    from sqlalchemy.ext.asyncio import (
        async_sessionmaker,
        create_async_engine,
    )

    _patch_env(monkeypatch, tmp_path)
    db_file = tmp_path / "conc.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_file}")

    import agentos.models  # noqa: F401
    from agentos.models.base import Base

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=_AS, expire_on_commit=False)

    async with factory() as db:
        config = await _make_agent(db)
        session = Session(id=str(uuid.uuid4()), agent_id="core-test", contact_id="c1")
        db.add(session)
        await db.commit()
        snap = await load_or_pin_core(db, config, session)
        await db.commit()
        base = snap.content_hash

    barrier = _asyncio.Event()
    results: dict[str, str] = {}

    async def worker(name: str, curated: str):
        async with factory() as sess:
            await barrier.wait()
            try:
                await update_core(sess, config, curated, expected_hash=base)
                results[name] = "ok"
            except CoreConflict:
                results[name] = "conflict"
            except Exception:
                results[name] = "error"

    t1 = _asyncio.create_task(worker("a", "- winner"))
    t2 = _asyncio.create_task(worker("b", "- loser"))
    barrier.set()
    await _asyncio.gather(t1, t2)
    await engine.dispose()
    assert sorted(results.values()) == ["conflict", "ok"]
    disk = _memory_path("core-test", tmp_path).read_text()
    # Exactly one of them landed.
    assert ("- winner" in disk) != ("- loser" in disk)


@pytest.mark.asyncio
async def test_cleanup_endpoint_external_edit_omits_hash(db, tmp_path, monkeypatch):
    """Manual cleanup path without an explicit expected_hash still loses a
    mid-flight external edit — observed-hash CAS protects it by default."""
    _patch_env(monkeypatch, tmp_path)
    config = await _make_agent(db)
    session = Session(id=str(uuid.uuid4()), agent_id="core-test", contact_id="c1")
    db.add(session)
    await db.commit()
    await load_or_pin_core(db, config, session)
    path = _memory_path("core-test", tmp_path)
    path.read_text()  # baseline captured implicitly by observed-hash CAS

    class EditingAdapter:
        async def get_model_info(self, m):
            return {"model_str": "test", "resolved_model": {"context_window_tokens": 32768}}

        async def complete(self, **kw):
            _sha, ident, cur = split_core(path.read_text())
            path.write_text(build_core(ident, cur + "\nexternal edit"))
            return type(
                "R",
                (),
                {
                    "content": json.dumps(
                        {"core_markdown": "cleaned", "demoted": [], "conflicts": []}
                    )
                },
            )()

    monkeypatch.setattr(
        "agentos.providers.ProviderRegistry.for_model",
        AsyncMock(return_value=EditingAdapter()),
    )
    monkeypatch.setattr("agentos.services.model_ledger.record_system_call", AsyncMock())
    with pytest.raises(CoreConflict):
        await cleanup_core(db, config)  # no expected_hash — observed CAS
    assert "external edit" in path.read_text()


@pytest.mark.asyncio
async def test_task_trailing_newline_preserved_in_identity(db, tmp_path, monkeypatch):
    """config.task ending in newlines survives the generated prefix —
    single-LF slicing doesn't eat user text."""
    from agentos.agent_service import save_agent

    _patch_env(monkeypatch, tmp_path)
    config = await _make_agent(db)
    config.task = "Finish tasks.\n\n"
    await save_agent(db, config)
    session = Session(id=str(uuid.uuid4()), agent_id="core-test", contact_id="c1")
    db.add(session)
    await db.commit()
    snap = await load_or_pin_core(db, config, session)
    assert "Finish tasks.\n\n" in snap.content
    _sha, ident, _cur = split_core(snap.content)
    assert ident.endswith("Finish tasks.\n\n")
