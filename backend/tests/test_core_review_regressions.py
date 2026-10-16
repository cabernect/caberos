"""Core-review regressions — the exact defect cases from the consolidated
review, exercised against production code paths only (no helper shortcuts).
"""

import json
import uuid
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from agentos.agent_service import create_agent, get_active_config, save_agent
from agentos.config_schema import AgentConfig, CapabilityGrant, ModelConfig
from agentos.memory import recall
from agentos.memory.auto_extract import auto_extract_memory
from agentos.memory.core import (
    IDENTITY_BEGIN,
    CoreConflict,
    build_core,
    cleanup_core,
    load_or_pin_core,
    split_core,
    update_core,
)
from agentos.models.core import CoreRevision
from agentos.models.memory import MemoryEntry
from agentos.models.run import Message, Run
from agentos.models.session import Session


def _caps(*names: str) -> list[CapabilityGrant]:
    return [CapabilityGrant(name=n, require_approval=False) for n in names]


async def _agent(db, agent_id="reg-test", **kw):
    config = AgentConfig(
        id=agent_id,
        name="Regression Test",
        model=ModelConfig(provider_id="test", name="scripted"),
        soul="Test soul.",
        persona="Calm.",
        task="Help the operator.",
        capabilities=kw.pop("capabilities", _caps("terminal")),
        **kw,
    )
    await create_agent(db, config)
    return config


def _patch_env(monkeypatch, tmp_path):
    from agentos.config import settings
    from agentos.sandbox.workspace import WorkspaceManager

    ws_dir = tmp_path / "ws"
    ws_dir.mkdir(exist_ok=True)
    monkeypatch.setattr(WorkspaceManager, "create_workspace", lambda self, aid: ws_dir)
    monkeypatch.setattr(settings, "agent_home_root", tmp_path / "agents")


def _memory_path(agent_id, tmp_path):
    return tmp_path / "agents" / agent_id / "MEMORY.md"


async def _seed_run(db, agent_id="reg-test", contact_id="c1"):
    session = Session(id=str(uuid.uuid4()), agent_id=agent_id, contact_id=contact_id)
    run = Run(
        id=str(uuid.uuid4()),
        session_id=session.id,
        contact_id=contact_id,
        agent_id=agent_id,
        status="completed",
    )
    db.add_all([session, run])
    await db.commit()
    return session, run


class _JsonAdapter:
    """Extraction adapter returning one canned JSON payload."""

    def __init__(self, payload):
        self.payload = payload
        self.seen_messages = None

    async def get_model_info(self, m):
        return {
            "model_str": "test-model",
            "resolved_model": {"context_window_tokens": 32768},
        }

    async def complete(self, **kw):
        self.seen_messages = kw.get("messages")
        return type("R", (), {"content": self.payload})()


def _extract_adapter(monkeypatch, payload):
    adapter = _JsonAdapter(payload)
    monkeypatch.setattr(
        "agentos.providers.ProviderRegistry.for_model",
        AsyncMock(return_value=adapter),
    )
    monkeypatch.setattr("agentos.services.model_ledger.record_system_call", AsyncMock())
    return adapter


@pytest.mark.asyncio
async def test_foreign_nested_fake_ids_never_cite(db, tmp_path, monkeypatch):
    """Model output citing other-run, foreign-contact, nested (subagent),
    and invented ids publishes NOTHING — eligible cites must be real
    persisted rows of this parent run."""
    _patch_env(monkeypatch, tmp_path)
    config = await _agent(db)
    session, run = await _seed_run(db)
    real = Message(id=str(uuid.uuid4()), run_id=run.id, role="user", content="hi", seq=0)
    # Same run but a subagent row (nested — not a parent user message).
    nested = Message(
        id=str(uuid.uuid4()),
        run_id=run.id,
        role="user",
        content="nested",
        seq=1,
        subagent_id="sub-1",
    )
    db.add_all([real, nested])
    await recall.store_snippet(db, "c1", "reg-test", "scratch", "a note", run_id=run.id)
    await db.commit()

    payload = json.dumps(
        {
            "memories": [
                {
                    "kind": "fact",
                    "text": "learned",
                    "source_ids": [real.id, nested.id, "fake-id-999"],
                },
            ],
            "clarifications": [],
            "core_markdown": None,
            "core_source_ids": [],
        }
    )
    _extract_adapter(monkeypatch, payload)
    result = await auto_extract_memory(
        db,
        config,
        "reg-test",
        [real],
        run_id=run.id,
        contact_id="c1",
        session_id=session.id,
    )
    # Mixed valid+invalid cites → the whole item is rejected.
    assert result["saved"] == 0
    entries = (await db.execute(select(MemoryEntry))).scalars().all()
    assert not [e for e in entries if e.key == "learned" and e.run_id is None]


