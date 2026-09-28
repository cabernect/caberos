from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from agentos.auth import require_operator
from agentos.config import settings
from agentos.db import get_db
from agentos.main import app
from agentos.models.operator import Operator


@pytest.fixture
async def client(db, monkeypatch, tmp_path: Path):
    async def fake_operator():
        return Operator(id="test-operator", username="test", password_hash="x")

    app.dependency_overrides[require_operator] = fake_operator
    app.dependency_overrides[get_db] = lambda: db
    monkeypatch.setattr(settings, "workspace_root", tmp_path / "workspaces")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as http:
        yield http
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_settings_lists_skill_created_in_agent_workspace(client, db):
    from agentos.models.agent import Agent

    db.add(Agent(id="caber", name="Caber"))
    await db.commit()

    skill_dir = settings.workspace_root / "caber" / "skills" / "release-notes"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: release-notes\ndescription: Create release notes.\n---\n\n# Release notes\n",
        encoding="utf-8",
    )

    response = await client.get("/api/agents/caber/skills")

    assert response.status_code == 200
    listed = response.json()
    assert len(listed) == 1
    assert listed[0]["id"]  # governed row id — indexed on read
    assert listed[0]["status"] == "published"
    assert {k: v for k, v in listed[0].items() if k not in ("id", "status")} == {
        "name": "release-notes",
        "type": "directory",
        "description": "Create release notes.",
    }

    available = await client.get("/api/agents/caber/available-skills")
    assert available.status_code == 200
    agent_skills = [skill for skill in available.json() if skill["source"] == "agent-local"]
    assert agent_skills == [
        {
            "name": "release-notes",
            "description": "Create release notes.",
            "source": "agent-local",
            "shadows": [],
        }
    ]
