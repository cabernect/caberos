"""W6 Skills Studio API — scoped listing, drafts, publish, imports."""

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from agentos.db import get_db
from agentos.main import app
from agentos.models.skill import Skill
from tests.skills_support import zip_bytes


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


SKILL_MD = "---\nname: sample\ndescription: does things\n---\n\nBody text.\n"


class TestListViews:
    async def test_builtin_seeded_and_draft_isolated(self, client, skills_env, db):
        """Built-ins seed at startup; drafts live in their own view."""
        import agentos.skills.reconcile as rc
        from agentos.skills import reconcile

        (skills_env / "skills" / "pdf").mkdir()
        (skills_env / "skills" / "pdf" / "SKILL.md").write_text(
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
    async def test_draft_publish_flow(self, client, skills_env, db, skills_agent):
        # Builder flow: draft owned by agent with launch session.
        resp = await client.post(
            "/api/skills/drafts",
            json={"name": "new-skill", "agent_id": skills_agent.id, "launch_session": True},
        )
        assert resp.status_code == 200
        skill_id, session_id = resp.json()["id"], resp.json()["session_id"]
        assert session_id  # builder session linked

        # Fill in a valid SKILL.md in the workspace draft dir.
        draft_dir = skills_env / "workspaces" / skills_agent.id / "skill-drafts" / "new-skill"
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

    async def test_publish_blocked_by_validation(self, client, skills_env):
        resp = await client.post("/api/skills/drafts", json={"name": "bad"})
        skill_id = resp.json()["id"]
        # Skeleton SKILL.md has empty description → validation error.
        resp = await client.post(f"/api/skills/{skill_id}/publish", json={"scope": "global"})
        assert resp.status_code == 422

    async def test_zip_import_lands_as_draft(self, client, skills_env):
        archive = zip_bytes({"SKILL.md": SKILL_MD})
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
        assert (skills_env / "skills-drafts" / "sample" / "SKILL.md").is_file()

    async def test_multi_skill_zip_returns_candidates(self, client, skills_env):
        archive = zip_bytes(
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

    async def test_delete_draft(self, client, skills_env, db):
        resp = await client.post("/api/skills/drafts", json={"name": "gone"})
        skill_id = resp.json()["id"]
        resp = await client.delete(f"/api/skills/{skill_id}")
        assert resp.status_code == 200
        assert (await db.scalar(select(Skill).where(Skill.id == skill_id))) is None

    async def test_effective_menu_endpoint(self, client, skills_env, db, skills_agent):
        ws = skills_env / "workspaces" / skills_agent.id / "skills" / "mine"
        ws.mkdir(parents=True)
        (ws / "SKILL.md").write_text("---\nname: mine\ndescription: local\n---\n\n")
        resp = await client.get(f"/api/skills/effective?agent_id={skills_agent.id}")
        assert resp.status_code == 200
        assert resp.json()["skills"][0]["name"] == "mine"
        assert resp.json()["skills"][0]["pin"].startswith("live:")
