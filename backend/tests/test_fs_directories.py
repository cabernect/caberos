"""Filesystem browse endpoint — home-directory jail.

/api/fs/directories exists so the operator can pick a workspace folder. The
browse scope is confined to the operator's home: paths, ``..`` escapes, and
symlinks resolving outside HOME are refused. Tests observe HTTP responses.
"""

import os
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from agentos.db import get_db
from agentos.main import app


@pytest.fixture
async def client(db):
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
def home(tmp_path, monkeypatch):
    """Jail root: HOME points at an isolated temp dir."""
    monkeypatch.setenv("HOME", str(tmp_path))
    return Path(os.path.realpath(tmp_path))


async def test_browse_default_lists_home(client, home):
    (home / "projects").mkdir()
    resp = await client.get("/api/fs/directories")
    assert resp.status_code == 200
    body = resp.json()
    assert body["path"] == str(home)
    assert any(d["name"] == "projects" for d in body["directories"])


async def test_browse_inside_home_ok(client, home):
    (home / "projects" / "repo").mkdir(parents=True)
    resp = await client.get("/api/fs/directories", params={"path": str(home / "projects")})
    assert resp.status_code == 200
    assert resp.json()["path"] == str(home / "projects")


async def test_browse_outside_home_refused(client, home, tmp_path_factory):
    outside = tmp_path_factory.mktemp("outside")
    resp = await client.get("/api/fs/directories", params={"path": str(outside)})
    assert resp.status_code == 403
    assert "outside allowed root" in resp.json()["detail"]


async def test_browse_dotdot_escape_refused(client, home):
    (home / "sub").mkdir()
    resp = await client.get(
        "/api/fs/directories",
        params={"path": str(home / "sub" / ".." / "..")},
    )
    assert resp.status_code == 403


async def test_browse_symlink_escape_refused(client, home, tmp_path_factory):
    outside = tmp_path_factory.mktemp("outside")
    (home / "link").symlink_to(outside)
    resp = await client.get("/api/fs/directories", params={"path": str(home / "link")})
    assert resp.status_code == 403


async def test_browse_missing_folder_404(client, home):
    resp = await client.get("/api/fs/directories", params={"path": str(home / "nope")})
    assert resp.status_code == 404


async def test_browse_file_not_dir_400(client, home):
    (home / "file.txt").write_text("x")
    resp = await client.get("/api/fs/directories", params={"path": str(home / "file.txt")})
    assert resp.status_code == 400