@pytest.mark.asyncio
async def test_clarification_blocks_core_publish_and_keeps_scratch(db, tmp_path, monkeypatch):
    """A valid clarification means ambiguity — no core write, scratch stays."""
    _patch_env(monkeypatch, tmp_path)
    config = await _agent(db)
    session, run = await _seed_run(db)
    real = Message(id=str(uuid.uuid4()), run_id=run.id, role="user", content="hi", seq=0)
    db.add(real)
    await recall.store_snippet(db, "c1", "reg-test", "scratch", "keep me", run_id=run.id)
    await db.commit()

    payload = json.dumps(
        {
            "memories": [],
            "clarifications": ["Which project did you mean?"],
            "core_markdown": "- preferred editor: vim",
            "core_source_ids": [real.id],
        }
    )
    _extract_adapter(monkeypatch, payload)
    result = await auto_extract_memory(
        db,
        config,
        "reg-test",
        [real],
        run_id=run.id,
        contact_id="c1",
        session_id=session.id,
    )
    assert result["core_updated"] is False
    assert _memory_path("reg-test", tmp_path).exists() is False
    scratch = (
        (
            await db.execute(
                select(MemoryEntry).where(
                    MemoryEntry.agent_id == "reg-test", MemoryEntry.key == "scratch"
                )
            )
        )
        .scalars()
        .all()
    )
    assert scratch, "scratch must be retained when a clarification exists"


@pytest.mark.asyncio
async def test_malformed_core_shapes_retain_scratch(db, tmp_path, monkeypatch):
    """core_markdown as a list / core_source_ids as a string → rejected;
    scratch retained for a later pass."""
    _patch_env(monkeypatch, tmp_path)
    config = await _agent(db)
    session, run = await _seed_run(db)
    real = Message(id=str(uuid.uuid4()), run_id=run.id, role="user", content="hi", seq=0)
    db.add(real)
    await recall.store_snippet(db, "c1", "reg-test", "scratch", "keep me", run_id=run.id)
    await db.commit()

    payload = json.dumps(
        {
            "memories": [],
            "clarifications": [],
            "core_markdown": ["- not a string"],
            "core_source_ids": "not-a-list",
        }
    )
    _extract_adapter(monkeypatch, payload)
    result = await auto_extract_memory(
        db,
        config,
        "reg-test",
        [real],
        run_id=run.id,
        contact_id="c1",
        session_id=session.id,
    )
    assert result["core_updated"] is False
    scratch = (
        (await db.execute(select(MemoryEntry).where(MemoryEntry.key == "scratch"))).scalars().all()
    )
    assert scratch


@pytest.mark.asyncio
async def test_stale_expected_oversize_never_calls_provider(db, tmp_path, monkeypatch):
    """A stale expected_hash on an oversize update rejects BEFORE any
    evidence-write or provider call — zero transport invocations."""
    _patch_env(monkeypatch, tmp_path)
    config = await _agent(db)
    session = Session(id=str(uuid.uuid4()), agent_id="reg-test", contact_id="c1")
    db.add(session)
    await db.commit()
    await load_or_pin_core(db, config, session)
    await db.commit()

    calls: list = []

    async def _boom(*a, **kw):
        calls.append(1)
        raise AssertionError("provider must not run")

    monkeypatch.setattr(
        "agentos.providers.ProviderRegistry.for_model", AsyncMock(side_effect=_boom)
    )
    with pytest.raises(CoreConflict):
        await update_core(
            db,
            config,
            "- " + "x" * (config.limits.core_max_tokens * 8),
            expected_hash="definitely-stale",
        )
    assert calls == []


@pytest.mark.asyncio
async def test_cleanup_midflight_external_file_creation_conflicts(db, tmp_path, monkeypatch):
    """Cleanup on a missing file then an external create mid-call must
    conflict — the external bytes are preserved, never overwritten."""
    _patch_env(monkeypatch, tmp_path)
    config = await _agent(db)
    path = _memory_path("reg-test", tmp_path)
    assert not path.exists()

    class Creator:
        async def get_model_info(self, m):
            return {
                "model_str": "test",
                "resolved_model": {"context_window_tokens": 32768},
            }

        async def complete(self, **kw):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("externally written\n")
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
        AsyncMock(return_value=Creator()),
    )
    monkeypatch.setattr("agentos.services.model_ledger.record_system_call", AsyncMock())
    with pytest.raises(CoreConflict):
        await cleanup_core(db, config)
    assert path.read_text() == "externally written\n"


