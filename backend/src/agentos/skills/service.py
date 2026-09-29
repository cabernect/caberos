"""Skill lifecycle operations (W6 Skills Studio).

The DB is the authority for visibility; disk holds the bytes. Every publish
copies a source dir into the skills-store as an immutable revision —
never overwrite, always copy, flip current_revision_id.

Layout:

    data/skills-store/{skill_id}/rev-{n}/     published revisions (global + local snapshots)
    skills/{name}/                            built-ins (shipped, read-only)
    workspace/{agent}/skills/{name}/          agent-local live working copy
    workspace/{agent}/skill-drafts/{name}/    drafts — never scanned by the loader
"""

import json
import logging
import shutil
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..models.skill import Skill, SkillAssignment, SkillRevision
from .builtins import hash_skill_dir

log = logging.getLogger(__name__)

ACTIVE_RUN_STATUSES = ("pending", "running", "awaiting_approval")


class SkillError(ValueError):
    """User-facing operation failure — the API turns it into a 4xx."""

    def __init__(self, message: str, *, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


def draft_dir(skill: Skill) -> Path:
    """A draft's working dir — unscanned by the loader.

    Agent-owned drafts (builder sessions) live inside the owner agent's
    workspace at `skill-drafts/{name}` so the host agent reaches them via
    ordinary workspace tools. Operator-owned import drafts have no owner —
    they live in `data/skills-drafts/{name}` instead.
    """
    if skill.owner_agent_id:
        return Path(settings.workspace_root) / skill.owner_agent_id / "skill-drafts" / skill.name
    return Path(settings.skills_drafts_root) / skill.name


def live_local_dir(skill: Skill) -> Path:
    """An agent-local skill's live workspace dir — the scanned location."""
    if not skill.owner_agent_id:
        raise SkillError("agent-local skill has no owner agent")
    return Path(settings.workspace_root) / skill.owner_agent_id / "skills" / skill.name


def _store_root() -> Path:
    return Path(settings.skills_store_root)


def _revision_rel(skill_id: str, number: int) -> str:
    return f"{skill_id}/rev-{number}"


def revision_abs_path(skill: Skill, revision: SkillRevision) -> Path:
    if skill.scope == "built-in":
        return Path(settings.skills_dir) / revision.storage_path
    return _store_root() / revision.storage_path


async def get_skill(db: AsyncSession, skill_id: str) -> Skill:
    skill = await db.scalar(select(Skill).where(Skill.id == skill_id))
    if skill is None:
        raise SkillError(f"Skill '{skill_id}' not found", status_code=404)
    return skill


async def _current_revision(db: AsyncSession, skill: Skill) -> SkillRevision | None:
    if skill.current_revision_id is None:
        return None
    return await db.scalar(
        select(SkillRevision).where(SkillRevision.id == skill.current_revision_id)
    )


async def _next_revision(
    db: AsyncSession,
    skill: Skill,
    source_dir: Path,
    change_summary: str | None,
    validation: dict | None = None,
    source_run_id: str | None = None,
) -> SkillRevision:
    """Copy source_dir into the store as the next immutable revision."""
    from sqlalchemy import func

    number = (
        await db.scalar(
            select(func.max(SkillRevision.revision_number)).where(
                SkillRevision.skill_id == skill.id
            )
        )
        or 0
    ) + 1
    relative = _revision_rel(skill.id, number)
    target = _store_root() / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source_dir, target)

    revision = SkillRevision(
        skill_id=skill.id,
        revision_number=number,
        storage_path=relative,
        content_hash=hash_skill_dir(target),
        change_summary=change_summary,
        source_run_id=source_run_id,
        validation_result=json.dumps(validation or {}, ensure_ascii=False),
    )
    db.add(revision)
    await db.flush()
    skill.current_revision_id = revision.id
    return revision


def _copy_to_live_local(skill: Skill, source_dir: Path) -> None:
    """Sync published agent-local content into the live workspace dir."""
    target = live_local_dir(skill)
    if target.exists():
        shutil.rmtree(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source_dir, target)


