"""Backend-aware terminal cleanup with synthetic handles; no host processes."""

import asyncio
from unittest.mock import AsyncMock, Mock, patch

import pytest

from agentos.models.terminal import TerminalSession
from agentos.sandbox.base import SandboxBackend, SandboxLaunch
from agentos.terminal.registry import TerminalRegistry, _ManagedTerminal

OWNER = {"agent_id": "agent", "session_id": "session", "run_id": "run"}


@pytest.fixture
def managed(tmp_path, monkeypatch):
    registry = TerminalRegistry()
    backend = Mock(spec=SandboxBackend)
    backend.cleanup_launch = AsyncMock(return_value=True)
    proc = Mock(returncode=-9)
    proc.wait = AsyncMock(return_value=-9)
    terminal = _ManagedTerminal(
        id="terminal",
        **OWNER,
        proc=proc,
        pgid=12345,
        stdout_path=tmp_path / "stdout",
        stderr_path=tmp_path / "stderr",
        backend=backend,
        launch=SandboxLaunch(argv=["synthetic-worker"], env={}, resource_id="owned-resource"),
    )
    registry._terminals[terminal.id] = terminal
    monkeypatch.setattr(registry, "_persist", AsyncMock())
    return registry, terminal


async def test_close_uses_captured_backend_resource_not_current_settings(managed):
    registry, terminal = managed
    result = await registry.close(terminal.id, **OWNER)
    assert result["status"] == "closed"
    terminal.backend.cleanup_launch.assert_awaited_once_with(terminal.launch, terminal.proc)
    assert result["error"] is None


async def test_unconfirmed_cleanup_is_orphaned_and_can_be_retried(managed):
    registry, terminal = managed
    terminal.backend.cleanup_launch.side_effect = [False, True]
    first = await registry.close(terminal.id, **OWNER)
    assert first["status"] == "orphaned"
    assert first["error"]
    assert await registry.active_for_run("run") == [terminal.id]
    second = await registry.close(terminal.id, **OWNER)
    assert second["status"] == "closed"
    assert await registry.active_for_run("run") == []


async def test_cleanup_exception_does_not_claim_termination(managed):
    registry, terminal = managed
    terminal.backend.cleanup_launch.side_effect = RuntimeError("synthetic disconnect")
    result = await registry.close(terminal.id, **OWNER)
    assert result["status"] == "orphaned"
    registry._persist.assert_awaited_once_with(terminal)


async def test_wrong_owner_never_reaches_backend_cleanup(managed):
    registry, terminal = managed
    with pytest.raises(ValueError, match="not found"):
        await registry.close(terminal.id, **{**OWNER, "run_id": "other-run"})
    terminal.backend.cleanup_launch.assert_not_awaited()


async def test_run_cancel_and_shutdown_use_backend_cleanup(managed):
    registry, terminal = managed
    assert await registry.close_for_run("other-run") == 0
    assert await registry.close_for_run("run") == 1
    terminal.status = "running"
    await registry.shutdown_all()
    assert terminal.status == "closed"
    assert terminal.backend.cleanup_launch.await_count == 2


async def test_concurrent_close_does_not_clean_twice(managed):
    registry, terminal = managed
    entered = asyncio.Event()
    release = asyncio.Event()

    async def slow_cleanup(*args):
        entered.set()
        await release.wait()
        return True

    terminal.backend.cleanup_launch.side_effect = slow_cleanup
    first = asyncio.create_task(registry.close(terminal.id, **OWNER))
    await asyncio.wait_for(entered.wait(), timeout=2)
    second = asyncio.create_task(registry.close(terminal.id, **OWNER))
    await asyncio.sleep(0)
    release.set()
    results = await asyncio.gather(
        first,
        second,
    )
    assert [result["status"] for result in results] == ["closed", "closed"]
    terminal.backend.cleanup_launch.assert_awaited_once()