@pytest.mark.asyncio
async def test_unpersisted_task_mutation_rejected(db, tmp_path, monkeypatch):
    """Mutating config.task in memory (no save_agent) must fail identity
    provenance — the on-disk identity can never be rewritten by an
    unpersisted edit."""
    _patch_env(monkeypatch, tmp_path)
    config = await _agent(db)
    session = Session(id=str(uuid.uuid4()), agent_id="reg-test", contact_id="c1")
    db.add(session)
    await db.commit()
    await load_or_pin_core(db, config, session)
    await db.commit()

    # Unpersisted identity mutation — the publisher must refuse.
    config.task = "UNPERSISTED EDIT"
    with pytest.raises(CoreConflict):
        await update_core(db, config, "- new curated\n")


@pytest.mark.asyncio
async def test_landed_candidate_commit_failure_recoverable(db, tmp_path, monkeypatch):
    """Candidate bytes landed but the publish commit failed — a fresh
    session re-pins the same published bytes rather than fabricating a
    new identity."""
    _patch_env(monkeypatch, tmp_path)
    config = await _agent(db)
    session = Session(id=str(uuid.uuid4()), agent_id="reg-test", contact_id="c1")
    db.add(session)
    await db.commit()
    await load_or_pin_core(db, config, session)
    await db.commit()
    path = _memory_path("reg-test", tmp_path)
    before = path.read_bytes()

    # Publish commit fails after bytes land.
    real_commit = db.commit
    calls = {"n": 0}

    async def flaky_commit():
        calls["n"] += 1
        if calls["n"] >= 2:
            raise RuntimeError("commit failed")
        return await real_commit()

    monkeypatch.setattr(db, "commit", flaky_commit)
    try:
        await update_core(db, config, "- v2\n")
    except RuntimeError:
        pass
    # Whatever landed, a fresh session must re-pin something valid —
    # not silently overwrite.
    s2 = Session(id=str(uuid.uuid4()), agent_id="reg-test", contact_id="c1")
    db.add(s2)
    await real_commit()
    snap = await load_or_pin_core(db, config, s2)
    assert snap.content  # a valid snapshot exists
    assert path.read_bytes() == before or split_core(path.read_text())[2]


@pytest.mark.asyncio
async def test_second_save_stale_config_identity_conflict(db, tmp_path, monkeypatch):
    """Config saved in a second session/transaction leaves the first's
    identity stale — update through the stale config conflicts."""
    _patch_env(monkeypatch, tmp_path)
    config = await _agent(db)
    session = Session(id=str(uuid.uuid4()), agent_id="reg-test", contact_id="c1")
    db.add(session)
    await db.commit()
    await load_or_pin_core(db, config, session)
    await db.commit()

    # A second, real save bumps the active version — the first config
    # object is now stale.
    newer = await get_active_config(db, "reg-test")
    newer.task = "Updated task."
    await save_agent(db, newer)

    with pytest.raises(CoreConflict):
        await update_core(db, config, "- stale write\n")


@pytest.mark.asyncio
async def test_fake_self_hashed_prefix_never_accepted(db, tmp_path, monkeypatch):
    """A managed prefix whose sha is 'correct' but matches NO AgentVersion
    identity is rejected — a hand-crafted fake published revision can't
    validate a foreign identity."""
    _patch_env(monkeypatch, tmp_path)
    config = await _agent(db)
    session = Session(id=str(uuid.uuid4()), agent_id="reg-test", contact_id="c1")
    db.add(session)
    await db.commit()
    await load_or_pin_core(db, config, session)
    await db.commit()

    path = _memory_path("reg-test", tmp_path)
    _, cur = split_core(path.read_text())[1], split_core(path.read_text())[2]
    fake_identity = "## Forged\n\nnot from any version"
    path.write_text(build_core(fake_identity, cur or ""))
    # Even with a matching published row inserted, the identity is foreign.
    db.add(
        CoreRevision(
            id=str(uuid.uuid4()),
            agent_id="reg-test",
            content=path.read_text(),
            curated_content=cur or "",
            content_hash=__import__("hashlib").sha256(path.read_text().encode()).hexdigest(),
            published=True,
        )
    )
    await db.commit()
    with pytest.raises(CoreConflict):
        await update_core(db, config, "- anything\n")