async def create_draft(
    db: AsyncSession,
    *,
    name: str,
    owner_agent_id: str | None,
    builder_session_id: str | None = None,
) -> Skill:
    """Create an inert draft: a dir + a Skill row (status=draft).

    Agent-owned drafts live in the workspace `skill-drafts/` (the builder
    flow); ownerless drafts live in `data/skills-drafts/` (manual creation).
    """
    from .validate import _NAME_RE

    if not _NAME_RE.match(name):
        raise SkillError(f"Invalid skill name '{name}' — lowercase letters, numbers, hyphens only")
    if owner_agent_id:
        clash = await db.scalar(
            select(Skill).where(
                Skill.name == name,
                Skill.scope == "agent-local",
                Skill.owner_agent_id == owner_agent_id,
            )
        )
        if clash is not None:
            raise SkillError(
                f"a skill named '{name}' already exists for this agent",
                status_code=409,
            )
    else:
        if (Path(settings.skills_drafts_root) / name).exists():
            raise SkillError(f"a draft named '{name}' already exists", status_code=409)
    skill = Skill(
        name=name,
        scope="agent-local" if owner_agent_id else "global",
        owner_agent_id=owner_agent_id,
        status="draft",
        builder_session_id=builder_session_id,
    )
    db.add(skill)
    path = draft_dir(skill)
    path.mkdir(parents=True, exist_ok=True)
    (path / "SKILL.md").write_text(f"---\nname: {name}\ndescription: \n---\n\n", encoding="utf-8")
    await db.flush()
    return skill


async def import_draft(
    db: AsyncSession,
    *,
    name: str,
    source_dir: Path,
    owner_agent_id: str | None = None,
) -> Skill:
    """Land extracted archive content as a draft — never published.

    Ownerless imports use `skills_drafts_root/{name}` (with a suffix on
    collision); agent-owned imports use the workspace `skill-drafts/` dir.
    """
    from .validate import _NAME_RE

    if not _NAME_RE.match(name):
        raise SkillError(f"Invalid skill name '{name}' — lowercase letters, numbers, hyphens only")
    if owner_agent_id:
        clash = await db.scalar(
            select(Skill).where(
                Skill.name == name,
                Skill.scope == "agent-local",
                Skill.owner_agent_id == owner_agent_id,
            )
        )
        if clash is not None:
            raise SkillError(
                f"a skill named '{name}' already exists for this agent",
                status_code=409,
            )

    skill = Skill(
        name=name,
        scope="agent-local" if owner_agent_id else "global",
        owner_agent_id=owner_agent_id,
        status="draft",
    )
    db.add(skill)
    await db.flush()

    target = draft_dir(skill)
    if target.exists():
        # Same-name ownerless drafts share the root — suffix the dir and
        # retitle so name == dir still holds.
        base = name
        suffix = 2
        while (Path(settings.skills_drafts_root) / f"{base}-{suffix}").exists():
            suffix += 1
        skill.name = f"{base}-{suffix}"
        target = draft_dir(skill)
        _retitle(target_name=skill.name, source_dir=source_dir)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source_dir, target)
    return skill


def _retitle(*, target_name: str, source_dir: Path) -> None:
    """Rewrite the `name:` field in a copied SKILL.md (name == dir rule)."""
    import re

    skill_md = source_dir / "SKILL.md"
    if skill_md.is_file():
        text = skill_md.read_text(encoding="utf-8", errors="replace")
        skill_md.write_text(
            re.sub(r"(?m)^name:\s*\S+", f"name: {target_name}", text, count=1),
            encoding="utf-8",
        )


