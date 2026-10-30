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

import asyncio
import hashlib
import json
import logging
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..models.skill import Skill, SkillAssignment, SkillRevision
from .builtins import hash_skill_dir
from .resolution import ResolvedSkill
from .validate import _AGENT_ID_RE, _NAME_RE

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
    if not _NAME_RE.fullmatch(skill.name) or not _AGENT_ID_RE.fullmatch(skill.owner_agent_id):
        raise SkillError("agent-local skill identity is not path-safe")
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
    live workspace dir (snapshot). Publishing to agent-local also syncs
    the content into the live workspace dir so it goes live immediately.
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

    # NULL owner_agent_id defeats the (name, scope, owner) unique
    # constraint in SQLite, so name uniqueness is enforced here — for
    # global rows (always NULL owner) and for the effective agent-local
    # owner alike.
    owner = owner_agent_id or skill.owner_agent_id
    clash = await db.scalar(
        select(Skill).where(
            Skill.name == skill.name,
            Skill.scope == scope,
            Skill.id != skill.id,
            Skill.owner_agent_id.is_(None) if scope == "global" else Skill.owner_agent_id == owner,
        )
    )
    if clash is not None:
        # A draft carrying an occupied name is a working copy of that
        # lineage — land its content as the existing row's next revision.
        if skill.status == "draft" and clash.status == "published":
            return await _publish_draft_as_revision(
                db,
                draft=skill,
                target=clash,
                source=source,
                scope=scope,
                availability=availability,
                agent_ids=agent_ids,
                change_summary=change_summary,
                validation=validation,
                source_run_id=source_run_id,
            )
        if scope == "global":
            raise SkillError(
                f"a global skill named '{skill.name}' already exists — "
                "rename or publish a revision of that skill instead",
                status_code=409,
            )
        raise SkillError(
            f"an agent-local skill named '{skill.name}' already exists for "
            f"this agent (status: {clash.status}) — restore it or rename "
            "the draft",
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


async def _publish_draft_as_revision(
    db: AsyncSession,
    *,
    draft: Skill,
    target: Skill,
    source: Path,
    scope: str,
    availability: str,
    agent_ids: list[str] | None,
    change_summary: str | None,
    validation: dict | None,
    source_run_id: str | None,
) -> SkillRevision:
    """Land a same-name draft's content as the target row's next revision.

    The published row keeps its identity — revision history, assignments
    and run pins stay on the right lineage — while the draft row and its
    dir are retired.
    """
    revision = await _next_revision(db, target, source, change_summary, validation, source_run_id)
    if scope == "global":
        target.availability = availability
        await db.execute(
            SkillAssignment.__table__.delete().where(SkillAssignment.skill_id == target.id)
        )
        if availability == "selected":
            for agent_id in agent_ids or []:
                db.add(SkillAssignment(skill_id=target.id, agent_id=agent_id))
    else:
        _copy_to_live_local(target, source)
    path = draft_dir(draft)
    if path.is_dir():
        shutil.rmtree(path)
    await db.delete(draft)
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


async def active_run_pins_skill(db: AsyncSession, skill: Skill) -> bool:
    """True when an active run's execution manifest pins one of the skill's
    revisions (pins carry a `rev:` prefix over the revision id)."""
    from ..models.execution_manifest import ExecutionManifest
    from ..models.run import Run

    rev_ids = (
        (await db.execute(select(SkillRevision.id).where(SkillRevision.skill_id == skill.id)))
        .scalars()
        .all()
    )
    if not rev_ids:
        return False
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
                return True
    return False


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

    if await active_run_pins_skill(db, skill):
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


# ---------------------------------------------------------------------------
# SkillEditSession — generic staged local-skill revision session.
#
# A bounded editing surface over one agent's local skills. The ordinary tools
# (read_file / write_file / skills_load / skills_read_resource) delegate the
# same-name operation here when the mediator supplies `skill_edits`; nothing
# lands on disk or in the DB until publish() with a precondition callback.
# ---------------------------------------------------------------------------

_MAX_CAPTURE_FILES = 200
_MAX_CAPTURE_BYTES = 5 * 1024 * 1024
_MAX_EDIT_FILES = 32
_MAX_EDIT_BYTES = 1024 * 1024
_MAX_READ_CHARS = 4000

_agent_edit_locks: dict[str, "asyncio.Lock"] = {}


def _edit_lock(agent_id: str) -> "asyncio.Lock":
    lock = _agent_edit_locks.get(agent_id)
    if lock is None:
        lock = asyncio.Lock()
        _agent_edit_locks[agent_id] = lock
    return lock


def _safe_name(name: str) -> str:
    if (
        not isinstance(name, str)
        or not name
        or len(name) > 64
        or "/" in name
        or "\\" in name
        or name.startswith(".")
        or any(
            c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_"
            for c in name
        )
    ):
        raise SkillError(f"Invalid skill name: {name!r}")
    return name


def _resource_rel(value: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or "\\" in value
        or "\0" in value
        or ":" in value
        or value.startswith("/")
        or any(part in ("", ".", "..") for part in value.split("/"))
    ):
        raise SkillError(f"Invalid skill resource path: {value!r}")
    return value


def _lexical_safe(path: Path, root: Path | None = None) -> Path:
    """Reject symlinked roots/ancestors/descendants BEFORE resolving."""
    lexical = Path(os.path.abspath(path))
    if any(p.is_symlink() for p in (lexical, *lexical.parents)):
        raise SkillError("Symlinked skill path")
    if root is not None:
        lexical.relative_to(_lexical_safe(root))
    return lexical


def _capture(path: Path) -> dict[str, bytes] | None:
    """Captured path->bytes map; None when absent. Enforces caps, no symlinks."""
    path = _lexical_safe(path)
    if not path.exists():
        return None
    if not path.is_dir():
        raise SkillError("Skill path is not a directory")
    from .builtins import _IGNORED_NAMES

    files: dict[str, bytes] = {}
    total = 0
    for child in sorted(path.rglob("*")):
        _lexical_safe(child, root=path)
        rel = child.relative_to(path).as_posix()
        if any(part in _IGNORED_NAMES for part in rel.split("/")):
            continue
        if child.is_dir():
            continue
        if not child.is_file():
            raise SkillError("Non-regular skill resource")
        size = child.stat().st_size  # check before reading arbitrarily big files
        total += size
        if len(files) >= _MAX_CAPTURE_FILES or total > _MAX_CAPTURE_BYTES:
            raise SkillError("Skill exceeds inspection limits")
        body = child.read_bytes()
        files[rel] = body
    return files


def _tree_hash(files: dict[str, bytes] | None) -> str | None:
    """Canonical path+bytes digest — aligned with hash_skill_dir semantics."""
    if files is None:
        return None
    digest = hashlib.sha256()
    for name, body in sorted(files.items()):
        digest.update(name.encode())
        digest.update(b"\0")
        digest.update(body)
        digest.update(b"\0")
    return digest.hexdigest()


class SkillEditSession:
    """Staged local-skill edits bound to a captured effective-skill snapshot.

    `resolved_skills` is the trusted effective list for the actor — edits
    can only target names visible there, and the bytes loaded/captured come
    from the resolved source, never from model-supplied paths or ids.
    """

    def __init__(
        self,
        db: AsyncSession,
        agent_id: str,
        resolved_skills: list[ResolvedSkill],
    ) -> None:
        _safe_name(agent_id)
        self.db = db
        self.agent_id = agent_id
        self._resolved = {s.name: s for s in resolved_skills}
        # name -> {"source": dict|None, "baseline": dict|None(absent), "staged": {path:bytes}}
        self._skills: dict[str, dict] = {}
        self._temps: list[Path] = []
        self._closed = False
        self._mu = asyncio.Lock()  # serialize staging/DB sections

    # -- internal ----------------------------------------------------------

    def _root(self) -> Path:
        return _lexical_safe(Path(settings.workspace_root) / self.agent_id / "skills")

    def _local_target(self, name: str) -> Path:
        return _lexical_safe(self._root() / _safe_name(name), root=self._root())

    def _local_row(self, name: str) -> Skill | None:
        return self.db.scalar(
            select(Skill).where(
                Skill.scope == "agent-local",
                Skill.owner_agent_id == self.agent_id,
                Skill.name == name,
            )
        )

    async def _prepare(self, name: str, for_write: bool = False) -> dict:
        async with self._mu:
            return await self._prepare_locked(name, for_write=for_write)

    async def _prepare_locked(self, name: str, for_write: bool = False) -> dict:
        """One-time capture of the same-name baseline + resolved source."""
        _safe_name(name)
        if name in self._skills:
            state = self._skills[name]
            if for_write and not state.get("inspected"):
                raise SkillError("Skill must be inspected before writing")
            return state
        if for_write:
            raise SkillError("Skill must be inspected before writing")

        resolved = self._resolved.get(name)
        target_dir = self._local_target(name)
        baseline = _capture(target_dir)

        # An existing local row that no longer resolves is stale/hidden —
        # never silently treated as absent-new, in EVERY source case.
        row = await self._local_row(name)
        if row is not None and (resolved is None or row.status != "published"):
            if row.status == "published" and resolved is not None and row.id == resolved.skill_id:
                pass  # the row we resolved is this same published row
            elif (
                resolved is not None
                and row.status == "published"
                and resolved.scope == "agent-local"
                and resolved.skill_id is None
            ):
                pass  # live dir not yet indexed — resolved path IS this dir
            elif resolved is None:
                raise SkillError("Skill exists but is not visible")
        if resolved is None:
            if row is not None:
                raise SkillError("Skill exists but is not visible")
            if baseline is not None:
                # A local dir exists but the row is gone — not absent-new.
                raise SkillError("Unresolvable existing local skill")
            source = None
            source_identity = None
        else:
            src_dir = _lexical_safe(resolved.path)
            # Constrain the source to its configured root by scope — a
            # corrupted trusted row must not read arbitrary absolute paths.
            if resolved.scope == "agent-local":
                src_dir = _lexical_safe(src_dir, root=self._root())
            elif resolved.scope in ("global", "built-in"):
                allowed = [
                    _lexical_safe(Path(settings.skills_dir)),
                    _lexical_safe(Path(settings.skills_store_root)),
                ]
                src_dir = _lexical_safe(src_dir)
                if not any(src_dir.is_relative_to(a) for a in allowed):
                    raise SkillError("Skill source outside configured storage")
            if src_dir.resolve() == target_dir.resolve():
                source = baseline
            else:
                source = _capture(src_dir)
            if source is None:
                raise SkillError("Source skill has no readable directory")
            source_identity = {
                "scope": resolved.scope,
                # agent-local resolution may leave skill_id None — the
                # stable identity is the (owner, name) row itself.
                "skill_id": resolved.skill_id or (row.id if row else None),
                "revision_id": resolved.revision_id,
                "source_hash": _tree_hash(source),
            }

        state = {
            "inspected": True,
            "baseline": baseline,
            "source": source,
            "source_identity": source_identity,
            "resolved": resolved,
            "local_revision_id": row.current_revision_id if row else None,
            "staged": {},
        }
        self._skills[name] = state
        return state

    # -- reads (delegated from tools) --------------------------------------

    async def load_skill(self, resolved: ResolvedSkill) -> dict[str, Any]:
        """Same shape as skills_load, rendered from the CAPTURED snapshot."""
        state = await self._prepare(resolved.name)
        src = state["source"] or {}
        tmp = Path(tempfile.mkdtemp(prefix="render-"))
        self._temps.append(tmp)
        for rel, body in src.items():
            dest = tmp / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(body)
        from .loader import render_skill_dir

        rendered = render_skill_dir(tmp, resolved.scope)
        if rendered is None:
            raise SkillError("Captured skill is not renderable")
        rendered["content_hash"] = _tree_hash(src)
        rendered["source_scope"] = resolved.scope
        return rendered

    async def read_resource(self, name: str, path: str, offset: int = 0) -> dict[str, Any]:
        if type(offset) is not int or offset < 0:
            raise SkillError("Invalid resource offset")
        state = await self._prepare(name)
        rel = _resource_rel(path)
        files = dict(state["source"] if state["source"] is not None else state["baseline"] or {})
        staged_hit = rel in state["staged"]
        files.update(state["staged"])
        if rel not in files:
            raise SkillError("Skill resource not found")
        content = files[rel].decode("utf-8", "replace")
        page = content[offset : offset + _MAX_READ_CHARS]
        return {
            "name": name,
            "resource": rel,
            "content": page,
            "offset": offset,
            "total_length": len(content),
            "next_offset": offset + len(page) if offset + len(page) < len(content) else None,
            "staged": staged_hit,
        }

    async def read_file(self, path: str) -> dict[str, Any]:
        """Workspace-relative skills/{name}/{resource}; absent-new baseline."""
        rel = _resource_rel(path)
        parts = rel.split("/")
        if parts[0] != "skills" or len(parts) < 3:
            raise SkillError("Skill edits are confined to skills/{name}/...")
        name = parts[1]
        state = await self._prepare(name)
        rest = "/".join(parts[2:])
        files = dict(state["source"] or state["baseline"] or {})
        files.update(state["staged"])
        if rest not in files:
            if rest == "SKILL.md" and state["baseline"] is None and state["source"] is None:
                return {"content": None, "absent": True}  # establishes absent-new baseline
            raise SkillError("Skill file not found")
        content = files[rest].decode("utf-8", "replace")
        page = content[:_MAX_READ_CHARS]
        return {
            "content": page,
            "total_length": len(content),
            "next_offset": len(page) if len(page) < len(content) else None,
        }

    # -- staging ------------------------------------------------------------

    async def write_file(self, path: str, content: str) -> dict[str, Any]:
        rel = _resource_rel(path)
        parts = rel.split("/")
        if parts[0] != "skills" or len(parts) < 3:
            raise SkillError("Skill edits are confined to skills/{name}/...")
        name = parts[1]
        if not isinstance(content, str):
            raise SkillError("Skill files are UTF-8 text")
        state = await self._prepare(name, for_write=True)
        rel_rest = "/".join(parts[2:])
        staged = dict(state["staged"])
        staged[rel_rest] = content.encode("utf-8")
        if len(staged) > _MAX_EDIT_FILES or sum(len(v) for v in staged.values()) > _MAX_EDIT_BYTES:
            raise SkillError("Skill edit exceeds staging limits")
        state["staged"] = staged
        return {"staged": True, "path": rel}

    # -- publish ------------------------------------------------------------

    async def publish(
        self,
        *,
        reason: str,
        source_run_id: str,
        precondition: Any = None,
    ) -> dict[str, Any]:
        """Persist staged edits as immutable revisions; conflict-safe."""
        revision_ids: list[str] = []
        conflicts: list[str] = []
        errors: list[str] = []
        if precondition is not None and not asyncio.iscoroutinefunction(precondition):

            async def _pre(name: str) -> None:
                res = precondition(name)
                if asyncio.iscoroutine(res):
                    await res

            check = _pre
        else:
            check = precondition

        async with _edit_lock(self.agent_id):
            for name in sorted(self._skills):
                state = self._skills[name]
                if not state["staged"]:
                    continue
                try:
                    rid = await self._publish_one(
                        name, state, reason=reason, source_run_id=source_run_id, check=check
                    )
                    if rid:
                        revision_ids.append(rid)
                except SkillConflict:
                    conflicts.append(name)
                    await self.db.rollback()
                except Exception as exc:
                    errors.append(f"{name}: {type(exc).__name__}")
                    await self.db.rollback()
        return {"revision_ids": revision_ids, "conflicts": conflicts, "errors": errors}

    async def _publish_one(self, name, state, *, reason, source_run_id, check) -> str | None:

        # Merge staged over the captured baseline/source — a shared source's
        # own bytes are never touched; the local target gets a full copy.
        base = dict(state["source"] or state["baseline"] or {})
        base.update(state["staged"])
        if _tree_hash(base) == _tree_hash(state["baseline"]):
            return None  # no change => no new revision

        target = self._local_target(name)
        maint = _lexical_safe(target.parent.parent / ".skill-edits")
        maint.mkdir(parents=True, exist_ok=True)
        work = Path(tempfile.mkdtemp(prefix="edit-", dir=maint))
        self._temps.append(work)
        stage = work / "next"
        backup = work / "previous"
        store_root = _lexical_safe(Path(settings.skills_store_root))
        created_stores: list[Path] = []
        installed = False
        preserve = False
        next_hash = _tree_hash(base)
        expected = _tree_hash(state["baseline"])
        try:
            stage.mkdir()
            for rel, body in base.items():
                dest = stage / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(body)
            from .validate import validate_skill_dir

            validation = validate_skill_dir(stage, expected_name=name)
            if validation["errors"]:
                raise SkillError("; ".join(validation["errors"]))
            if check is not None:
                await check(name)
            await self._verify_unchanged(name, state)

            skill = await self._local_row(name)
            _lexical_safe(store_root / (skill.id if skill else "pending"), root=store_root)
            if skill is None:
                skill = Skill(
                    name=name,
                    scope="agent-local",
                    owner_agent_id=self.agent_id,
                    status="published",
                )
                self.db.add(skill)
                await self.db.flush()
            elif skill.status != "published":
                raise SkillConflict("local-status")

            # Snapshot any unsnapshotted/drifted pre-edit bytes first — the
            # old state must be recoverable before ours is installed.
            if state["baseline"] is not None:
                latest = (
                    await self.db.get(SkillRevision, skill.current_revision_id)
                    if skill.current_revision_id
                    else None
                )
                if latest is None or latest.content_hash != expected:
                    orig = work / "original"
                    orig.mkdir()
                    for rel, body in state["baseline"].items():
                        (orig / rel).parent.mkdir(parents=True, exist_ok=True)
                        (orig / rel).write_bytes(body)
                    prior = await _next_revision(
                        self.db, skill, orig, "Snapshot before staged edit", source_run_id=None
                    )
                    created_stores.append(store_root / prior.storage_path)

            rev = await _next_revision(
                self.db, skill, stage, reason, validation, source_run_id=source_run_id
            )
            created_stores.append(store_root / rev.storage_path)

            if check is not None:
                await check(name)  # still current after DB prep
            # Final compare: source identity/hash/status AND local target
            # hash/status — but skip the local revision pointer (our own
            # _next_revision just updated it).
            await self._verify_unchanged(
                name, state, skip_local_revision=True, created_skill_id=skill.id
            )
            if _tree_hash(_capture(target)) != expected:
                raise SkillConflict("Local skill changed before publication")

            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                target.rename(backup)
            stage.rename(target)
            installed = True
            await self.db.commit()
            return rev.id
        except BaseException:
            await self.db.rollback()
            if installed:
                if _tree_hash(_capture(target)) == next_hash:
                    target.rename(work / "uncommitted")
                    if backup.exists():
                        backup.rename(target)
                else:
                    preserve = True
                    self._temps.remove(work)  # retained for recovery — NOT ours to clean
                    log.error("Newer edit preserved; backup retained under %s", work)
            elif backup.exists() and not target.exists():
                backup.rename(target)
            for p in created_stores:
                if p.exists():
                    shutil.rmtree(p)
            raise
        finally:
            if not preserve and work.exists():
                shutil.rmtree(work, ignore_errors=True)

    async def _verify_unchanged(
        self,
        name: str,
        state: dict,
        *,
        skip_local_revision: bool = False,
        created_skill_id: str | None = None,
    ) -> None:
        """Re-resolve current source identity + local row/target; mismatch =>
        conflict. `skip_local_revision` only for the post-publish check (our
        own _next_revision just bumped the local pointer)."""
        from .resolution import resolve_effective_skills

        current = {r.name: r for r in await resolve_effective_skills(self.db, self.agent_id)}
        now = current.get(name)
        ident = state["source_identity"]
        if created_skill_id is not None and now is not None and now.skill_id == created_skill_id:
            # The resolution now returns the row THIS publish just made
            # (incl. a new local shadow over a shared source) — expected.
            return
        if ident is None:
            # A row WE just created in this transaction may now resolve —
            # that's expected; any other visibility is drift.
            if now is not None and now.skill_id != created_skill_id:
                raise SkillConflict("became-visible")
        else:
            # Re-resolve the local row for id comparison — resolution can
            # leave agent-local skill_id None while the row is stable.
            row_now = await self._local_row(name)
            now_id = now.skill_id if now and now.skill_id else (row_now.id if row_now else None)
            if now is None or now.scope != ident["scope"] or now_id != ident["skill_id"]:
                raise SkillConflict("source-identity")
            if ident["scope"] != "agent-local" and now.revision_id != ident["revision_id"]:
                raise SkillConflict("source-revision")
            if ident["scope"] != "agent-local":
                src = _capture(_lexical_safe(now.path))
                if _tree_hash(src) != ident["source_hash"]:
                    raise SkillConflict("source-content")

        row = await self._local_row(name)
        if row is not None and row.status != "published":
            raise SkillConflict("local-status")
        if not skip_local_revision:
            if (row.current_revision_id if row else None) != state["local_revision_id"]:
                raise SkillConflict("local-revision")

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        for p in self._temps:
            shutil.rmtree(p, ignore_errors=True)
        self._temps.clear()


class SkillConflict(SkillError):
    """Baseline/source changed between capture and publication."""
