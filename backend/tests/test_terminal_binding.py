"""W11.2 — exec.terminal binding: spec, save-time validation, backend
resolution, and the admission pin on terminal sessions."""

import json
import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from agentos.auth import require_operator
from agentos.capabilities.bindings import capability_ready, spec_for
from agentos.db import get_db
from agentos.main import app
from agentos.models.operator import Operator
from agentos.models.terminal import TerminalSession
from agentos.models.tool_binding import ToolBinding
from agentos.sandbox.base import (
    LOCAL_BACKEND_OSES,
    UnavailableBackend,
    _local_makers,
    backend_named,
)
from agentos.terminal.registry import TerminalRegistry
from agentos.terminal.resolution import resolve_terminal_backend


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


def _native() -> str | None:
    return next(iter(_local_makers()), None)


def _foreign() -> str:
    return next(n for n in LOCAL_BACKEND_OSES if n not in _local_makers())


def _bind(db, backend: str) -> ToolBinding:
    binding = ToolBinding(
        id=str(uuid.uuid4()),
        key="exec.terminal",
        options=json.dumps({"backend": backend}),
        revision=1,
    )
    db.add(binding)
    return binding


# --- spec ---


def test_exec_terminal_spec():
    spec = spec_for("exec.terminal")
    assert spec and spec.kind == "engine" and spec.implemented
    assert spec.capability_names == ("terminal",)
    field = spec.option_fields[0]
    assert field.name == "backend"
    assert set(field.choices) == {"auto", *LOCAL_BACKEND_OSES}
    assert field.default == "auto"


# --- settings API: local validation only ---


async def test_put_exec_terminal_binding(client):
    pick = _native() or "auto"
    r = await client.put("/api/settings/tools/exec.terminal", json={"options": {"backend": pick}})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["options"]["backend"] == pick
    assert body["binding"]["revision"] == 1


async def test_put_exec_terminal_rejects_foreign_backend(client):
    foreign = _foreign()
    r = await client.put(
        "/api/settings/tools/exec.terminal", json={"options": {"backend": foreign}}
    )
    assert r.status_code == 422
    assert "native to" in r.json()["detail"]


async def test_put_exec_terminal_rejects_bad_option_and_provider(client):
    r = await client.put(
        "/api/settings/tools/exec.terminal", json={"options": {"backend": "bogus"}}
    )
    assert r.status_code == 422
    r = await client.put(
        "/api/settings/tools/exec.terminal",
        json={"provider_id": "p1", "options": {}},
    )
    assert r.status_code == 422


async def test_list_tools_includes_backend_readiness(client):
    r = await client.get("/api/settings/tools")
    assert r.status_code == 200
    tool = {t["key"]: t for t in r.json()["tools"]}["exec.terminal"]
    rows = {b["name"]: b for b in tool["backends"]}
    assert set(rows) == set(LOCAL_BACKEND_OSES)
    native = _native()
    if native:
        assert rows[native]["supported_here"] is True
    foreign = _foreign()
    assert rows[foreign]["supported_here"] is False
    assert "requires" in rows[foreign]["reason"]


# --- backend resolution ---


async def test_resolve_defaults_to_os_native(db):
    backend, revision = await resolve_terminal_backend(db)
    assert revision is None
    assert backend.kind == (_native() or "none")


async def test_resolve_auto_explicit(db):
    _bind(db, "auto")
    await db.flush()
    backend, revision = await resolve_terminal_backend(db)
    assert revision == 1
    assert backend.kind == (_native() or "none")


async def test_resolve_explicit_native(db):
    native = _native()
    if not native or not backend_named(native).is_available():
        pytest.skip("no usable native backend on this platform")
    _bind(db, native)
    await db.flush()
    backend, revision = await resolve_terminal_backend(db)
    assert revision == 1 and backend.kind == native
    assert not isinstance(backend, UnavailableBackend)


