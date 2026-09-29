"""Skill loader precedence — agent-local shadows system (W6 foundation)."""

import pytest

from agentos.config import settings
from agentos.skills import loader
from tests.skills_support import write_skill


@pytest.fixture
def skill_dirs(tmp_path, monkeypatch):
    system_dir = tmp_path / "system-skills"
    system_dir.mkdir()
    monkeypatch.setattr(settings, "skills_dir", system_dir)
    monkeypatch.setattr(settings, "workspace_root", tmp_path / "workspaces")
    return system_dir


def test_agent_skill_shadows_system_with_same_name(skill_dirs):
    write_skill(skill_dirs, "docx", "system version")
    write_skill(settings.workspace_root / "caber" / "skills", "docx", "agent version")

    matches = [s for s in loader.list_skills("caber") if s["name"] == "docx"]
    assert matches == [{"name": "docx", "description": "agent version", "source": "agent"}]

    loaded = loader.load_skill("caber", "docx")
    assert loaded is not None
    assert loaded["description"] == "agent version"
    assert loaded["source"] == "agent"


def test_system_skill_survives_when_no_local_override(skill_dirs):
    write_skill(skill_dirs, "pdf", "system pdf")

    assert loader.list_skills("caber") == [
        {"name": "pdf", "description": "system pdf", "source": "system"}
    ]