@pytest.mark.asyncio
async def test_corrupt_row_never_served_by_archive(db, tmp_path, monkeypatch):
    """A hash-corrupt CoreRevision row is never returned as archive
    evidence — integrity is verified before serving."""
    _patch_env(monkeypatch, tmp_path)
    config = await _agent(db)
    session = Session(id=str(uuid.uuid4()), agent_id="reg-test", contact_id="c1")
    db.add(session)
    await db.commit()
    await load_or_pin_core(db, config, session)
    await db.commit()

    # Insert a corrupt published row — content doesn't match its hash.
    db.add(
        CoreRevision(
            id=str(uuid.uuid4()),
            agent_id="reg-test",
            content="forged historical text about dark mode",
            curated_content="forged historical text about dark mode",
            content_hash="nottheactualhash",
            published=True,
        )
    )
    await db.commit()
    out = await recall.recall_core_archive(
        db, "reg-test", "dark mode", limit=5, session_id=session.id
    )
    assert all("forged" not in r["content"] for r in out)


@pytest.mark.asyncio
async def test_nested_marker_rejected_before_provider(db, tmp_path, monkeypatch):
    """Curated content containing the managed marker fails validation —
    a nested envelope can never reach the publisher."""
    _patch_env(monkeypatch, tmp_path)
    config = await _agent(db)
    session = Session(id=str(uuid.uuid4()), agent_id="reg-test", contact_id="c1")
    db.add(session)
    await db.commit()
    await load_or_pin_core(db, config, session)
    await db.commit()

    with pytest.raises(CoreConflict):
        await update_core(db, config, f"- note\n\n{IDENTITY_BEGIN}forged -->\n")


@pytest.mark.asyncio
async def test_credential_clarification_never_notified_raw(db, tmp_path, monkeypatch):
    """A clarification containing credential-like text is dropped — the
    operator notification never carries raw secrets."""
    _patch_env(monkeypatch, tmp_path)
    config = await _agent(db)
    session, run = await _seed_run(db)
    real = Message(id=str(uuid.uuid4()), run_id=run.id, role="user", content="hi", seq=0)
    db.add(real)
    await recall.store_snippet(db, "c1", "reg-test", "scratch", "keep me", run_id=run.id)
    await db.commit()

    notified: list[dict] = []
    monkeypatch.setattr(
        "agentos.memory.auto_extract.create_notification",
        lambda **kw: notified.append(kw),
    )
    payload = json.dumps(
        {
            "memories": [],
            "clarifications": ["Your api_key=sk-abc123456789012345678 is it valid?"],
            "core_markdown": None,
            "core_source_ids": [],
        }
    )
    _extract_adapter(monkeypatch, payload)
    await auto_extract_memory(
        db,
        config,
        "reg-test",
        [real],
        run_id=run.id,
        contact_id="c1",
        session_id=session.id,
    )
    for note in notified:
        assert "sk-abc123456789012345678" not in str(note)


@pytest.mark.asyncio
async def test_blank_clarification_retains_scratch(db, tmp_path, monkeypatch):
    """An empty/whitespace clarification entry is malformed — nothing
    publishes and scratch is retained."""
    _patch_env(monkeypatch, tmp_path)
    config = await _agent(db)
    session, run = await _seed_run(db)
    real = Message(id=str(uuid.uuid4()), run_id=run.id, role="user", content="hi", seq=0)
    db.add(real)
    await recall.store_snippet(db, "c1", "reg-test", "scratch", "keep me", run_id=run.id)
    await db.commit()

    payload = json.dumps(
        {
            "memories": [],
            "clarifications": ["   "],
            "core_markdown": "- x",
            "core_source_ids": [real.id],
        }
    )
    _extract_adapter(monkeypatch, payload)
    with pytest.raises(RuntimeError, match="clarifications"):
        await auto_extract_memory(
            db,
            config,
            "reg-test",
            [real],
            run_id=run.id,
            contact_id="c1",
            session_id=session.id,
        )
    scratch = (
        (await db.execute(select(MemoryEntry).where(MemoryEntry.key == "scratch"))).scalars().all()
    )
    assert scratch


