"""Skills API — list, import (zip), delete, promote skills (D11b, D11c).

Skills are stored at:
- System-level: skills/ (shared across all agents, operator-managed)
- Per-agent: workspace/skills/{agent_id}/ (agent-created via write_file)

This API manages system-level skills. Per-agent skills are managed by the agent
itself via write_file (in the workspace sandbox).
"""

import io
import shutil
import zipfile
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel

from ..auth import require_operator
from ..config import settings
from ..models.operator import Operator
from ..skills.loader import _load_skill_from_dir, list_skills

router = APIRouter(prefix="/api/skills", tags=["skills"])

# System-level skills directory (from config — repo root/skills)
SKILLS_DIR = settings.skills_dir


@router.get("")
async def get_skills(
    operator: Operator = Depends(require_operator),
) -> dict:
    """List all installed system-level skills."""
    SKILLS_DIR.mkdir(parents=True, exist_ok=True)

    skills: list[dict] = []
    if SKILLS_DIR.exists():
        for entry in sorted(SKILLS_DIR.iterdir()):
            if not entry.is_dir():
                continue
            skill = _load_skill_from_dir(entry, "system")
            if skill:
                # Count resources
                resource_count = sum(1 for f in entry.rglob("*") if f.is_file() and f.name != "SKILL.md")
                skills.append({
                    "name": skill.name,
                    "description": skill.description,
                    "source": "system",
                    "path": str(entry),
                    "resource_count": resource_count,
                    "license": skill.license,
                    "compatibility": skill.compatibility,
                })

    return {"skills": skills, "count": len(skills)}


@router.post("/import")
async def import_skill_zip(
    file: UploadFile = File(...),
    operator: Operator = Depends(require_operator),
) -> dict:
    """Import a skill from a zip file.

    The zip must contain a SKILL.md at the root (or inside a single top-level dir).
    The skill is extracted to skills/{name}/ (system-level).
    """
    if not file.filename or not file.filename.endswith(".zip"):
        raise HTTPException(status_code=400, detail="File must be a .zip")

    content = await file.read()
    try:
        zf = zipfile.ZipFile(io.BytesIO(content))
    except zipfile.BadZipFile:
        raise HTTPException(status_code=400, detail="Invalid zip file")

    # Find SKILL.md in the zip — either at root or inside a single top-level dir
    names = zf.namelist()
    skill_md_path = None
    top_dir = None

    # Check for SKILL.md at root
    if "SKILL.md" in names:
        skill_md_path = "SKILL.md"
        top_dir = ""
    else:
        # Check for SKILL.md inside a single top-level directory
        top_dirs = set()
        for name in names:
            if "/" in name:
                top_dirs.add(name.split("/")[0])
        if len(top_dirs) == 1:
            candidate = f"{top_dirs.pop()}/SKILL.md"
            if candidate in names:
                skill_md_path = candidate
                top_dir = names[0].split("/")[0]

    if skill_md_path is None:
        raise HTTPException(
            status_code=400,
            detail="Zip must contain SKILL.md at root or inside a single top-level directory",
        )

    # Read SKILL.md to get the skill name
    skill_md_content = zf.read(skill_md_path).decode("utf-8", errors="replace")
    from ..skills.loader import _parse_frontmatter

    fm, _ = _parse_frontmatter(skill_md_content)
    skill_name = fm.get("name", "")
    if not skill_name:
        raise HTTPException(status_code=400, detail="SKILL.md must have a 'name' field in frontmatter")

    # Validate name (Agent Skills spec: lowercase, numbers, hyphens)
    import re

    if not re.match(r"^[a-z0-9]+(-[a-z0-9]+)*$", skill_name):
        raise HTTPException(
            status_code=400,
            detail=f"Invalid skill name '{skill_name}'. Must be lowercase letters, numbers, and hyphens only.",
        )

    # Check if skill already exists
    skill_dir = SKILLS_DIR / skill_name
    if skill_dir.exists():
        raise HTTPException(
            status_code=409,
            detail=f"Skill '{skill_name}' already exists. Delete it first or use a different name.",
        )

    # Extract to skills/{name}/
    SKILLS_DIR.mkdir(parents=True, exist_ok=True)
    skill_dir.mkdir(parents=True)

    for name in names:
        # Skip directories (they'll be created by file extraction)
        if name.endswith("/"):
            continue
        # Strip the top-level dir prefix if present
        if top_dir:
            rel = name[len(top_dir) + 1:]
        else:
            rel = name
        if not rel:
            continue

        # Security: prevent path traversal
        target = (skill_dir / rel).resolve()
        if not str(target).startswith(str(skill_dir.resolve())):
            continue

        target.parent.mkdir(parents=True, exist_ok=True)
        with open(target, "wb") as f:
            f.write(zf.read(name))

    return {
        "imported": True,
        "name": skill_name,
        "path": str(skill_dir),
        "files": len([n for n in names if not n.endswith("/")]),
    }


@router.delete("/{skill_name}")
async def delete_skill(
    skill_name: str,
    operator: Operator = Depends(require_operator),
) -> dict:
    """Delete a system-level skill."""
    skill_dir = SKILLS_DIR / skill_name

    # Security: validate the path stays within skills/
    if not str(skill_dir.resolve()).startswith(str(SKILLS_DIR.resolve())):
        raise HTTPException(status_code=400, detail="Invalid skill name")

    if not skill_dir.exists():
        raise HTTPException(status_code=404, detail=f"Skill '{skill_name}' not found")

    shutil.rmtree(skill_dir)
    return {"deleted": True, "name": skill_name}


@router.post("/{skill_name}/promote")
async def promote_skill(
    skill_name: str,
    agent_id: str,
    operator: Operator = Depends(require_operator),
) -> dict:
    """Promote a per-agent skill to system-level.

    Copies the skill from workspace/skills/{agent_id}/{skill_name}/ to skills/{skill_name}/.
    """
    from ..config import settings

    agent_skill_dir = settings.workspace_root / agent_id / "skills" / skill_name
    if not agent_skill_dir.exists():
        raise HTTPException(
            status_code=404,
            detail=f"Skill '{skill_name}' not found in agent {agent_id} workspace",
        )

    target_dir = SKILLS_DIR / skill_name
    if target_dir.exists():
        raise HTTPException(
            status_code=409,
            detail=f"Skill '{skill_name}' already exists at system level",
        )

    SKILLS_DIR.mkdir(parents=True, exist_ok=True)
    shutil.copytree(agent_skill_dir, target_dir)

    return {
        "promoted": True,
        "name": skill_name,
        "from": str(agent_skill_dir),
        "to": str(target_dir),
    }