async def publish(
    db: AsyncSession,
    skill: Skill,
    *,
    scope: str,
    owner_agent_id: str | None = None,
    availability: str = "all",
    agent_ids: list[str] | None = None,
    change_summary: str | None = None,
    validation: dict | None = None,
    source_run_id: str | None = None,
) -> SkillRevision:
    """Publish a draft or snapshot an agent-local working copy.

    source dir: draft → workspace skill-drafts dir; published agent-local →
    live workspace dir (snapshot). Publishing to agent-local also syncs the
    content into the live workspace dir so it goes live immediately.
    """
    if scope not in ("global", "agent-local"):
        raise SkillError("publish scope must be 'global' or 'agent-local'")
    if scope == "agent-local" and not (owner_agent_id or skill.owner_agent_id):
        raise SkillError("agent-local publish requires an owner agent")

    if skill.status == "draft":
        source = draft_dir(skill)
    elif skill.scope == "agent-local":
        source = live_local_dir(skill)
    else:
        current = await _current_revision(db, skill)
        source = revision_abs_path(skill, current) if current else None
    if source is None or not source.is_dir():
        raise SkillError("nothing to publish — source directory is missing")

    if scope == "global":
        # NULL owner_agent_id defeats the (name, scope, owner) unique
        # constraint in SQLite — enforce global-name uniqueness here.
        clash = await db.scalar(
            select(Skill).where(
                Skill.scope == "global",
                Skill.name == skill.name,
                Skill.id != skill.id,
            )
        )
        if clash is not None:
            raise SkillError(
                f"a global skill named '{skill.name}' already exists — "
                "rename or publish a revision of that skill instead",
                status_code=409,
            )

    # Promoting a live agent-local copy to global retires the workspace dir —
    # its bytes are snapshotted into the new revision, and leaving the dir
    # would let the live copy keep shadowing the global row for its owner.
    retired_live_dir = (
        live_local_dir(skill)
        if scope == "global" and skill.scope == "agent-local" and skill.status != "draft"
        else None
    )
    was_draft_dir = source if skill.status == "draft" else None
    revision = await _next_revision(db, skill, source, change_summary, validation, source_run_id)
    skill.scope = scope
    skill.status = "published"
    if scope == "agent-local":
        skill.owner_agent_id = owner_agent_id or skill.owner_agent_id
        # Drafts publish INTO the live dir; an already-live source is the
        # same dir — copying onto itself is skipped by the identical paths.
        if source.resolve() != live_local_dir(skill).resolve():
            _copy_to_live_local(skill, source)
    else:
        skill.owner_agent_id = None
        skill.availability = availability
        # Assignments are rewritten wholesale on every publish.
        await db.execute(
            SkillAssignment.__table__.delete().where(SkillAssignment.skill_id == skill.id)
        )
        if availability == "selected":
            for agent_id in agent_ids or []:
                db.add(SkillAssignment(skill_id=skill.id, agent_id=agent_id))
    # A published draft leaves no stale copy in skill-drafts/.
    if was_draft_dir is not None and was_draft_dir.is_dir():
        shutil.rmtree(was_draft_dir)
    if retired_live_dir is not None and retired_live_dir.is_dir():
        shutil.rmtree(retired_live_dir)
    await db.flush()
    return revision


async def promote(
    db: AsyncSession,
    skill: Skill,
    *,
    availability: str = "all",
    agent_ids: list[str] | None = None,
    change_summary: str | None = None,
    validation: dict | None = None,
) -> SkillRevision:
    """Promote agent-local → global: same row, history preserved (Q7)."""
    if skill.scope != "agent-local":
        raise SkillError("only agent-local skills can be promoted")
    return await publish(
        db,
        skill,
        scope="global",
        availability=availability,
        agent_ids=agent_ids,
        change_summary=change_summary or "promoted to global",
        validation=validation,
    )


async def duplicate(
    db: AsyncSession, skill: Skill, *, owner_agent_id: str | None, new_name: str | None = None
) -> Skill:
    """Copy a skill's current content into a new draft.

    With an owner the draft lands in the agent's workspace skill-drafts dir;
    ownerless duplicates land in `data/skills-drafts/` like manual drafts.
    """
    source: Path | None = None
    if skill.status == "draft":
        source = draft_dir(skill)
    elif skill.scope == "agent-local" and live_local_dir(skill).is_dir():
        source = live_local_dir(skill)
    else:
        current = await _current_revision(db, skill)
        if current is not None:
            source = revision_abs_path(skill, current)
    if source is None or not source.is_dir():
        raise SkillError("nothing to duplicate — source directory is missing")

    base = (new_name or f"{skill.name}-copy").strip().lower() or f"{skill.name}-copy"
    name = base
    suffix = 2
    while True:
        if owner_agent_id:
            taken = (
                await db.scalar(
                    select(Skill).where(
                        Skill.name == name,
                        Skill.scope == "agent-local",
                        Skill.owner_agent_id == owner_agent_id,
                    )
                )
                is not None
            ) or (Path(settings.workspace_root) / owner_agent_id / "skill-drafts" / name).exists()
        else:
            taken = (
                await db.scalar(
                    select(Skill).where(
                        Skill.name == name,
                        Skill.status == "draft",
                        Skill.owner_agent_id.is_(None),
                    )
                )
                is not None
            ) or (Path(settings.skills_drafts_root) / name).exists()
        if not taken:
            break
        name = f"{base}-{suffix}"
        suffix += 1

    draft = Skill(
        name=name,
        scope="agent-local" if owner_agent_id else "global",
        owner_agent_id=owner_agent_id,
        status="draft",
    )
    db.add(draft)
    target = draft_dir(draft)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, target)
    # The copy's SKILL.md still names the original — retitle it so the draft
    # validates (name must equal dir name).
    import re

    skill_md = target / "SKILL.md"
    if skill_md.is_file():
        text = skill_md.read_text(encoding="utf-8", errors="replace")
        skill_md.write_text(
            re.sub(r"(?m)^name:\s*\S+", f"name: {name}", text, count=1),
            encoding="utf-8",
        )
    await db.flush()
    return draft


