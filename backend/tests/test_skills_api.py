"""W6 Skills Studio API — scoped listing, drafts, publish, imports."""

import io
import zipfile

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from agentos.db import get_db
from agentos.main import app
from agentos.models.agent import Agent
from agentos.models.skill import Skill


@pytest.fixture
async def client(db):
    """Test client with auth bypass + test DB session."""
    from agentos.auth import require_operator
    from agentos.models.operator import Operator

    async def fake_operator():
        return Operator(id="test-operator", username="test", password_hash="x")

    app.dependency_overrides[require_operator] = fake_operator
    app.dependency_overrides[get_db] = lambda: db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c

    app.dependency_overrides.clear()


@pytest.fixture
def env(tmp_path, monkeypatch):
    """Patch all skill storage roots into tmp_path."""
    import agentos.config as cfg

    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    monkeypatch.setattr(cfg.settings, "skills_dir", skills_dir)
    monkeypatch.setattr(cfg.settings, "skills_store_root", tmp_path / "skills-store")
    monkeypatch.setattr(cfg.settings, "skills_drafts_root", tmp_path / "skills-drafts")
    monkeypatch.setattr(cfg.settings, "workspace_root", tmp_path / "workspaces")
    return tmp_path


@pytest.fixture
async def agent(db):
    a = Agent(id="agent-1", name="Caber", enabled=True)
    db.add(a)
    await db.flush()
    return a


def _zip(files: dict[str, str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, content in files.items():
            zf.writestr(name, content)
    return buf.getvalue()


SKILL_MD = "---\nname: sample\ndescription: does things\n---\n\nBody text.\n"


class TestListViews:
    async def test_builtin_seeded_and_draft_isolated(self, client, env, db):
        """Built-ins seed at startup; drafts live in their own view."""
        import agentos.skills.reconcile as rc
        from agentos.skills import reconcile

        (env / "skills" / "pdf").mkdir()
        (env / "skills" / "pdf" / "SKILL.md").write_text(
            "---\nname: pdf\ndescription: shipped\n---\n\n"
        )
        monkey = pytest.MonkeyPatch()
        monkey.setattr(rc, "BUILTIN_SKILLS", {"pdf"})
        await reconcile.reconcile_skills(db)
        await db.commit()
        monkey.undo()

        resp = await client.get("/api/skills?view=built-in")
        assert resp.status_code == 200
        names = [s["name"] for s in resp.json()["skills"]]
        assert names == ["pdf"]
        assert resp.json()["skills"][0]["scope"] == "built-in"

        # Create a draft — only appears in the drafts view.
        resp = await client.post("/api/skills/drafts", json={"name": "wip"})
        assert resp.status_code == 200
        draft_id = resp.json()["id"]

        assert (await client.get("/api/skills?view=drafts")).json()["count"] == 1
        all_names = [s["name"] for s in (await client.get("/api/skills")).json()["skills"]]
        assert "wip" not in all_names  # drafts never leak into live views

        # Detail shows draft status + empty draft dir validation.
        detail = (await client.get(f"/api/skills/{draft_id}")).json()
        assert detail["status"] == "draft"


class TestLifecycleApi:
    async def test_draft_publish_flow(self, client, env, db, agent):
        # Builder flow: draft owned by agent with launch session.
        resp = await client.post(
            "/api/skills/drafts",
            json={"name": "new-skill", "agent_id": agent.id, "launch_session": True},
        )
        assert resp.status_code == 200
        skill_id, session_id = resp.json()["id"], resp.json()["session_id"]
        assert session_id  # builder session linked

        # Fill in a valid SKILL.md in the workspace draft dir.
        draft_dir = env / "workspaces" / agent.id / "skill-drafts" / "new-skill"
        assert draft_dir.is_dir()
        (draft_dir / "SKILL.md").write_text(
            "---\nname: new-skill\ndescription: ready\n---\n\nDo it.\n"
        )

        # Publish global.
        resp = await client.post(
            f"/api/skills/{skill_id}/publish",
            json={"scope": "global", "availability": "all", "change_summary": "v1"},
        )
        assert resp.status_code == 200
        assert resp.json()["revision"] == 1
        assert not draft_dir.exists()  # draft dir consumed

        detail = (await client.get(f"/api/skills/{skill_id}")).json()
        assert detail["scope"] == "global"
        assert detail["status"] == "published"
        assert detail["current_revision"] == 1

    async def test_publish_blocked_by_validation(self, client, env):
        resp = await client.post("/api/skills/drafts", json={"name": "bad"})
        skill_id = resp.json()["id"]
        # Skeleton SKILL.md has empty description → validation error.
        resp = await client.post(f"/api/skills/{skill_id}/publish", json={"scope": "global"})
        assert resp.status_code == 422

    async def test_zip_import_lands_as_draft(self, client, env):
        archive = _zip({"SKILL.md": SKILL_MD})
        resp = await client.post(
            "/api/skills/import",
            files={"file": ("skill.zip", archive, "application/zip")},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["imported"][0]["name"] == "sample"
        # Draft-only: not in the live list.
        assert "sample" not in [
            s["name"] for s in (await client.get("/api/skills")).json()["skills"]
        ]
        assert "sample" in [
            s["name"] for s in (await client.get("/api/skills?view=drafts")).json()["skills"]
        ]

    async def test_multi_skill_zip_returns_candidates(self, client, env):
        archive = _zip(
            {
                "repo/a/SKILL.md": "---\nname: a-skill\ndescription: a\n---\n\n",
                "repo/b/SKILL.md": "---\nname: b-skill\ndescription: b\n---\n\n",
            }
        )
        resp = await client.post(
            "/api/skills/import",
            files={"file": ("skills.zip", archive, "application/zip")},
        )
        body = resp.json()
        assert body["imported"] == []
        assert {c["name"] for c in body["candidates"]} == {"a-skill", "b-skill"}

        # Pick one.
        resp = await client.post(
            "/api/skills/import",
            data={"paths": '["repo/a/"]'},
            files={"file": ("skills.zip", archive, "application/zip")},
        )
        body = resp.json()
        assert body["imported"][0]["name"] == "a-skill"

    async def test_delete_draft(self, client, env, db):
        resp = await client.post("/api/skills/drafts", json={"name": "gone"})
        skill_id = resp.json()["id"]
        resp = await client.delete(f"/api/skills/{skill_id}")
        assert resp.status_code == 200
        assert (await db.scalar(select(Skill).where(Skill.id == skill_id))) is None

    async def test_effective_menu_endpoint(self, client, env, db, agent):
        ws = env / "workspaces" / agent.id / "skills" / "mine"
        ws.mkdir(parents=True)
        (ws / "SKILL.md").write_text("---\nname: mine\ndescription: local\n---\n\n")
        resp = await client.get(f"/api/skills/effective?agent_id={agent.id}")
        assert resp.status_code == 200
        assert resp.json()["skills"][0]["name"] == "mine"
        assert resp.json()["skills"][0]["pin"].startswith("live:")
