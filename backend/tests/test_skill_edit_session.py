"""SkillEditSession via the ordinary tool seams — stage, publish, conflict.

Covers the public contract: read/write through read_file/write_file +
skills_load with kwargs['skill_edits'], publish() writing immutable
revisions, conflict on drifted baselines, and path/symlink rejection.
"""

import pytest
from sqlalchemy import select

from agentos.config_schema import AgentConfig, Limits, ModelConfig
from agentos.models.contact import Contact
from agentos.models.run import Run
from agentos.models.session import Session
from agentos.models.skill import Skill, SkillRevision
from agentos.skills.resolution import ResolvedSkill
from agentos.skills.service import SkillEditSession


async def _resolve(db, agent_id):
    from agentos.skills.resolution import resolve_effective_skills

    return await resolve_effective_skills(db, agent_id)


async def _seed_db(db, cfg):
    from agentos.agent_service import create_agent

    await create_agent(db, cfg)
    db.add(Contact(id="c1", channel="dashboard_chat", bot_id=cfg.id, external_user_id="u1"))
    db.add(Session(id="s1", contact_id="c1", agent_id=cfg.id, closed=True))
    db.add(
        Run(
            id="r1",
            session_id="s1",
            contact_id="c1",
            agent_id=cfg.id,
            status="completed",
            trigger="user_message",
        )
    )
    await db.commit()


async def _mk(db, tmp_path, monkeypatch):
    from agentos.config import settings

    cfg = AgentConfig(
        id="qa-agent",
        name="Q",
        model=ModelConfig(provider_id="p", name="m"),
        limits=Limits(),
    )
    await _seed_db(db, cfg)
    monkeypatch.setattr(settings, "workspace_root", tmp_path / "ws")
    monkeypatch.setattr(settings, "skills_store_root", tmp_path / "store")
    (tmp_path / "ws").mkdir()
    (tmp_path / "store").mkdir()
    return cfg


def _local_skill_dir(tmp_path, name):
    return tmp_path / "ws" / "qa-agent" / "skills" / name


def _mk_local_skill(tmp_path, name, content):
    d = _local_skill_dir(tmp_path, name)
    d.mkdir(parents=True, exist_ok=True)
    (d / "SKILL.md").write_text(content, encoding="utf-8")
    return d


@pytest.mark.asyncio
async def test_read_write_stage_publish_new_skill(db, tmp_path, monkeypatch):
    """write stages only; publish creates the immutable revision with the
    correct source_run_id and reason; the live dir matches the store."""
    await _mk(db, tmp_path, monkeypatch)
    from agentos.capabilities.tools.file import read_file, write_file

    session = SkillEditSession(db, "qa-agent", [])
    # read of absent-new establishes a baseline, doesn't fabricate bytes
    out = await read_file({"path": "skills/newskill/SKILL.md"}, "", skill_edits=session)
    assert out.get("absent") is True

    staged = await write_file(
        {
            "path": "skills/newskill/SKILL.md",
            "content": "---\nname: newskill\ndescription: x\nlicense: L\ncompatibility: c\nallowed-tools: read_file\n---\nBody",
        },
        "",
        skill_edits=session,
    )
    assert staged == {"staged": True, "path": "skills/newskill/SKILL.md"}
    # nothing on disk yet — only .skill-edits staging, no live SKILL.md
    assert not (_local_skill_dir(tmp_path, "newskill") / "SKILL.md").exists()

    res = await session.publish(
        reason="session feedback", source_run_id="r1", precondition=lambda n: None
    )
    assert res["conflicts"] == [] and res["errors"] == []
    assert res["revision_ids"]
    rev = await db.get(SkillRevision, res["revision_ids"][0])
    assert rev.source_run_id == "r1" and rev.change_summary == "session feedback"
    live = _local_skill_dir(tmp_path, "newskill") / "SKILL.md"
    assert live.exists() and "Body" in live.read_text()


