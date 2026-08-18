"""Tests for the skills API — list, import zip, delete, promote."""

import io
import zipfile

import pytest
from httpx import ASGITransport, AsyncClient

from agentos.db import get_db
from agentos.main import app


@pytest.fixture
async def client(db):
    """Test client with auth bypass."""
    from agentos.auth import require_operator
    from agentos.models.operator import Operator

    # Override the auth dependency to return a fake operator
    async def fake_operator():
        return Operator(id="test-operator", username="test", password_hash="x")

    app.dependency_overrides[require_operator] = fake_operator
    app.dependency_overrides[get_db] = lambda: db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c

    app.dependency_overrides.clear()


@pytest.fixture
def skills_dir(tmp_path, monkeypatch):
    """Create a temporary skills directory and chdir to it."""
    sd = tmp_path / "skills"
    sd.mkdir()
    monkeypatch.chdir(tmp_path)
    # Patch the SKILLS_DIR in the API module + settings
    import agentos.api.skills as api_skills
    import agentos.config

    monkeypatch.setattr(api_skills, "SKILLS_DIR", sd)
    monkeypatch.setattr(agentos.config.settings, "skills_dir", sd)
    return sd


class TestSkillsAPI:
    async def test_list_empty(self, client, skills_dir):
        """GET /api/skills returns empty list when no skills installed."""
        resp = await client.get("/api/skills")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 0
        assert data["skills"] == []

    async def test_list_with_skills(self, client, skills_dir):
        """GET /api/skills returns installed skills."""
        # Create a skill
        skill_dir = skills_dir / "pdf"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            "---\nname: pdf\ndescription: PDF processing skill\n---\n\nBody."
        )

        resp = await client.get("/api/skills")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 1
        assert data["skills"][0]["name"] == "pdf"
        assert data["skills"][0]["description"] == "PDF processing skill"

    async def test_import_zip(self, client, skills_dir):
        """POST /api/skills/import installs a skill from a zip file."""
        # Create a zip with SKILL.md at root
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr(
                "SKILL.md", "---\nname: my-skill\ndescription: Test skill\n---\n\nInstructions."
            )
            zf.writestr("reference.md", "# Reference\n\nDetails.")
        buf.seek(0)

        resp = await client.post(
            "/api/skills/import",
            files={"file": ("my-skill.zip", buf, "application/zip")},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["imported"] is True
        assert data["name"] == "my-skill"
        assert (skills_dir / "my-skill" / "SKILL.md").exists()
        assert (skills_dir / "my-skill" / "reference.md").exists()

    async def test_import_zip_with_top_dir(self, client, skills_dir):
        """POST /api/skills/import handles zips with a top-level directory."""
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("my-skill/SKILL.md", "---\nname: my-skill\ndescription: Test\n---\n\nBody.")
        buf.seek(0)

        resp = await client.post(
            "/api/skills/import",
            files={"file": ("my-skill.zip", buf, "application/zip")},
        )
        assert resp.status_code == 200
        assert (skills_dir / "my-skill" / "SKILL.md").exists()

    async def test_import_zip_no_skill_md(self, client, skills_dir):
        """POST /api/skills/import rejects zips without SKILL.md."""
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("random.txt", "no skill here")
        buf.seek(0)

        resp = await client.post(
            "/api/skills/import",
            files={"file": ("random.zip", buf, "application/zip")},
        )
        assert resp.status_code == 400
        assert "SKILL.md" in resp.json()["detail"]

    async def test_import_zip_invalid_name(self, client, skills_dir):
        """POST /api/skills/import rejects skills with invalid names."""
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("SKILL.md", "---\nname: Bad Name\ndescription: Test\n---\n\nBody.")
        buf.seek(0)

        resp = await client.post(
            "/api/skills/import",
            files={"file": ("bad.zip", buf, "application/zip")},
        )
        assert resp.status_code == 400
        assert "Invalid skill name" in resp.json()["detail"]

    async def test_import_zip_duplicate(self, client, skills_dir):
        """POST /api/skills/import rejects duplicates."""
        # Create existing skill
        (skills_dir / "existing").mkdir()
        (skills_dir / "existing" / "SKILL.md").write_text("---\nname: existing\n---\n\nBody.")

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("SKILL.md", "---\nname: existing\ndescription: Test\n---\n\nBody.")
        buf.seek(0)

        resp = await client.post(
            "/api/skills/import",
            files={"file": ("existing.zip", buf, "application/zip")},
        )
        assert resp.status_code == 409

    async def test_delete_skill(self, client, skills_dir):
        """DELETE /api/skills/{name} removes a skill."""
        skill_dir = skills_dir / "pdf"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text("---\nname: pdf\n---\n\nBody.")

        resp = await client.delete("/api/skills/pdf")
        assert resp.status_code == 200
        assert resp.json()["deleted"] is True
        assert not skill_dir.exists()

    async def test_delete_nonexistent(self, client, skills_dir):
        """DELETE /api/skills/{name} returns 404 for missing skills."""
        resp = await client.delete("/api/skills/nonexistent")
        assert resp.status_code == 404

    async def test_delete_path_traversal_blocked(self, client, skills_dir):
        """DELETE /api/skills/../../etc rejects path traversal."""
        resp = await client.delete("/api/skills/..%2F..%2Fetc")
        assert resp.status_code in (400, 404)
