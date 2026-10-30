"""Drift scanner — live-dir writes outside a tracked edit session get
pinned to immutable revisions at close/startup checkpoints."""

import pytest
from sqlalchemy import func, select

from agentos.config import settings
from agentos.config_schema import AgentConfig, ModelConfig
from agentos.models.skill import Skill, SkillRevision

SKILL_MD = (
    "---\nname: report\ndescription: r\nlicense: x\ncompatibility: c\n"
    "allowed-tools: read_file\n---\nv%d"
)


async def _agent(db):
    from agentos.agent_service import create_agent

    cfg = AgentConfig(id="qa-agent", name="QA", model=ModelConfig(provider_id="p", name="m"))
    await create_agent(db, cfg)
    return cfg


def _skill_dir(name="report"):
    return settings.workspace_root / "qa-agent" / "skills" / name


@pytest.mark.asyncio
async def test_first_sighting_snapshots_rev1(db, tmp_path):
    await _agent(db)
    live = _skill_dir()
    live.mkdir(parents=True)
    (live / "SKILL.md").write_text(SKILL_MD % 1)

    from agentos.skills.reconcile import snapshot_agent_local_drift

    revs = await snapshot_agent_local_drift(db, "qa-agent")
    await db.commit()
    assert len(revs) == 1
    rev = revs[0]
    assert rev.revision_number == 1
    # Untracked edit → honest provenance, no invented run link.
    assert rev.source_run_id is None
    assert "outside a tracked edit" in rev.change_summary
    # Stored bytes exist and hash to the recorded content_hash.
    from agentos.skills.builtins import hash_skill_dir

    stored = settings.skills_store_root / rev.storage_path
    assert (stored / "SKILL.md").exists()
    assert rev.content_hash == hash_skill_dir(stored)


@pytest.mark.asyncio
async def test_unchanged_dir_snapshots_nothing(db, tmp_path):
    await _agent(db)
    live = _skill_dir()
    live.mkdir(parents=True)
    (live / "SKILL.md").write_text(SKILL_MD % 1)

    from agentos.skills.reconcile import snapshot_agent_local_drift

    assert len(await snapshot_agent_local_drift(db, "qa-agent")) == 1
    await db.commit()
    assert await snapshot_agent_local_drift(db, "qa-agent") == []


@pytest.mark.asyncio
async def test_drift_and_restore_chain(db, tmp_path):
    await _agent(db)
    live = _skill_dir()
    live.mkdir(parents=True)
    (live / "SKILL.md").write_text(SKILL_MD % 1)
    (live / "extra.txt").write_text("v1 extra")

    from agentos.skills.reconcile import snapshot_agent_local_drift

    await snapshot_agent_local_drift(db, "qa-agent")
    await db.commit()
    # Untracked edit: modify + delete a file.
    (live / "SKILL.md").write_text(SKILL_MD % 2)
    (live / "extra.txt").unlink()
    revs = await snapshot_agent_local_drift(db, "qa-agent")
    await db.commit()
    assert len(revs) == 1 and revs[0].revision_number == 2
    stored = settings.skills_store_root / revs[0].storage_path
    assert (stored / "SKILL.md").read_text() == SKILL_MD % 2
    assert not (stored / "extra.txt").exists()
    # Rev-1 bytes remain intact — history isn't rewritten.
    skill = await db.scalar(
        select(Skill).where(Skill.scope == "agent-local", Skill.name == "report")
    )
    revs_all = list(
        await db.scalars(
            select(SkillRevision)
            .where(SkillRevision.skill_id == skill.id)
            .order_by(SkillRevision.revision_number)
        )
    )
    assert len(revs_all) == 2
    first = settings.skills_store_root / revs_all[0].storage_path
    assert (first / "extra.txt").exists()


@pytest.mark.asyncio
async def test_tracked_publish_then_scan_sees_no_drift(db, tmp_path):
    """Bytes installed by a tracked publish hash-match its revision —
    the next drift scan must add nothing (hash functions agree)."""
    await _agent(db)
    live = _skill_dir()
    live.mkdir(parents=True)
    (live / "SKILL.md").write_text(SKILL_MD % 1)

    from agentos.skills.reconcile import snapshot_agent_local_drift
    from agentos.skills.resolution import resolve_effective_skills
    from agentos.skills.service import SkillEditSession

    await snapshot_agent_local_drift(db, "qa-agent")
    await db.commit()

    resolved = await resolve_effective_skills(db, "qa-agent")
    target = next(s for s in resolved if s.name == "report")
    edits = SkillEditSession(db, "qa-agent", resolved)
    try:
        await edits.load_skill(target)
        await edits.write_file("skills/report/SKILL.md", SKILL_MD % 2)
        published = await edits.publish(
            reason="tracked revision", source_run_id=None, precondition=None
        )
    finally:
        await edits.close()
    await db.commit()
    assert published["revision_ids"], published

    # Publish installed rev-2 — the scanner must detect zero drift.
    assert await snapshot_agent_local_drift(db, "qa-agent") == []
    count = await db.scalar(select(func.count()).select_from(SkillRevision))
    assert count == 2