async def test_resolve_foreign_refuses_without_fallback(db):
    """A binding written directly (predating the save-time guard or edited
    out-of-band) must still refuse at admission — never fall back to Auto."""
    _bind(db, _foreign())
    await db.flush()
    backend, _ = await resolve_terminal_backend(db)
    assert isinstance(backend, UnavailableBackend)
    assert "native to" in backend.unavailable_reason()


async def test_resolve_invalid_binding_refuses(db):
    binding = _bind(db, "auto")
    binding.options = "{corrupt"
    await db.flush()
    backend, _ = await resolve_terminal_backend(db)
    assert isinstance(backend, UnavailableBackend)
    assert "invalid" in backend.unavailable_reason()


def test_backend_named_unknown_is_honest_refusal():
    backend = backend_named("teleport")
    assert isinstance(backend, UnavailableBackend)
    assert "Unknown" in backend.unavailable_reason()


async def test_capability_ready_for_terminal(db):
    assert await capability_ready(db, "terminal") is True  # defaults usable
    binding = _bind(db, "auto")
    binding.options = "{corrupt"
    await db.flush()
    assert await capability_ready(db, "terminal") is False


# --- admission pin ---


@pytest.fixture
def terminals(tmp_path, monkeypatch):
    from agentos.config import settings

    monkeypatch.setattr(settings, "db_path", tmp_path / "test.db")
    yield TerminalRegistry()


OWNER = {"agent_id": "a1", "session_id": "s1", "run_id": "r1"}


async def test_start_pins_binding_revision_and_resolved_kind(terminals, db, workspace):
    native = _native()
    if not native or not backend_named(native).is_available():
        pytest.skip("no usable native backend on this platform")
    _bind(db, native)
    await db.flush()

    result = await terminals.start(
        db,
        command="echo pinned",
        workspace_path=workspace,
        sandbox_mode="strict",
        **OWNER,
    )
    row = await db.scalar(
        select(TerminalSession).where(TerminalSession.id == result["terminal_id"])
    )
    assert row.backend_kind == native  # resolved kind, never the "auto" token
    assert row.binding_revision == 1
    await terminals.close(result["terminal_id"], **OWNER)


async def test_start_unbound_pins_nothing(terminals, db, workspace):
    native = _native()
    if not native or not backend_named(native).is_available():
        pytest.skip("no usable native backend on this platform")
    result = await terminals.start(
        db,
        command="echo unbound",
        workspace_path=workspace,
        sandbox_mode="strict",
        **OWNER,
    )
    row = await db.scalar(
        select(TerminalSession).where(TerminalSession.id == result["terminal_id"])
    )
    assert row.backend_kind == native
    assert row.binding_revision is None
    await terminals.close(result["terminal_id"], **OWNER)


async def test_start_open_mode_does_not_consult_binding(terminals, db):
    _bind(db, _foreign())  # foreign pick must not block open mode
    await db.flush()
    result = await terminals.start(
        db,
        command="echo open",
        workspace_path="/tmp",
        sandbox_mode="open",
        **OWNER,
    )
    assert result["status"] == "running"
    row = await db.scalar(
        select(TerminalSession).where(TerminalSession.id == result["terminal_id"])
    )
    assert row.backend_kind == "open"
    assert row.binding_revision is None
    await terminals.close(result["terminal_id"], **OWNER)


async def test_start_foreign_binding_refuses(terminals, db):
    _bind(db, _foreign())
    await db.flush()
    with pytest.raises(RuntimeError, match="disabled|requires|native to"):
        await terminals.start(
            db,
            command="echo never",
            workspace_path="/tmp",
            sandbox_mode="strict",
            **OWNER,
        )


async def test_sync_path_honors_binding(db):
    """terminal_run sync path resolves the same binding — a foreign pick
    refuses honestly instead of running sandboxed elsewhere."""
    from agentos.capabilities.tools.terminal import _run_sync

    _bind(db, _foreign())
    await db.flush()
    result = await _run_sync("echo x", "/tmp", "strict", 5, db=db)
    assert result["exit_code"] == -1
    assert "disabled" in result["stderr"]
