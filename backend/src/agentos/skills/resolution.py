"""Skill resolution — which skills an agent sees, and which bytes a run loads.

The DB is the authority for governed scopes: built-ins and globals resolve
through Skill/SkillRevision rows (published + assigned + not disabled).
Agent-local stays a live workspace scan — the agent can create or edit its
own skills via write_file and they take effect next run (Q3: the
self-improvement loop is preserved). Drafts live in `skill-drafts/` — never
scanned.

Precedence on name collision: agent-local > global > built-in.

Pins: at run start the pipeline stores `{name: "rev:<revision_id>" |
"live:<sha256>"}` in the manifest's skill_revision_ids. Mid-run,
skills_load/read_resource serve the pinned revision for governed scopes so
a publish can't wobble a live run; agent-local serves the live dir (the pin
records its hash for provenance).
"""

from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..models.skill import Skill, SkillAssignment, SkillRevision
from .builtins import hash_skill_dir
from .loader import _load_skill_from_dir

PIN_REVISION = "rev:"
PIN_LIVE = "live:"


@dataclass
class ResolvedSkill:
    """One skill in an agent's effective menu, resolved to a concrete dir."""

    name: str
    description: str
    scope: str  # built-in | global | agent-local
    path: Path
    skill_id: str | None = None
    revision_id: str | None = None
    pin: str = ""
    # Names of same-named skills this one shadows (UI surfaces it).
    shadows: list[str] = field(default_factory=list)


def revision_path(scope: str, storage_path: str) -> Path:
    """Resolve a revision's storage_path to an absolute dir.

    Built-ins resolve against the shipped skills_dir; governed revisions
    (global, published agent-local snapshots) resolve against the
    skills-store root.
    """
    if scope == "built-in":
        return Path(settings.skills_dir) / storage_path
    return Path(settings.skills_store_root) / storage_path


def _agent_skills_dir(agent_id: str) -> Path:
    return Path(settings.workspace_root) / agent_id / "skills"


async def resolve_effective_skills(db: AsyncSession, agent_id: str) -> list[ResolvedSkill]:
    """The agent's effective skill set: live locals + governed published rows."""
    resolved: dict[str, ResolvedSkill] = {}

    # Governed scopes via DB — published only; disabled/archived are not
    # loaded. Global respects availability/assignments.
    assigned_ids = select(SkillAssignment.skill_id).where(SkillAssignment.agent_id == agent_id)
    rows = (
        (
            await db.execute(
                select(Skill).where(
                    Skill.status == "published",
                    or_(
                        Skill.scope == "built-in",
                        (Skill.scope == "agent-local") & (Skill.owner_agent_id == agent_id),
                        (Skill.scope == "global")
                        & or_(
                            Skill.availability == "all",
                            Skill.id.in_(assigned_ids),
                        ),
                    ),
                )
            )
        )
        .scalars()
        .all()
    )

    # Two passes so precedence lands: built-in first, then global (overrides
    # built-in on collision), then agent-local live scan wins overall.
    for scope in ("built-in", "global", "agent-local"):
        for skill in rows:
            if skill.scope != scope or skill.current_revision_id is None:
                continue
            revision = await db.scalar(
                select(SkillRevision).where(SkillRevision.id == skill.current_revision_id)
            )
            if revision is None:
                continue
            path = revision_path(scope, revision.storage_path)
            if not path.is_dir():
                continue
            loaded = _load_skill_from_dir(path, scope)
            if loaded is None:
                continue
            existing = resolved.get(skill.name)
            shadows = [*existing.shadows, existing.scope] if existing else []
            resolved[skill.name] = ResolvedSkill(
                name=skill.name,
                description=loaded.description,
                scope=scope,
                path=path,
                skill_id=skill.id,
                revision_id=revision.id,
                pin=f"{PIN_REVISION}{revision.id}",
                shadows=shadows,
            )

    # Agent-local LIVE scan — workspace copy wins over any governed row of
    # the same name, and needs no DB row to exist (it may not be indexed yet).
    # A disabled/archived row suppresses the live dir — otherwise the
    # operator's status change would be unobservable.
    local_status = {
        s.name: s.status
        for s in (
            await db.execute(
                select(Skill.name, Skill.status).where(
                    Skill.scope == "agent-local", Skill.owner_agent_id == agent_id
                )
            )
        ).all()
    }
    local_dir = _agent_skills_dir(agent_id)
    if local_dir.is_dir():
        for entry in sorted(local_dir.iterdir()):
            if not entry.is_dir():
                continue
            status = local_status.get(entry.name)
            if status is not None and status != "published":
                continue
            loaded = _load_skill_from_dir(entry, "agent-local")
            if loaded is None:
                continue
            existing = resolved.get(loaded.name)
            shadows = [*existing.shadows, existing.scope] if existing else []
            resolved[loaded.name] = ResolvedSkill(
                name=loaded.name,
                description=loaded.description,
                scope="agent-local",
                path=entry,
                # Carry identity so live skills still link to usage/history.
                skill_id=(
                    existing.skill_id if existing and existing.scope == "agent-local" else None
                ),
                pin=f"{PIN_LIVE}{hash_skill_dir(entry)}",
                shadows=shadows,
            )

    return sorted(resolved.values(), key=lambda s: s.name)


def format_menu(resolved: list[ResolvedSkill]) -> str:
    """Format resolved skills as the system-prompt menu (names + descriptions)."""
    if not resolved:
        return ""
    lines = ["The following skills are available. Use `skills_load(name)` to load one."]
    for s in resolved:
        desc = f" — {s.description}" if s.description else ""
        lines.append(f"- **{s.name}**{desc}")
    return "\n".join(lines)


def skill_pins(resolved: list[ResolvedSkill]) -> dict[str, str]:
    """The manifest pin map: name → 'rev:<id>' | 'live:<hash>'."""
    return {s.name: s.pin for s in resolved if s.pin}


async def pinned_dir(db: AsyncSession, resolved: ResolvedSkill, run_id: str | None) -> Path:
    """The directory a run should load for this skill.

    Governed scopes: if the run pinned a different revision than current
    (a publish landed mid-run), serve the pinned rev — the menu was built
    from it. Agent-local always serves the live dir (its pin is a provenance
    hash, not a frozen copy). A missing pinned rev falls back to current —
    honest behavior over serving bytes that don't exist.
    """
    if resolved.scope == "agent-local" or not run_id:
        return resolved.path

    from ..models.execution_manifest import ExecutionManifest

    manifest = await db.scalar(
        select(ExecutionManifest.skill_revision_ids).where(ExecutionManifest.run_id == run_id)
    )
    pins_raw = manifest if manifest else None
    if not pins_raw:
        return resolved.path
    import json

    pins = json.loads(pins_raw)
    pin = pins.get(resolved.name, "") if isinstance(pins, dict) else ""
    if not pin.startswith(PIN_REVISION):
        return resolved.path
    pinned_id = pin[len(PIN_REVISION) :]
    if pinned_id == resolved.revision_id:
        return resolved.path
    pinned_rev = await db.scalar(
        select(SkillRevision).where(
            SkillRevision.id == pinned_id, SkillRevision.skill_id == resolved.skill_id
        )
    )
    if pinned_rev is None:
        return resolved.path
    path = revision_path(resolved.scope, pinned_rev.storage_path)
    return path if path.is_dir() else resolved.path