@pytest.mark.asyncio
async def test_local_edit_snapshots_old_and_new(db, tmp_path, monkeypatch):
    """Existing local skill: publish snapshots the pre-edit bytes (no author)
    then writes the staged content as a new sourced revision."""
    await _mk(db, tmp_path, monkeypatch)
    from agentos.capabilities.tools.file import write_file

    live = _mk_local_skill(
        tmp_path,
        "oldskill",
        "---\nname: oldskill\ndescription: o\nlicense: L\ncompatibility: c\nallowed-tools: read_file\n---\nOld",
    )
    from agentos.skills.reconcile import _index_agent_local

    await _index_agent_local(db, "qa-agent", live)

    session = SkillEditSession(
        db,
        "qa-agent",
        [
            ResolvedSkill(
                name="oldskill",
                description="o",
                scope="agent-local",
                path=live,
                skill_id=None,
                revision_id=None,
                pin=None,
                shadows=None,
            )
        ],
    )
    await session.read_file("skills/oldskill/SKILL.md")
    await write_file(
        {
            "path": "skills/oldskill/SKILL.md",
            "content": "---\nname: oldskill\ndescription: o\nlicense: L\ncompatibility: c\nallowed-tools: read_file\n---\nNew",
        },
        "",
        skill_edits=session,
    )
    res = await session.publish(reason="edit", source_run_id="r1", precondition=lambda n: None)
    assert res["revision_ids"]
    skill = await db.scalar(
        select(Skill).where(Skill.name == "oldskill", Skill.scope == "agent-local")
    )
    revs = (
        (
            await db.execute(
                select(SkillRevision)
                .where(SkillRevision.skill_id == skill.id)
                .order_by(SkillRevision.revision_number)
            )
        )
        .scalars()
        .all()
    )
    # _index already snapshotted the baseline (hash matches), so only the
    # sourced edit revision is added — drifted bytes would add a third.
    assert len(revs) == 2
    assert revs[-2].source_run_id is None  # index snapshot — no invented author
    assert revs[-1].source_run_id == "r1"
    assert (live / "SKILL.md").read_text().endswith("New")


@pytest.mark.asyncio
async def test_conflicts_leave_newer_bytes_untouched(db, tmp_path, monkeypatch):
    """Target drifts between capture and publish → conflict, no overwrite."""
    await _mk(db, tmp_path, monkeypatch)
    from agentos.capabilities.tools.file import write_file

    live = _mk_local_skill(
        tmp_path,
        "drifty",
        "---\nname: drifty\ndescription: d\nlicense: L\ncompatibility: c\nallowed-tools: read_file\n---\nV1",
    )
    session = SkillEditSession(
        db,
        "qa-agent",
        [
            ResolvedSkill(
                name="drifty",
                description="d",
                scope="agent-local",
                path=live,
                skill_id=None,
                revision_id=None,
                pin=None,
                shadows=None,
            )
        ],
    )
    await session.read_file("skills/drifty/SKILL.md")
    await write_file(
        {
            "path": "skills/drifty/SKILL.md",
            "content": "---\nname: drifty\ndescription: d\nlicense: L\ncompatibility: c\nallowed-tools: read_file\n---\nV2",
        },
        "",
        skill_edits=session,
    )
    # External writer changes the target after capture.
    (live / "SKILL.md").write_text(
        "---\nname: drifty\ndescription: d\nlicense: L\ncompatibility: c\nallowed-tools: read_file\n---\nV3-external",
        encoding="utf-8",
    )
    res = await session.publish(reason="edit", source_run_id="r1", precondition=lambda n: None)
    assert "drifty" in res["conflicts"]
    assert (live / "SKILL.md").read_text().endswith("V3-external")


@pytest.mark.asyncio
async def test_path_escape_and_symlink_rejected(db, tmp_path, monkeypatch):
    await _mk(db, tmp_path, monkeypatch)
    session = SkillEditSession(db, "qa-agent", [])
    from agentos.capabilities.tools.file import read_file, write_file
    from agentos.skills.service import SkillError

    for bad in ("skills/../etc/passwd", "skills//abs", "/etc/passwd", "skills/a\\b"):
        with pytest.raises(SkillError):
            await write_file({"path": bad, "content": "x"}, "", skill_edits=session)
    with pytest.raises(SkillError):
        await read_file({"path": "skills/../outside/SKILL.md"}, "", skill_edits=session)


@pytest.mark.asyncio
async def test_unchanged_staged_publish_no_revision(db, tmp_path, monkeypatch):
    """Staged content identical to baseline → no new revision."""
    await _mk(db, tmp_path, monkeypatch)
    live = _mk_local_skill(
        tmp_path,
        "same",
        "---\nname: same\ndescription: s\nlicense: L\ncompatibility: c\nallowed-tools: read_file\n---\nBody",
    )
    session = SkillEditSession(
        db,
        "qa-agent",
        [
            ResolvedSkill(
                name="same",
                description="s",
                scope="agent-local",
                path=live,
                skill_id=None,
                revision_id=None,
                pin=None,
                shadows=None,
            )
        ],
    )
    await session.read_file("skills/same/SKILL.md")
    await session.write_file(
        "skills/same/SKILL.md",
        "---\nname: same\ndescription: s\nlicense: L\ncompatibility: c\nallowed-tools: read_file\n---\nBody",
    )
    res = await session.publish(reason="x", source_run_id="r1", precondition=lambda n: None)
    assert res["revision_ids"] == [] and res["conflicts"] == []


