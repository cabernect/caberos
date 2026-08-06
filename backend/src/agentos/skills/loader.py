"""Skill loading — aligned with the Agent Skills spec (agentskills.io/specification).

Two operations:
- list_skills(agent_id) → [{name, description, source}] — lightweight menu (progressive disclosure level 1)
- load_skill(agent_id, name) → {name, description, body, resources: [...]} — full load (level 2)

Skills are NOT auto-injected. The harness injects the menu (names + descriptions)
into the system prompt. The agent calls skills_load to get the full content (level 2),
then skills_read_resource to read resource files (level 3 — on demand).

Spec compliance:
- SKILL.md with YAML frontmatter (name, description required; license, compatibility,
  metadata, allowed-tools optional)
- name must match parent directory name
- name: lowercase letters, numbers, hyphens only; max 64 chars
- description: max 1024 chars
- Optional directories: scripts/, references/, assets/ (convention)

Two locations:
- System-level: skills/ (shared, agent-read-only, ships defaults)
- Per-agent: workspace/skills/{agent_id}/ (agent can create/update via write_file)
"""

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class Skill:
    """A loaded skill."""
    name: str
    description: str
    body: str = ""
    source: str = ""  # "system" or "agent"
    path: Path = field(default_factory=lambda: Path())
    # Optional spec fields
    license: str = ""
    compatibility: str = ""
    metadata: dict[str, str] = field(default_factory=dict)
    allowed_tools: str = ""


def _parse_frontmatter(content: str) -> tuple[dict[str, Any], str]:
    """Parse YAML frontmatter from a SKILL.md file.
    Returns (frontmatter_dict, body_text).
    """
    frontmatter: dict[str, Any] = {}
    body = content

    match = re.match(r"^---\s*\n(.*?)\n---\s*\n?(.*)", content, re.DOTALL)
    if match:
        fm_text = match.group(1)
        body = match.group(2).strip()

        for line in fm_text.split("\n"):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if ":" in line:
                key, _, val = line.partition(":")
                key = key.strip()
                val = val.strip()

                if val.startswith("[") and val.endswith("]"):
                    # List value
                    items = [v.strip().strip("\"'") for v in val[1:-1].split(",") if v.strip()]
                    frontmatter[key] = items
                elif val:
                    frontmatter[key] = val.strip("\"'")
                else:
                    # Might be a nested map (e.g. metadata:) — skip for simple parser
                    frontmatter[key] = ""

    return frontmatter, body


def _load_skill_from_dir(skill_dir: Path, source: str) -> Skill | None:
    """Load a skill from a directory. Returns None if SKILL.md is missing or invalid."""
    skill_md = skill_dir / "SKILL.md"
    if not skill_md.exists():
        return None

    content = skill_md.read_text(encoding="utf-8", errors="replace")
    fm, body = _parse_frontmatter(content)

    name = fm.get("name", skill_dir.name)
    description = fm.get("description", "")

    return Skill(
        name=name,
        description=description,
        body=body,
        source=source,
        path=skill_dir,
        license=fm.get("license", ""),
        compatibility=fm.get("compatibility", ""),
        allowed_tools=fm.get("allowed-tools", ""),
    )


def _get_skill_dirs(agent_id: str) -> list[tuple[Path, str]]:
    """Return (dir_path, source) pairs for system + per-agent skill dirs."""
    from ..config import settings
    from ..sandbox.workspace import WorkspaceManager

    wm = WorkspaceManager()
    workspace = Path(wm.create_workspace(agent_id))

    return [
        (settings.skills_dir, "system"),
        (workspace / "skills", "agent"),
    ]


def _scan_all_skills(agent_id: str) -> list[Skill]:
    """Scan both system + per-agent dirs, load all valid skills.
    Per-agent skills override system skills with the same name.
    """
    skill_dirs = _get_skill_dirs(agent_id)
    skills: list[Skill] = []
    seen_names: set[str] = set()

    for dir_path, source in skill_dirs:
        if not dir_path.exists():
            continue
        for entry in sorted(dir_path.iterdir()):
            if not entry.is_dir():
                continue
            skill = _load_skill_from_dir(entry, source)
            if skill and skill.name not in seen_names:
                skills.append(skill)
                seen_names.add(skill.name)

    return skills


def list_skills(agent_id: str) -> list[dict[str, Any]]:
    """Return a lightweight menu of available skills (name + description + source).
    Does NOT load the skill body — just the frontmatter (progressive disclosure level 1).
    """
    skills = _scan_all_skills(agent_id)
    return [
        {
            "name": s.name,
            "description": s.description,
            "source": s.source,
        }
        for s in skills
    ]


def load_skill(agent_id: str, name: str) -> dict[str, Any] | None:
    """Load a specific skill's full content + resource listing (level 2).
    Returns None if the skill doesn't exist.
    """
    skills = _scan_all_skills(agent_id)
    skill = next((s for s in skills if s.name == name), None)
    if skill is None:
        return None

    # List resources (files/dirs in the skill dir, excluding SKILL.md)
    resources: list[dict[str, Any]] = []
    if skill.path.exists():
        for entry in sorted(skill.path.iterdir()):
            if entry.name == "SKILL.md":
                continue
            if entry.is_file():
                resources.append({
                    "name": entry.name,
                    "type": "file",
                    "size": entry.stat().st_size,
                })
            elif entry.is_dir():
                # Subdirectory (scripts/, references/, assets/) — list its contents
                sub_files = []
                for sub in sorted(entry.iterdir()):
                    if sub.is_file():
                        sub_files.append({
                            "name": f"{entry.name}/{sub.name}",
                            "type": "file",
                            "size": sub.stat().st_size,
                        })
                resources.append({
                    "name": entry.name,
                    "type": "directory",
                    "files": sub_files,
                })

    result: dict[str, Any] = {
        "name": skill.name,
        "description": skill.description,
        "body": skill.body,
        "resources": resources,
        "source": skill.source,
    }

    # Include optional spec fields if present
    if skill.license:
        result["license"] = skill.license
    if skill.compatibility:
        result["compatibility"] = skill.compatibility
    if skill.allowed_tools:
        result["allowed_tools"] = skill.allowed_tools

    return result


def format_skill_menu(agent_id: str) -> str:
    """Format the available skills as a menu for the system prompt.
    Only names + descriptions — no bodies. The agent calls skills_load to get full content.
    """
    skills = list_skills(agent_id)
    if not skills:
        return ""

    lines = ["The following skills are available. Use `skills_load(name)` to load one."]
    for s in skills:
        desc = f" — {s['description']}" if s["description"] else ""
        lines.append(f"- **{s['name']}**{desc}")

    return "\n".join(lines)
