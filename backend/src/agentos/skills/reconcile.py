"""Skill reconciliation — seed built-ins, migrate legacy dirs, index agent-locals.

Runs at startup after init_db. Makes the filesystem ground truth visible as
Skill/SkillRevision rows so the loader can resolve menus through the DB:

- Built-ins: every manifest name with a dir under `skills_dir` gets a
  `scope=built-in` row; a changed content hash produces a new immutable
  revision (source "initial seed" / "app update"), so shipped updates are
  versioned like everything else. Built-ins dropped from the manifest are
  deleted — their bytes no longer ship, so the rows are dead ends — except
  while an active run pins a revision, which keeps the row archived until
  the pin clears.
- Legacy user imports sitting in `skills/` (dir names outside the manifest)
  move to the skills-store as `scope=global` revision 1 — `skills/` is
  read-only shipped resources from here on.
- Agent-local: `workspaces/{agent}/skills/{name}/` dirs get
  `scope=agent-local` rows. They stay live working copies — no revision rows
  until an explicit publish/snapshot.
- Workspace drafts: `workspaces/{agent}/skill-drafts/{name}/` dirs get
  `scope=agent-local`, `status=draft` rows — an agent told to use
  skill-creator in a normal chat writes only files, so indexing is what
  makes those drafts visible. `index_workspace_draft_dirs` is shared with
  the skills listing so mid-run drafts surface without a restart.
"""

import json
import logging
import shutil
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..models.skill import Skill, SkillRevision
from .builtins import BUILTIN_SKILLS, hash_skill_dir
from .loader import _load_skill_from_dir

log = logging.getLogger(__name__)


def _store_path_for(relative: str) -> Path:
    return Path(settings.skills_store_root) / relative


async def _latest_revision_number(db: AsyncSession, skill_id: str) -> int:
    return (
        await db.scalar(
            select(func.max(SkillRevision.revision_number)).where(
                SkillRevision.skill_id == skill_id
            )
        )
        or 0
    )


async def _new_revision(
    db: AsyncSession,
    skill: Skill,
    *,
    storage_path: str,
    content_hash: str,
    change_summary: str,
    validation: dict | None = None,
) -> SkillRevision:
    """Append the next immutable revision and make it current."""
    revision = SkillRevision(
        skill_id=skill.id,
        revision_number=await _latest_revision_number(db, skill.id) + 1,
        storage_path=storage_path,
        content_hash=content_hash,
        change_summary=change_summary,
        validation_result=json.dumps(validation or {}, ensure_ascii=False),
    )
    db.add(revision)
    await db.flush()
    skill.current_revision_id = revision.id
    return revision


async def _seed_builtin(db: AsyncSession, name: str, skill_dir: Path) -> None:
    """Seed or re-hash one built-in skill; changed content → new revision."""
    if _load_skill_from_dir(skill_dir, "built-in") is None:
        log.warning("[skills] built-in %r has no valid SKILL.md — skipped", name)
        return

    skill = (
        await db.execute(select(Skill).where(Skill.scope == "built-in", Skill.name == name))
    ).scalar_one_or_none()
    if skill is None:
        skill = Skill(name=name, scope="built-in", status="published", availability="all")
        db.add(skill)
        await db.flush()
    elif skill.status == "archived":
        # Name is back in the manifest (re-shipped or app downgrade) — revive.
        skill.status = "published"

    content_hash = hash_skill_dir(skill_dir)
    latest_number = await _latest_revision_number(db, skill.id)
    if latest_number:
        latest = (
            await db.execute(
                select(SkillRevision).where(
                    SkillRevision.skill_id == skill.id,
                    SkillRevision.revision_number == latest_number,
                )
            )
        ).scalar_one()
        if latest.content_hash == content_hash:
            return  # unchanged — nothing to do

    await _new_revision(
        db,
        skill,
        storage_path=name,
        content_hash=content_hash,
        change_summary="initial seed" if latest_number == 0 else "app update",
    )
    if latest_number:
        log.info("[skills] built-in %r changed on disk → new revision", name)


async def _migrate_legacy_dir(db: AsyncSession, skill_dir: Path) -> None:
    """Move a non-manifest dir out of skills/ → global skill revision 1."""
    name = skill_dir.name
    existing = (
        await db.execute(select(Skill).where(Skill.scope == "global", Skill.name == name))
    ).scalar_one_or_none()
    if existing is not None:
        log.warning(
            "[skills] legacy dir %r still in skills/ but a global row exists — left in place",
            name,
        )
        return

    skill = Skill(name=name, scope="global", status="published", availability="all")
    db.add(skill)
    await db.flush()  # skill.id needed for the storage path

    relative = f"{skill.id}/rev-1"
    target = _store_path_for(relative)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(skill_dir), str(target))
    await _new_revision(
        db,
        skill,
        storage_path=relative,
        content_hash=hash_skill_dir(target),
        change_summary="migrated legacy import",
    )
    log.info("[skills] migrated legacy import %r → %s", name, target)


