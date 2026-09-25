"""Skill loader precedence — agent-local shadows system (W6 foundation)."""

from pathlib import Path

import pytest

from agentos.config import settings
from agentos.skills import loader


@pytest.fixture
def skill_dirs(tmp_path, monkeypatch):
    system_dir = tmp_path / "system-skills"
    system_dir.mkdir()
    monkeypatch.setattr(settings, "skills_dir", system_dir)
    monkeypatch.setattr(settings, "workspace_root", tmp_path / "workspaces")
    return system_dir


def _write_skill(root: Path, name: str, description: str) -> None:
    skill_dir = root / name
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {description}\n---\n\n# {name}\n",
        encoding="utf-8",
    )


def test_agent_skill_shadows_system_with_same_name(skill_dirs):
    _write_skill(skill_dirs, "docx", "system version")
    _write_skill(settings.workspace_root / "caber" / "skills", "docx", "agent version")

    matches = [s for s in loader.list_skills("caber") if s["name"] == "docx"]
    assert matches == [
        {"name": "docx", "description": "agent version", "source": "agent"}
    ]

    loaded = loader.load_skill("caber", "docx")
    assert loaded is not None
    assert loaded["description"] == "agent version"
    assert loaded["source"] == "agent"


def test_system_skill_survives_when_no_local_override(skill_dirs):
    _write_skill(skill_dirs, "pdf", "system pdf")

    assert loader.list_skills("caber") == [
        {"name": "pdf", "description": "system pdf", "source": "system"}
    ]