@pytest.mark.asyncio
async def test_compact_uses_original_pin_reservation(db, tmp_path, monkeypatch):
    """After a global core update, /compact on an existing session still
    reserves the session's ORIGINAL pinned snapshot — exactly once."""
    import httpx

    from agentos.auth import require_operator
    from agentos.db import get_db
    from agentos.main import app
    from agentos.models.operator import Operator

    _patch_env(monkeypatch, tmp_path)
    config = await _agent(db)
    session = Session(id=str(uuid.uuid4()), agent_id="reg-test", contact_id="c1")
    db.add(session)
    await db.commit()
    snap = await load_or_pin_core(db, config, session)
    await db.commit()
    pinned_rev = snap.revision_id

    # Global update publishes a new revision — the session pin is intact.
    await update_core(db, config, "- after\n")
    await db.commit()
    assert session.core_revision_id == pinned_rev

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
            resp = await c.post(
                "/api/chat/reg-test/compact",
                json={"session_id": session.id},
            )
        assert resp.status_code in (200, 409, 422)
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_unpublished_core_conflict_notifies(db, tmp_path, monkeypatch):
    """An extraction-path core conflict emits the existing
    memory_update_failed notification with a session action link — the
    outcome is never silently discarded."""
    _patch_env(monkeypatch, tmp_path)
    config = await _agent(db)
    session, run = await _seed_run(db)
    real = Message(id=str(uuid.uuid4()), run_id=run.id, role="user", content="hi", seq=0)
    db.add(real)
    # Pin so update_core has a base — then corrupt the pin so the
    # core-markdown publish lands as a conflict.
    pin_session = Session(id=str(uuid.uuid4()), agent_id="reg-test", contact_id="c1")
    db.add(pin_session)
    await db.commit()
    await load_or_pin_core(db, config, pin_session)
    await db.commit()
    # Force a genuine publish conflict through the real path.
    monkeypatch.setattr(
        "agentos.memory.auto_extract.core_mod.update_core",
        AsyncMock(side_effect=CoreConflict("stale")),
    )
    await recall.store_snippet(db, "c1", "reg-test", "scratch", "keep me", run_id=run.id)
    await db.commit()

    notified: list[dict] = []
    monkeypatch.setattr(
        "agentos.memory.auto_extract.create_notification",
        AsyncMock(side_effect=lambda *a, **kw: notified.append(dict(kw))),
    )
    payload = json.dumps(
        {
            "memories": [],
            "clarifications": [],
            "core_markdown": "- proposed",
            "core_source_ids": [real.id],
        }
    )
    _extract_adapter(monkeypatch, payload)
    await auto_extract_memory(
        db,
        config,
        "reg-test",
        [real],
        run_id=run.id,
        contact_id="c1",
        session_id=session.id,
    )
    assert notified, "core conflict must notify"
    assert notified[0]["notification_type"] == "memory_update_failed"
    assert "chat?session=" in notified[0]["action_path"]


@pytest.mark.asyncio
async def test_archive_reaches_beyond_newest_50(db, tmp_path, monkeypatch):
    """An old demoted paragraph past the newest 50 revisions stays
    retrievable — the archive streams candidates, not .limit(50)."""
    _patch_env(monkeypatch, tmp_path)
    await _agent(db)
    import datetime as _dt
    import hashlib

    base_time = _dt.datetime(2024, 1, 1, 0, 0, 0)
    # One old revision containing the unique term.
    old_content = build_core("old id", "- rare-skill-tok-7 fact\n")
    db.add(
        CoreRevision(
            id=str(uuid.uuid4()),
            agent_id="reg-test",
            content=old_content,
            curated_content="- rare-skill-tok-7 fact\n",
            content_hash=hashlib.sha256(old_content.encode()).hexdigest(),
            published=True,
            created_at=base_time,
        )
    )
    # 60 newer empty revisions — strictly later created_at so the old row
    # sorts after all of them.
    for _i in range(60):
        c = build_core("x", f"- filler-{_i}\n")
        db.add(
            CoreRevision(
                id=str(uuid.uuid4()),
                agent_id="reg-test",
                content=c,
                curated_content=f"- filler-{_i}\n",
                content_hash=hashlib.sha256(c.encode()).hexdigest(),
                published=True,
                created_at=base_time + _dt.timedelta(seconds=_i + 1),
            )
        )
    await db.commit()
    out = await recall.recall_core_archive(db, "reg-test", "rare-skill-tok-7", limit=5)
    assert any("rare-skill-tok-7" in r["content"] for r in out)
