"""Skill capability implementations — skills_list, skills_load, skills_read_resource (D11b, D11c).

Skills are NOT auto-injected. The agent sees a menu (names + descriptions) in
the system prompt, then calls skills_list or skills_load to get details.

skills_read_resource reads a resource file from a skill directory. This is
needed because system-level skills live outside the workspace, so read_file
(workspace-sandboxed) can't access them. The path is scoped to the skill
directory — it cannot escape.

These are called by the syscall mediator with extra_kwargs:
- agent_id: str
"""

from typing import Any

from ...skills.loader import list_skills, load_skill


async def skills_list(args: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
    """List available skills (name + description only)."""
    agent_id = kwargs["agent_id"]
    skills = list_skills(agent_id)
    return {"skills": skills, "count": len(skills)}


async def skills_load(args: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
    """Load a specific skill's full content + resource listing.

    After loading, call skills_read_resource to read any resource files
    the skill body references (templates, checklists, data files).
    """
    agent_id = kwargs["agent_id"]
    name = args["name"]

    skill = load_skill(agent_id, name)
    if skill is None:
        return {"error": f"Skill '{name}' not found"}
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
    agent_id = kwargs["agent_id"]
    skill_name = args["skill"]
    resource_name = args["resource"]

    from ...skills.loader import _scan_all_skills

    skills = _scan_all_skills(agent_id)
    skill_obj = next((s for s in skills if s.name == skill_name), None)
    if skill_obj is None:
        return {"error": f"Skill '{skill_name}' not found"}

    # Validate the resource path — must stay within the skill directory
    resource_path = (skill_obj.path / resource_name).resolve()
    skill_dir = skill_obj.path.resolve()
    try:
        resource_path.relative_to(skill_dir)
    except ValueError:
        return {"error": "Resource path escapes skill directory"}

    if not resource_path.is_file():
        return {"error": f"Resource not found: {resource_name}"}

    content = resource_path.read_text(encoding="utf-8", errors="replace")
    return {
        "skill": skill_name,
        "resource": resource_name,
        "content": content,
        "size": resource_path.stat().st_size,
    }
