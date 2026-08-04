"""Agent files API — MEMORY.md, skills, workspace browser (D34, D37)."""

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import require_operator
from ..config import settings
from ..db import get_db
from ..models.operator import Operator

router = APIRouter(prefix="/api/agents", tags=["agent-files"])


def _agent_home(agent_id: str) -> Path:
    """Get the agent's home directory."""
    home = settings.agent_home_root / agent_id
    home.mkdir(parents=True, exist_ok=True)
    return home


def _memory_path(agent_id: str) -> Path:
    """Get the path to the agent's MEMORY.md file."""
    return _agent_home(agent_id) / "MEMORY.md"


def _skills_dir(agent_id: str) -> Path:
    """Get the agent's skills directory."""
    skills = _agent_home(agent_id) / "skills"
    skills.mkdir(parents=True, exist_ok=True)
    return skills


def _workspace_path(agent_id: str) -> Path:
    """Get the agent's workspace path."""
    from ..sandbox.workspace import WorkspaceManager

    wm = WorkspaceManager()
    return Path(wm.create_workspace(agent_id))


# --- MEMORY.md ---


@router.get("/{agent_id}/memory")
async def get_memory(
    agent_id: str,
    operator: Operator = Depends(require_operator),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Get the agent's MEMORY.md content."""
    path = _memory_path(agent_id)
    if not path.exists():
        return {"content": "", "exists": False}
    content = path.read_text(encoding="utf-8", errors="replace")
    return {"content": content, "exists": True}


class UpdateMemoryRequest(BaseModel):
    content: str


@router.put("/{agent_id}/memory")
async def update_memory(
    agent_id: str,
    req: UpdateMemoryRequest,
    operator: Operator = Depends(require_operator),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Update the agent's MEMORY.md content."""
    path = _memory_path(agent_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(req.content, encoding="utf-8")
    return {"ok": True, "bytes": len(req.content)}


# --- Skills ---


@router.get("/{agent_id}/skills")
async def list_skills(
    agent_id: str,
    operator: Operator = Depends(require_operator),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """List all skills for an agent."""
    skills_dir = _skills_dir(agent_id)
    skills = []
    if skills_dir.exists():
        for entry in sorted(skills_dir.iterdir()):
            if entry.is_dir():
                # Skill is a directory with SKILL.md
                skill_md = entry / "SKILL.md"
                desc = ""
                if skill_md.exists():
                    content = skill_md.read_text(encoding="utf-8", errors="replace")
                    # Extract first paragraph as description
                    lines = content.split("\n")
                    for line in lines[1:]:  # skip title
                        if line.strip() and not line.startswith("#"):
                            desc = line.strip()
                            break
                skills.append(
                    {
                        "name": entry.name,
                        "type": "directory",
                        "description": desc,
                    }
                )
            elif entry.is_file() and entry.suffix in (".md", ".yaml", ".yml"):
                skills.append(
                    {
                        "name": entry.name,
                        "type": "file",
                        "description": "",
                    }
                )
    return skills


class CreateSkillRequest(BaseModel):
    name: str
    content: str = ""


@router.post("/{agent_id}/skills")
async def create_skill(
    agent_id: str,
    req: CreateSkillRequest,
    operator: Operator = Depends(require_operator),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Create a new skill (as a directory with SKILL.md)."""
    skills_dir = _skills_dir(agent_id)
    skill_path = skills_dir / req.name
    if skill_path.exists():
        raise HTTPException(status_code=409, detail="Skill already exists")
    skill_path.mkdir(parents=True)
    skill_md = skill_path / "SKILL.md"
    content = req.content or f"# {req.name}\n\nDescribe this skill here.\n"
    skill_md.write_text(content, encoding="utf-8")
    return {"name": req.name, "path": str(skill_path)}


@router.delete("/{agent_id}/skills/{skill_name}")
async def delete_skill(
    agent_id: str,
    skill_name: str,
    operator: Operator = Depends(require_operator),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Delete a skill."""
    skills_dir = _skills_dir(agent_id)
    skill_path = skills_dir / skill_name
    if not skill_path.exists():
        raise HTTPException(status_code=404, detail="Skill not found")
    if skill_path.is_dir():
        import shutil

        shutil.rmtree(skill_path)
    else:
        skill_path.unlink()
    return {"ok": True}


# --- Workspace browser ---


@router.get("/{agent_id}/workspace")
async def list_workspace(
    agent_id: str,
    operator: Operator = Depends(require_operator),
    db: AsyncSession = Depends(get_db),
    path: str = "",
) -> dict:
    """List files in the agent's workspace."""
    ws = _workspace_path(agent_id)
    target = ws / path if path else ws

    # Security: ensure target is within workspace
    try:
        target.resolve().relative_to(ws.resolve())
    except ValueError:
        raise HTTPException(status_code=403, detail="Path outside workspace")

    if not target.exists():
        raise HTTPException(status_code=404, detail="Path not found")

    if target.is_file():
        content = target.read_text(encoding="utf-8", errors="replace")
        return {
            "type": "file",
            "path": path,
            "content": content,
            "size": target.stat().st_size,
        }

    entries = []
    for entry in sorted(target.iterdir(), key=lambda e: (not e.is_dir(), e.name)):
        if entry.name.startswith("."):
            continue
        entries.append(
            {
                "name": entry.name,
                "type": "dir" if entry.is_dir() else "file",
                "size": entry.stat().st_size if entry.is_file() else 0,
            }
        )
    return {
        "type": "dir",
        "path": path,
        "entries": entries,
    }
