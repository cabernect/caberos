"""Cancellation asks each synchronous backend to clean up, without host execution."""

import asyncio
from unittest.mock import AsyncMock, Mock

import pytest
from tests.process_fakes import FakeProcess

from agentos.capabilities.tools.terminal import terminal_run
from agentos.sandbox.bwrap import BwrapBackend
from agentos.sandbox.docker import DockerBackend
from agentos.sandbox.mxc import MxcBackend
from agentos.sandbox.seatbelt import SeatbeltBackend


@pytest.mark.parametrize(
    "kind,backend_type",
    [("seatbelt", SeatbeltBackend), ("bwrap", BwrapBackend), ("mxc", MxcBackend)],
)
async def test_cancelled_native_command_requests_tree_cleanup(
    tmp_path, monkeypatch, kind, backend_type
):
    policy = tmp_path / "synthetic-policy.json"
    policy.write_text("{}")
    proc = FakeProcess(error=asyncio.CancelledError)
    cleanup = AsyncMock()
    backend = backend_type()
    monkeypatch.setattr(backend, "spawn_argv", Mock(return_value=["synthetic-worker", str(policy)]))
    monkeypatch.setattr(f"agentos.sandbox.{kind}.kill_process_group", cleanup)
    monkeypatch.setattr("asyncio.create_subprocess_exec", AsyncMock(return_value=proc))
    with pytest.raises(asyncio.CancelledError):
        await backend.run_command(str(tmp_path), "true")
    cleanup.assert_awaited_once()
    assert cleanup.call_args.args[0] is proc
    if kind == "mxc":
        assert not policy.exists()


async def test_cancelled_docker_command_requests_actual_container_cleanup(tmp_path, monkeypatch):
    proc = FakeProcess(error=asyncio.CancelledError)
    backend = DockerBackend()
    cleanup = AsyncMock()
    spawn = AsyncMock(return_value=proc)
    monkeypatch.setattr(backend, "_kill_container", cleanup)
    monkeypatch.setattr("asyncio.create_subprocess_exec", spawn)
    with pytest.raises(asyncio.CancelledError):
        await backend.run_command(str(tmp_path), "true")
    cleanup.assert_awaited_once_with(
        spawn.call_args.args[spawn.call_args.args.index("--name") + 1], proc
    )


async def test_cancelled_open_command_requests_tree_cleanup(tmp_path, monkeypatch):
    proc = FakeProcess(error=asyncio.CancelledError)
    cleanup = AsyncMock()
    monkeypatch.setattr("asyncio.create_subprocess_exec", AsyncMock(return_value=proc))
    monkeypatch.setattr("agentos.capabilities.tools.terminal.kill_process_group", cleanup)
    with pytest.raises(asyncio.CancelledError):
        await terminal_run({"command": "true"}, str(tmp_path), sandbox_mode="open")
    cleanup.assert_awaited_once_with(proc)
