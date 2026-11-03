"""W2 — agent workspace selection: authoritative resolver, session pins,
run provenance, selection API, and containment under an external root."""

import os
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from agentos.auth import require_operator
from agentos.db import get_db
from agentos.main import app
from agentos.models.operator import Operator
from agentos.sandbox.workspace import WorkspaceManager


@pytest.fixture
async def client(db):
    async def fake_operator():
        return Operator(id="test-operator", username="test", password_hash="x")

    app.dependency_overrides[require_operator] = fake_operator
    app.dependency_overrides[get_db] = lambda: db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as http:
        yield http
    app.dependency_overrides.clear()


async def _agent(db, agent_id: str = "agent-ws"):
    from agentos.agent_service import create_agent
    from agentos.config_schema import AgentConfig

    config = AgentConfig(id=agent_id, name="WS Agent", model={"provider_id": "p", "name": "m"})
    return await create_agent(db, config)


# --- resolver ---


def test_resolve_agent_root_defaults_to_managed():
    wm = WorkspaceManager()
    root = wm.resolve_agent_root("a1", "")
    assert root == Path(os.path.realpath(str(wm.get_workspace_path("a1"))))
    assert wm.is_managed_root("a1", root)


def test_resolve_agent_root_uses_configured_external(tmp_path):
    wm = WorkspaceManager()
    external = tmp_path / "my repo"
    external.mkdir()
    root = wm.resolve_agent_root("a1", str(external))
    assert root == Path(os.path.realpath(str(external)))
    assert not wm.is_managed_root("a1", root)


def test_validate_external_root_rejects_missing_and_files(tmp_path):
    wm = WorkspaceManager()
    with pytest.raises(ValueError):
        wm.validate_external_root(str(tmp_path / "does-not-exist"))
    f = tmp_path / "file.txt"
    f.write_text("x")
    with pytest.raises(ValueError):
        wm.validate_external_root(str(f))


def test_validate_external_root_canonicalizes(tmp_path):
    wm = WorkspaceManager()
    external = tmp_path / "spaced dir"
    external.mkdir()
    real = wm.validate_external_root(str(external) + "/.")
    assert real == os.path.realpath(str(external))
    assert " " not in real or "spaced dir" in real


def test_resolve_session_root_pin_wins_over_default_change(tmp_path):
    wm = WorkspaceManager()
    pinned = tmp_path / "old"
    pinned.mkdir()
    other = tmp_path / "new"
    other.mkdir()

    class _S:
        workspace_path = str(pinned)

    assert wm.resolve_session_root(_S(), "a1", str(other)) == Path(str(pinned))

    class _Legacy:
        workspace_path = None

    assert wm.resolve_session_root(_Legacy(), "a1", str(other)) == Path(
        os.path.realpath(str(other))
    )


def test_strict_containment_holds_inside_external_root(tmp_path):
    wm = WorkspaceManager()
    root = tmp_path / "repo"
    root.mkdir()
    (root / "ok.txt").write_text("hi")
    inside = wm.validate_path(str(root), "ok.txt")
    assert Path(inside).read_text() == "hi"
    with pytest.raises(ValueError):
        wm.validate_path(str(root), "../escape")


# --- API-level: session pin + selection ---


@pytest.mark.asyncio
async def test_session_pin_and_api_root(db, tmp_path):
    from agentos.models.session import Session

    agent = await _agent(db)
    external = tmp_path / "repo one"
    external.mkdir()

    session = Session(
        id="sess-1",
        contact_id="c1",
        agent_id=agent.id,
        status="active",
        workspace_path=os.path.realpath(str(external)),
    )
    db.add(session)
    await db.flush()

    wm = WorkspaceManager()
    root = await wm.resolve_api_root(db, agent.id, session.id)
    assert root == Path(os.path.realpath(str(external)))

    # No session → agent default (managed, since config.workspace unset)
    default = await wm.resolve_api_root(db, agent.id)
    assert default == Path(os.path.realpath(str(wm.get_workspace_path(agent.id))))

    # Foreign session → LookupError, never a fallback
    with pytest.raises(LookupError):
        await wm.resolve_api_root(db, agent.id, "other-session")