async def _retire_builtins(db: AsyncSession) -> None:
    """Delete built-in rows whose name was dropped from the manifest.

    A removed built-in's dir no longer ships in skills/, so its rows are dead
    ends — revisions, assignments, and the row itself are deleted. Exception:
    while an active run pins one of its revisions the row stays archived (it
    is deleted on a later startup once the pin clears). Nothing on disk is
    touched — built-in bytes live in `skills_dir`, which isn't ours.
    """
    from . import service

    retired = (
        await db.execute(
            select(Skill).where(
                Skill.scope == "built-in",
                Skill.name.not_in(BUILTIN_SKILLS),
            )
        )
    ).scalars()
    for skill in retired:
        if await service.active_run_pins_skill(db, skill):
            if skill.status != "archived":
                skill.status = "archived"
                log.info("[skills] built-in %r pinned by an active run → archived", skill.name)
            continue
        await db.delete(skill)
        log.info("[skills] built-in %r no longer shipped → deleted", skill.name)


async def _index_agent_local(db: AsyncSession, agent_id: str, skill_dir: Path) -> Skill | None:
    """Register a workspace skill dir as an agent-local row (live copy)."""
    # Identity is the directory name (spec: name must match it); frontmatter
    # name drift is a validation problem, not an identity problem.
    name = skill_dir.name
    # owner_agent_id is FK'd — a workspace dir can outlive its Agent row
    # (deleted agent, copied fixtures). Skip rather than violate.
    from ..models.agent import Agent

    if await db.scalar(select(Agent.id).where(Agent.id == agent_id)) is None:
        return None
    existing = (
        await db.execute(
            select(Skill).where(
                Skill.scope == "agent-local",
                Skill.owner_agent_id == agent_id,
                Skill.name == name,
            )
        )
    ).scalar_one_or_none()
    if existing is not None or _load_skill_from_dir(skill_dir, "agent-local") is None:
        return existing
    skill = Skill(
        name=name,
        scope="agent-local",
        owner_agent_id=agent_id,
        status="published",
    )
    db.add(skill)
    await db.flush()
    return skill


async def _index_agent_draft(db: AsyncSession, agent_id: str, skill_dir: Path) -> Skill | None:
    """Register a workspace `skill-drafts/` dir as an agent-local draft row.

    Mirrors `_index_agent_local`'s guards — directory-name identity, a live
    Agent row, an existing (scope, owner, name) row wins, a valid SKILL.md
    required — but the new row is a draft: no SkillRevision until an
    explicit publish. Returns the created row, or None when the dir was
    skipped or already indexed (existing rows are never touched).
    """
    name = skill_dir.name
    from ..models.agent import Agent

    if await db.scalar(select(Agent.id).where(Agent.id == agent_id)) is None:
        return None
    existing = (
        await db.execute(
            select(Skill).where(
                Skill.scope == "agent-local",
                Skill.owner_agent_id == agent_id,
                Skill.name == name,
            )
        )
    ).scalar_one_or_none()
    if existing is not None or _load_skill_from_dir(skill_dir, "agent-local") is None:
        return None
    skill = Skill(
        name=name,
        scope="agent-local",
        owner_agent_id=agent_id,
        status="draft",
    )
    db.add(skill)
    await db.flush()
    return skill


async def index_workspace_draft_dirs(db: AsyncSession) -> int:
    """Index `workspaces/{agent}/skill-drafts/{name}` dirs as draft rows.

    Shared by startup reconcile and the skills listing — a builder agent
    mid-run writes only files, so chat-created drafts must be picked up
    without a restart. Cheap: one bounded walk of `workspace_root` looking
    at `skill-drafts/` children only. Returns the number of rows created.
    """
    created = 0
    workspace_root = Path(settings.workspace_root)
    if not workspace_root.is_dir():
        return created
    for agent_dir in sorted(workspace_root.iterdir()):
        drafts_dir = agent_dir / "skill-drafts"
        if not drafts_dir.is_dir():
            continue
        for skill_dir in sorted(drafts_dir.iterdir()):
            if skill_dir.is_dir() and await _index_agent_draft(db, agent_dir.name, skill_dir):
                created += 1
    await db.flush()
    return created


async def reconcile_skills(db: AsyncSession) -> None:
    """Sync filesystem ground truth into Skill/SkillRevision rows."""
    skills_dir = Path(settings.skills_dir)
    skills_dir.mkdir(parents=True, exist_ok=True)
    Path(settings.skills_store_root).mkdir(parents=True, exist_ok=True)

    for entry in sorted(skills_dir.iterdir()):
        if not entry.is_dir():
            continue
        if entry.name in BUILTIN_SKILLS:
            await _seed_builtin(db, entry.name, entry)
        else:
            await _migrate_legacy_dir(db, entry)

    # Manifest entries with no dir on disk (partial checkout / trimmed
    # package) get seeded on their next appearance — nothing to do now.
    # Names dropped from the manifest retire any surviving built-in rows.
    await _retire_builtins(db)

    workspace_root = Path(settings.workspace_root)
    if workspace_root.is_dir():
        for agent_dir in sorted(workspace_root.iterdir()):
            local_dir = agent_dir / "skills"
            if not local_dir.is_dir():
                continue
            for skill_dir in sorted(local_dir.iterdir()):
                if skill_dir.is_dir():
                    await _index_agent_local(db, agent_dir.name, skill_dir)

    # Workspace skill-drafts/ dirs → draft rows. Published agent-locals are
    # indexed first so a same-named live copy wins the (scope, owner, name)
    # uniqueness and the draft dir is skipped.
    await index_workspace_draft_dirs(db)

    await db.flush()