async def _global_skill(db, tmp_path, monkeypatch, name="gskill"):
    """Real governed source: Skill row + rev-1 store dir + resolution."""

    src = tmp_path / "globalsrc" / name
    src.mkdir(parents=True, exist_ok=True)
    (src / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: g\nlicense: L\ncompatibility: c\nallowed-tools: read_file\n---\nGlobal",
        encoding="utf-8",
    )
    (src / "res.txt").write_text("shared-resource", encoding="utf-8")
    skill = Skill(name=name, scope="global", status="published", availability="all")
    db.add(skill)
    await db.flush()
    rel = f"{skill.id}/rev-1"
    store = tmp_path / "store" / rel
    store.parent.mkdir(parents=True, exist_ok=True)
    import shutil

    shutil.copytree(src, store)
    rev = SkillRevision(
        skill_id=skill.id,
        revision_number=1,
        storage_path=rel,
        content_hash="",
        change_summary="v1",
    )
    db.add(rev)
    await db.flush()
    skill.current_revision_id = rev.id
    await db.commit()
    return skill, src


@pytest.mark.asyncio
async def test_global_override_preserves_resources(db, tmp_path, monkeypatch):
    """Overriding a global skill keeps its resources in the local copy; the
    shared source is never touched."""
    await _mk(db, tmp_path, monkeypatch)
    skill, src = await _global_skill(db, tmp_path, monkeypatch)

    rl = await _resolve(db, "qa-agent")
    session = SkillEditSession(db, "qa-agent", rl)
    # inspect the GLOBAL source — capture pins scope + revision + hash
    out = await session.load_skill(
        next(s for s in await _resolve(db, "qa-agent") if s.name == "gskill")
    )
    assert out["source_scope"] == "global" and out["content_hash"]
    await session.read_file("skills/gskill/SKILL.md")
    await session.write_file(
        "skills/gskill/SKILL.md",
        "---\nname: gskill\ndescription: g\nlicense: L\ncompatibility: c\nallowed-tools: read_file\n---\nLocalOverride",
    )
    res = await session.publish(reason="override", source_run_id="r1", precondition=lambda n: None)
    assert res["revision_ids"], res
    live = _local_skill_dir(tmp_path, "gskill")
    assert (live / "SKILL.md").read_text().endswith("LocalOverride")
    assert (live / "res.txt").read_text() == "shared-resource"
    # shared source unchanged
    assert (src / "SKILL.md").read_text().endswith("Global")


@pytest.mark.asyncio
async def test_global_publish_mid_await_conflicts(db, tmp_path, monkeypatch):
    """A new global revision published between inspect and publish =>
    conflict; no local bytes installed."""
    await _mk(db, tmp_path, monkeypatch)
    skill, src = await _global_skill(db, tmp_path, monkeypatch)

    session = SkillEditSession(db, "qa-agent", await _resolve(db, "qa-agent"))
    await session.read_file("skills/gskill/SKILL.md")
    await session.write_file(
        "skills/gskill/SKILL.md",
        "---\nname: gskill\ndescription: g\nlicense: L\ncompatibility: c\nallowed-tools: read_file\n---\nLocalOverride",
    )

    done = False

    async def _mid_publish(name):
        # Precondition fires INSIDE publish — publish a newer global rev ONCE.
        nonlocal done
        if done:
            return
        done = True
        import shutil

        rev = SkillRevision(
            skill_id=skill.id,
            revision_number=2,
            storage_path=f"{skill.id}/rev-2",
            content_hash="x",
            change_summary="newer global",
        )
        db.add(rev)
        store = tmp_path / "store" / rev.storage_path
        store.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(src, store)
        skill.current_revision_id = rev.id
        await db.flush()

    res = await session.publish(reason="override", source_run_id="r1", precondition=_mid_publish)
    assert "gskill" in res["conflicts"]
    assert not (_local_skill_dir(tmp_path, "gskill") / "SKILL.md").exists()
