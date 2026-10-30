"""Skill capability implementations — skills_list, skills_load, skills_read_resource (D11b, D11c).

Skills are NOT auto-injected. The agent sees a menu (names + descriptions) in
the system prompt, then calls skills_list or skills_load to get details.

skills_read_resource reads a resource file from a skill directory. This is
needed because system-level skills live outside the workspace, so read_file
(workspace-sandboxed) can't access them. The path is scoped to the skill
directory — it cannot escape.

Resolution is DB-backed (W6): governed scopes come from published/assigned
Skill rows, agent-local from the live workspace scan. Governed skills are
served from the run's pinned revision — a mid-run publish cannot wobble a
live run.

These are called by the syscall mediator with extra_kwargs:
- agent_id: str
- db: AsyncSession
- run_id: str | None
"""

from typing import Any

from ...skills.loader import render_skill_dir
from ...skills.resolution import pinned_dir, resolve_effective_skills
from ...skills.usage import record_skill_activation_isolated
from ...skills.usage_queries import scoped_skill_usage


async def _resolve(db: Any, agent_id: str, name: str):
    """Find `name` in the agent's effective set."""
    resolved = await resolve_effective_skills(db, agent_id)
    return next((s for s in resolved if s.name == name), None)


async def skills_list(args: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
    """List available skills (name + description only)."""
    resolved = await resolve_effective_skills(kwargs["db"], kwargs["agent_id"])
    skills = [{"name": s.name, "description": s.description, "source": s.scope} for s in resolved]
    return {"skills": skills, "count": len(skills)}


async def skills_load(args: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
    """Load a specific skill's full content + resource listing.

    After loading, call skills_read_resource to read any resource files
    the skill body references (templates, checklists, data files).
    """
    db = kwargs["db"]
    resolved = await _resolve(db, kwargs["agent_id"], args["name"])
    if resolved is None:
        return {"error": f"Skill '{args['name']}' not found"}

    edits = kwargs.get("skill_edits")
    if edits is not None:
        skill = await edits.load_skill(resolved)
    else:
        path = await pinned_dir(db, resolved, kwargs.get("run_id"))
        skill = render_skill_dir(path, resolved.scope)
    if skill is None:
        return {"error": f"Skill '{args['name']}' not found"}

    # Successful load → record ONE activation per logical call (idempotent
    # event_key on call_id). Serialized under db_lock so a concurrent tool
    # in the same run can't double-flush the shared session.
    run_id = kwargs.get("run_id")
    if run_id:
        await record_skill_activation_isolated(
            resolved,
            run_id,
            "load",
            call_id=kwargs.get("call_id"),
            sub_agent_id=kwargs.get("sub_agent_id"),
        )
    return skill


async def skills_read_resource(args: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
    """Read a resource file from a skill directory.

    System-level skills live outside the workspace, so read_file can't access
    them. This capability is scoped to the skill's directory — the path cannot
    escape it.

    Args:
        skill: The skill name (from skills_list)
        resource: The resource filename (from skills_load resources listing)
    """
    db = kwargs["db"]
    resolved = await _resolve(db, kwargs["agent_id"], args["skill"])
    if resolved is None:
        return {"error": f"Skill '{args['skill']}' not found"}
    edits = kwargs.get("skill_edits")
    if edits is not None:
        try:
            out = await edits.read_resource(args["skill"], args["resource"], args.get("offset", 0))
        except Exception as exc:
            return {"error": type(exc).__name__}
        return {
            "skill": args["skill"],
            "resource": args["resource"],
            "content": out["content"],
            "size": len(out["content"].encode("utf-8")),
            "offset": out["offset"],
            "total_length": out["total_length"],
            "next_offset": out["next_offset"],
            "staged": out["staged"],
        }

    skill_dir = (await pinned_dir(db, resolved, kwargs.get("run_id"))).resolve()
    resource_path = (skill_dir / args["resource"]).resolve()
    try:
        resource_path.relative_to(skill_dir)
    except ValueError:
        return {"error": "Resource path escapes skill directory"}

    if not resource_path.is_file():
        return {"error": f"Resource not found: {args['resource']}"}

    content = resource_path.read_text(encoding="utf-8", errors="replace")
    return {
        "skill": args["skill"],
        "resource": args["resource"],
        "content": content,
        "size": resource_path.stat().st_size,
    }


async def skills_usage(args: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
    """Inspect recorded activations of a visible skill in the caller's own
    conversation scope — revision evidence, not effectiveness proof."""
    db = kwargs["db"]
    agent_id = kwargs["agent_id"]
    contact_id = kwargs.get("contact_id")
    run_id = kwargs.get("run_id")
    if not contact_id or not run_id:
        return {"error": "No conversation scope to inspect"}
    # Trusted scope: the persisted run must really belong to this
    # agent+contact — never trust model-supplied values.
    from sqlalchemy import select as _select0

    from ...models.run import Run

    run = await db.scalar(
        _select0(Run).where(
            Run.id == run_id, Run.agent_id == agent_id, Run.contact_id == contact_id
        )
    )
    if run is None:
        return {"error": "No conversation scope to inspect"}
    resolved = await _resolve(db, agent_id, args["name"])
    if resolved is None:
        return {"error": f"Skill '{args['name']}' not found"}
    skill_id = resolved.skill_id
    if skill_id is None and resolved.scope == "agent-local":
        from sqlalchemy import select as _select

        from ...models.skill import Skill

        skill_id = await db.scalar(
            _select(Skill.id).where(
                Skill.scope == "agent-local",
                Skill.owner_agent_id == agent_id,
                Skill.name == resolved.name,
            )
        )
    if skill_id is None:
        return {
            "skill": resolved.name,
            "activation_count": 0,
            "last_used_at": None,
            "coverage": "recorded activations only; older use is unknown",
            "recent": [],
        }
    result = await scoped_skill_usage(
        db, skill_id=skill_id, agent_id=agent_id, contact_id=contact_id
    )
    result["skill"] = resolved.name
    return result