async def test_client_exit_is_not_proof_of_external_resource_exit(managed):
    registry, terminal = managed
    terminal.backend.cleanup_launch.return_value = False
    terminal.proc.wait.return_value = 0
    await registry._monitor(terminal)
    assert terminal.status == "orphaned"
    assert terminal.exit_code == 0


async def test_cancelled_cleanup_remains_retryable(managed):
    registry, terminal = managed
    terminal.backend.cleanup_launch.side_effect = asyncio.CancelledError
    with pytest.raises(asyncio.CancelledError):
        await registry.close(terminal.id, **OWNER)
    assert terminal.status == "orphaned"
    registry._persist.assert_awaited_once_with(terminal)


async def test_durable_resource_identity_precedes_activation(tmp_path, monkeypatch):
    registry = TerminalRegistry()
    launch = SandboxLaunch(["synthetic-worker"], {}, "owned-resource")
    backend = Mock(spec=SandboxBackend, kind="docker")
    backend.plan_launch.return_value = launch
    events = []

    async def save(db, row, lock):
        events.append(("persist", row.status, row.resource_id))

    async def activate(plan):
        events.append(("activate", plan.resource_id))

    async def spawn(*args, **kwargs):
        events.append(("spawn", args))
        return Mock(pid=12345, stdout=None, stderr=None)

    backend.activate_launch = AsyncMock(side_effect=activate)
    backend.cleanup_launch = AsyncMock(return_value=True)
    monkeypatch.setattr(registry, "_save_start", save)
    monkeypatch.setattr(registry, "_monitor", AsyncMock())
    monkeypatch.setattr("agentos.terminal.registry._terminals_dir", lambda: tmp_path)
    monkeypatch.setattr("agentos.terminal.registry.get_backend", lambda: backend)
    monkeypatch.setattr("agentos.terminal.registry.os.getpgid", lambda pid: pid)
    monkeypatch.setattr("agentos.terminal.registry.asyncio.create_subprocess_exec", spawn)
    await registry.start(
        Mock(), command="true", workspace_path=str(tmp_path), sandbox_mode="strict", **OWNER
    )
    await asyncio.sleep(0)
    assert events == [
        ("persist", "starting", "owned-resource"),
        ("activate", "owned-resource"),
        ("spawn", ("synthetic-worker",)),
        ("persist", "running", "owned-resource"),
    ]


async def test_failed_durable_admission_never_creates_resource(tmp_path, monkeypatch):
    registry = TerminalRegistry()
    backend = Mock(spec=SandboxBackend)
    backend.plan_launch.return_value = SandboxLaunch(["synthetic"], {}, "owned-resource")
    backend.activate_launch = AsyncMock()
    monkeypatch.setattr(registry, "_save_start", AsyncMock(side_effect=OSError("dummy DB error")))
    monkeypatch.setattr("agentos.terminal.registry._terminals_dir", lambda: tmp_path)
    monkeypatch.setattr("agentos.terminal.registry.get_backend", lambda: backend)
    with pytest.raises(OSError, match="dummy DB error"):
        await registry.start(
            Mock(), command="true", workspace_path=str(tmp_path), sandbox_mode="strict", **OWNER
        )
    backend.activate_launch.assert_not_awaited()


@pytest.mark.parametrize("confirmed", [False, True])
async def test_restart_reconciles_recorded_resource_without_claiming_success(db, confirmed):
    row = TerminalSession(
        id="resource-terminal",
        **OWNER,
        workspace_path="/synthetic",
        backend_kind="docker",
        resource_id="caberos-sandbox-" + "a" * 32,
        status="starting",
    )
    db.add(row)
    await db.commit()
    with patch(
        "agentos.sandbox.docker.DockerBackend.cleanup_launch",
        AsyncMock(return_value=confirmed),
    ) as cleanup:
        assert await TerminalRegistry().reconcile_startup(db) == 1
    assert row.status == ("interrupted" if confirmed else "orphaned")
    cleanup.assert_awaited_once()