async def restore(db: AsyncSession, skill: Skill, revision_number: int) -> SkillRevision:
    """Restore-as-new-revision: old rev's bytes become the next rev."""
    old = await db.scalar(
        select(SkillRevision).where(
            SkillRevision.skill_id == skill.id,
            SkillRevision.revision_number == revision_number,
        )
    )
    if old is None:
        raise SkillError(f"revision {revision_number} not found", status_code=404)
    source = revision_abs_path(skill, old)
    if not source.is_dir():
        raise SkillError("revision bytes are missing from storage")
    revision = await _next_revision(db, skill, source, f"restore of revision {revision_number}")
    # Agent-local restore also rewinds the live working copy.
    if skill.scope == "agent-local" and skill.status == "published":
        _copy_to_live_local(skill, source)
    await db.flush()
    return revision


async def set_status(db: AsyncSession, skill: Skill, status: str) -> None:
    """disable / archive — status changes only, bytes retained."""
    if status not in ("published", "disabled", "archived"):
        raise SkillError(f"invalid status '{status}'")
    if skill.status == "draft":
        raise SkillError("drafts can only be deleted, not disabled/archived")
    skill.status = status
    await db.flush()


async def purge(db: AsyncSession, skill: Skill) -> None:
    """Hard-delete a skill's store bytes + rows.

    Guards: must be archived/disabled, and no active run's manifest may pin
    one of its revisions. Built-ins can't purge — they ship with the app
    (archive to hide); their shipped bytes are never deleted.
    """
    if skill.scope == "built-in":
        raise SkillError("built-in skills cannot be purged — archive instead")
    if skill.status not in ("archived", "disabled"):
        raise SkillError("archive or disable the skill before purging", status_code=409)

    from ..models.execution_manifest import ExecutionManifest
    from ..models.run import Run

    rev_ids = (
        (await db.execute(select(SkillRevision.id).where(SkillRevision.skill_id == skill.id)))
        .scalars()
        .all()
    )
    if rev_ids:
        active_runs = select(Run.id).where(Run.status.in_(ACTIVE_RUN_STATUSES))
        manifests = (
            (
                await db.execute(
                    select(ExecutionManifest.skill_revision_ids).where(
                        ExecutionManifest.run_id.in_(active_runs)
                    )
                )
            )
            .scalars()
            .all()
        )
        pinned = {str(r) for r in rev_ids}
        for raw in manifests:
            try:
                pins = json.loads(raw or "{}")
            except (TypeError, json.JSONDecodeError):
                continue
            values = pins.values() if isinstance(pins, dict) else pins
            for pin in values:
                if str(pin).replace("rev:", "") in pinned:
                    raise SkillError(
                        "an active run pins a revision of this skill — purge is blocked",
                        status_code=409,
                    )

    # Delete stored revisions (store root only — never skills_dir) and, for
    # agent-local skills, the live workspace dir — otherwise the workspace
    # scan would resurrect the skill on the next run.
    store_dir = _store_root() / skill.id
    if store_dir.is_dir():
        shutil.rmtree(store_dir)
    if skill.scope == "agent-local" and skill.owner_agent_id:
        live = live_local_dir(skill)
        if live.is_dir():
            shutil.rmtree(live)
    await db.delete(skill)
    await db.flush()


async def delete_draft(db: AsyncSession, skill: Skill) -> None:
    """Delete a draft: rm the workspace dir + drop the row. No guards."""
    if skill.status != "draft":
        raise SkillError("only drafts can be deleted outright")
    path = draft_dir(skill)
    if path.is_dir():
        shutil.rmtree(path)
    await db.delete(skill)
    await db.flush()