@pytest.mark.asyncio
async def test_update_workspace_selects_external_and_validates(client, db, tmp_path):
    agent = await _agent(db)
    external = tmp_path / "project dir"
    external.mkdir()

    # Selecting an existing directory canonicalizes + persists it.
    resp = await client.put(f"/api/agents/{agent.id}", json={"workspace": str(external)})
    assert resp.status_code == 200

    got = await client.get(f"/api/agents/{agent.id}")
    body = got.json()
    assert body["workspace"] == os.path.realpath(str(external))
    assert body["workspace_path"] == os.path.realpath(str(external))
    assert body["workspace_is_managed"] is False

    # Clearing back to "" selects the managed root again.
    resp = await client.put(f"/api/agents/{agent.id}", json={"workspace": ""})
    assert resp.status_code == 200
    got = await client.get(f"/api/agents/{agent.id}")
    assert got.json()["workspace_is_managed"] is True
    assert got.json()["workspace_path"] == os.path.realpath(
        str(WorkspaceManager().get_workspace_path(agent.id))
    )


@pytest.mark.asyncio
async def test_update_workspace_rejects_missing_path(client, db, tmp_path):
    agent = await _agent(db)
    resp = await client.put(f"/api/agents/{agent.id}", json={"workspace": str(tmp_path / "nope")})
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_update_workspace_blocked_while_run_active(client, db, tmp_path):
    from agentos.models.run import Run
    from agentos.models.session import Session

    agent = await _agent(db)
    session = Session(id="s-run", contact_id="c1", agent_id=agent.id, status="active")
    db.add(session)
    db.add(
        Run(
            id="run-1",
            session_id="s-run",
            contact_id="c1",
            agent_id=agent.id,
            trigger="chat",
            status="running",
        )
    )
    await db.flush()

    external = tmp_path / "busy"
    external.mkdir()
    resp = await client.put(f"/api/agents/{agent.id}", json={"workspace": str(external)})
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_workspace_browser_uses_session_pinned_root(client, db, tmp_path):
    from agentos.models.session import Session

    agent = await _agent(db)
    external = tmp_path / "repo"
    external.mkdir()
    (external / "README.md").write_text("hi")

    session = Session(
        id="sess-pin",
        contact_id="c1",
        agent_id=agent.id,
        status="active",
        workspace_path=os.path.realpath(str(external)),
    )
    db.add(session)
    await db.flush()

    resp = await client.get(
        f"/api/agents/{agent.id}/workspace",
        params={"session_id": "sess-pin"},
    )
    assert resp.status_code == 200
    names = [e["name"] for e in resp.json()["entries"]]
    assert "README.md" in names

    # A foreign session id never leaks another agent's root.
    other = Session(
        id="sess-other",
        contact_id="c1",
        agent_id="different-agent",
        status="active",
        workspace_path=str(tmp_path),
    )
    db.add(other)
    await db.flush()
    resp = await client.get(
        f"/api/agents/{agent.id}/workspace",
        params={"session_id": "sess-other"},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_shared_folder_two_agents(client, db, tmp_path):
    """Two agents attached to the same folder see the same files — shared
    workspace means shared files, never shared identity/memory."""
    a1 = await _agent(db, "agent-a")
    a2 = await _agent(db, "agent-b")
    shared = tmp_path / "shared repo"
    shared.mkdir()
    (shared / "code.py").write_text("print(1)")

    for agent in (a1, a2):
        resp = await client.put(f"/api/agents/{agent.id}", json={"workspace": str(shared)})
        assert resp.status_code == 200
        resp = await client.get(f"/api/agents/{agent.id}/workspace")
        assert "code.py" in [e["name"] for e in resp.json()["entries"]]
