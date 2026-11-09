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


@pytest.mark.asyncio
async def test_resolve_session_root_pin_wins_over_default_change(db, tmp_path):
    wm = WorkspaceManager()
    pinned = tmp_path / "old"
    pinned.mkdir()
    other = tmp_path / "new"
    other.mkdir()

    class _S:
        workspace_path = str(pinned)
        id = "s-pinned"

    assert await wm.resolve_session_root(db, _S(), "a1", str(other)) == Path(str(pinned))

    class _Legacy:
        workspace_path = None
        id = "s-legacy"

    # No run evidence → a never-worked session pins the current default,
    # same as a brand-new session would.
    assert await wm.resolve_session_root(db, _Legacy(), "a1", str(other)) == Path(
        os.path.realpath(str(other))
    )


@pytest.mark.asyncio
async def test_legacy_session_resolves_run_evidence_not_default(db, tmp_path):
    """An unpinned legacy session anchors to the root its runs actually
    used — a later agent-default change must never re-anchor it."""
    from agentos.models.run import Run
    from agentos.models.session import Session

    old = tmp_path / "old repo"
    old.mkdir()
    new = tmp_path / "new repo"
    new.mkdir()
    db.add(Session(id="s-ev", contact_id="c1", agent_id="a1", status="active"))
    db.add(
        Run(
            id="r-old",
            session_id="s-ev",
            contact_id="c1",
            agent_id="a1",
            trigger="chat",
            status="completed",
            workspace_path=str(old),
        )
    )
    await db.flush()

    wm = WorkspaceManager()
    session = await db.get(Session, "s-ev")
    root = await wm.resolve_session_root(db, session, "a1", str(new))
    assert root == Path(os.path.realpath(str(old)))
    # The API path follows the same evidence — historical attachments and
    # previews resolve where they were actually written.
    api_root = await wm.resolve_api_root(db, "a1", "s-ev")
    assert api_root == Path(os.path.realpath(str(old)))


@pytest.mark.asyncio
async def test_legacy_session_conflicting_evidence_refuses(db, tmp_path):
    """Runs under two different roots = ambiguous provenance — refuse
    honestly for explicit mapping, never silently pick one."""
    from agentos.models.run import Run
    from agentos.models.session import Session
    from agentos.sandbox.workspace import WorkspaceAmbiguousError

    a = tmp_path / "repo a"
    a.mkdir()
    b = tmp_path / "repo b"
    b.mkdir()
    db.add(Session(id="s-amb", contact_id="c1", agent_id="a1", status="active"))
    for i, root in enumerate((a, b)):
        db.add(
            Run(
                id=f"r-{i}",
                session_id="s-amb",
                contact_id="c1",
                agent_id="a1",
                trigger="chat",
                status="completed",
                workspace_path=str(root),
            )
        )
    await db.flush()

    wm = WorkspaceManager()
    session = await db.get(Session, "s-amb")
    with pytest.raises(WorkspaceAmbiguousError):
        await wm.resolve_session_root(db, session, "a1", str(tmp_path))
    with pytest.raises(WorkspaceAmbiguousError):
        await wm.resolve_api_root(db, "a1", "s-amb")


@pytest.mark.asyncio
async def test_legacy_session_unknown_run_roots_refuses(db, tmp_path):
    """A v0.2.0 session's runs all have NULL workspace_path — the column
    didn't exist. Unknown roots are NOT 'never ran': the session refuses
    to silently re-anchor to today's default."""
    from agentos.models.run import Run
    from agentos.models.session import Session
    from agentos.sandbox.workspace import WorkspaceAmbiguousError

    db.add(Session(id="s-old", contact_id="c1", agent_id="a1", status="active"))
    db.add(
        Run(
            id="r-pre",
            session_id="s-old",
            contact_id="c1",
            agent_id="a1",
            trigger="chat",
            status="completed",
            workspace_path=None,  # pre-column run — root unrecorded
        )
    )
    await db.flush()

    wm = WorkspaceManager()
    session = await db.get(Session, "s-old")
    with pytest.raises(WorkspaceAmbiguousError):
        await wm.resolve_session_root(db, session, "a1", str(tmp_path))
    with pytest.raises(WorkspaceAmbiguousError):
        await wm.resolve_api_root(db, "a1", "s-old")


@pytest.mark.asyncio
async def test_legacy_session_known_root_plus_unknown_runs_refuses(db, tmp_path):
    """One populated root plus a NULL-root run still refuses — the unknown
    run could have lived under a different root, so nothing proves the
    session's files are all in the known one."""
    from agentos.models.run import Run
    from agentos.models.session import Session
    from agentos.sandbox.workspace import WorkspaceAmbiguousError

    known = tmp_path / "known repo"
    known.mkdir()
    db.add(Session(id="s-mix", contact_id="c1", agent_id="a1", status="active"))
    for i, ws in enumerate((str(known), None)):
        db.add(
            Run(
                id=f"r-{i}",
                session_id="s-mix",
                contact_id="c1",
                agent_id="a1",
                trigger="chat",
                status="completed",
                workspace_path=ws,
            )
        )
    await db.flush()

    wm = WorkspaceManager()
    session = await db.get(Session, "s-mix")
    with pytest.raises(WorkspaceAmbiguousError):
        await wm.resolve_session_root(db, session, "a1", str(tmp_path))
    with pytest.raises(WorkspaceAmbiguousError):
        await wm.resolve_api_root(db, "a1", "s-mix")


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


@pytest.mark.asyncio
async def test_pipeline_admission_resolves_before_run_exists(db, tmp_path):
    """Pipeline-level regression: the run being admitted must not count
    as its own unknown historical evidence. Resolution happens before the
    Run row exists, so clean evidence resolves and the new run records
    that same root instead of failing on a self-created NULL row."""
    import uuid

    from agentos.harness.loop import Harness
    from agentos.harness.scripted_model import ScriptedModel, ScriptedResponse
    from agentos.models.contact import Contact
    from agentos.models.run import Run
    from agentos.models.session import Session
    from agentos.pipeline import InboundMessage, Pipeline

    agent = await _agent(db)
    old = tmp_path / "old repo"
    old.mkdir()
    # The contact the pipeline resolves for this channel+user — session
    # resume requires contact_id to match.
    contact = Contact(
        id="ct-hist",
        channel="test",
        bot_id=agent.id,
        external_user_id="u",
        display_name="u",
    )
    db.add(contact)
    session = Session(id="s-hist", contact_id="ct-hist", agent_id=agent.id, status="active")
    db.add(session)
    db.add(
        Run(
            id="r-hist",
            session_id="s-hist",
            contact_id="ct-hist",
            agent_id=agent.id,
            trigger="chat",
            status="completed",
            workspace_path=str(old),
        )
    )
    await db.flush()

    model = ScriptedModel([ScriptedResponse(content="done")])
    pipeline = Pipeline(db=db, harness=Harness(model=model))
    run = await pipeline.handle_inbound(
        InboundMessage(
            channel="test",
            bot_id=agent.id,
            external_user_id="u",
            text="resume",
            message_id=str(uuid.uuid4()),
            session_id="s-hist",
        ),
        trigger="user_message",
        is_test=True,
    )
    await db.refresh(session)
    real = os.path.realpath(str(old))
    assert run.status == "completed"
    assert session.workspace_path == real
    assert run.workspace_path == real


@pytest.mark.asyncio
async def test_ambiguous_session_surfaces_through_start_run(db, tmp_path):
    """start_run()'s startup wait resolves on run_started — a refused
    admission must still emit it or the send-message endpoint hangs ~30s
    on 'Run failed to start'. The failed run row carries the real
    workspace-mapping error instead."""
    import asyncio

    from agentos.db import async_session_factory
    from agentos.models.contact import Contact
    from agentos.models.run import Run
    from agentos.models.session import Session
    from agentos.run_manager import start_run

    agent = await _agent(db)
    for name in ("repo a", "repo b"):
        (tmp_path / name).mkdir()
    contact = Contact(
        id="ct-amb",
        channel="dashboard_chat",
        bot_id=agent.id,
        external_user_id="test-operator",
        display_name="op",
    )
    db.add(contact)
    db.add(
        Session(
            id="s-amb2",
            contact_id="ct-amb",
            agent_id=agent.id,
            status="active",
        )
    )
    for i, name in enumerate(("repo a", "repo b")):
        db.add(
            Run(
                id=f"r-amb{i}",
                session_id="s-amb2",
                contact_id="ct-amb",
                agent_id=agent.id,
                trigger="chat",
                status="completed",
                workspace_path=str(tmp_path / name),
            )
        )
    await db.commit()  # start_run opens its own DB session — data must be durable

    result = await asyncio.wait_for(
        start_run(
            agent_id=agent.id,
            text="resume",
            user_id="test-operator",
            is_test=True,
            session_id="s-amb2",
        ),
        timeout=15,
    )
    async with async_session_factory() as check:
        run = await check.get(Run, result["run_id"])
        assert run is not None
        assert run.status == "failed"
        assert "multiple workspaces" in (run.error or "")
