"""Installed-tool lookup must not widen the strict sandbox environment."""

import asyncio
import os
import sys
from unittest.mock import AsyncMock, Mock

import pytest

from agentos.capabilities.tools.terminal import _run_sync
from agentos.config import settings
from agentos.dependencies import RuntimeDependencyRegistry
from agentos.sandbox.base import ShellResult
from agentos.sandbox.bwrap import BwrapBackend
from agentos.sandbox.docker import DockerBackend
from agentos.sandbox.mxc import _build_config
from agentos.sandbox.seatbelt import SeatbeltBackend, _build_profile
from agentos.terminal.registry import TerminalRegistry
from agentos.terminal_environment import (
    open_terminal_environment,
    terminal_path,
    workspace_tool_environment,
)
from tests.process_fakes import FakeProcess


@pytest.fixture
def runtime_bin(tmp_path, monkeypatch):
    bindir = tmp_path / "installed tools"
    bindir.mkdir()
    reg = RuntimeDependencyRegistry(data_dir=tmp_path.parent / f"{tmp_path.name}-managed")
    reg._last_paths = {"node": str(bindir / "node"), "npx": str(bindir / "npx")}
    monkeypatch.setattr(reg, "status", AsyncMock(return_value=[]))
    monkeypatch.setattr(settings, "runtime_source", "system")
    monkeypatch.setattr("agentos.terminal_environment.get_dependency_registry", lambda: reg)
    monkeypatch.setattr("agentos.terminal_environment.runtime_directories", lambda: [])
    return bindir


def test_path_preserves_precedence_deduplicates_and_excludes_relative_entries(
    tmp_path, runtime_bin
):
    explicit = str(tmp_path / "operator-configured")
    base = os.pathsep.join([explicit, "", ".", "node_modules/.bin", explicit])
    assert terminal_path(base).split(os.pathsep) == [str(runtime_bin), explicit]


def test_fallback_discovery_skips_missing_directories(tmp_path, runtime_bin, monkeypatch):
    fallback = tmp_path / "fallback"
    fallback.mkdir()
    monkeypatch.setattr(
        "agentos.terminal_environment.runtime_directories",
        lambda: [str(fallback), str(tmp_path / "missing")],
    )
    assert terminal_path("").split(os.pathsep) == [str(runtime_bin), str(fallback)]


def test_open_environment_is_a_copy(runtime_bin, monkeypatch):
    monkeypatch.setenv("PATH", os.defpath)
    monkeypatch.setenv("CABEROS_SYNTHETIC_ENV", "inherited-in-open-mode")
    before = dict(os.environ)
    env = open_terminal_environment()
    assert env["CABEROS_SYNTHETIC_ENV"] == "inherited-in-open-mode"
    assert str(runtime_bin) in env["PATH"].split(os.pathsep)
    assert dict(os.environ) == before


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX shell fixture")
async def test_open_sync_and_background_find_installed_cli(tmp_path, runtime_bin, monkeypatch, db):
    cli = runtime_bin / "caberos-test-cli"
    cli.write_text("#!/bin/sh\nprintf installed-tool")
    cli.chmod(0o755)
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    monkeypatch.setattr(settings, "db_path", tmp_path / "test.db")
    result = await _run_sync("caberos-test-cli", str(tmp_path), "open", 5)
    assert result["stdout"] == "installed-tool"
    registry = TerminalRegistry()
    owner = {"agent_id": "test-agent", "session_id": None, "run_id": "test-run"}
    started = await registry.start(
        db, command="caberos-test-cli", workspace_path=str(tmp_path), sandbox_mode="open", **owner
    )
    try:
        for _ in range(100):
            result = await registry.read(started["terminal_id"], offset=0, **owner)
            if result["status"] != "running":
                break
            await asyncio.sleep(0.02)
        assert result["stdout"] == "installed-tool"
        assert result["exit_code"] == 0
    finally:
        await registry.close(started["terminal_id"], **owner)


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX sandbox environments")
def test_strict_discovery_keeps_secrets_and_mounts_confined(tmp_path, runtime_bin, monkeypatch):
    monkeypatch.setenv("CABEROS_SYNTHETIC_SECRET", "not-for-strict")
    env = SeatbeltBackend().spawn_env(str(tmp_path))
    assert str(runtime_bin) in env["PATH"].split(os.pathsep)
    assert "CABEROS_SYNTHETIC_SECRET" not in env
    assert env["HOME"] == env["TMPDIR"] == str(tmp_path.resolve())
    profile = _build_profile(str(tmp_path), False)
    assert "(allow network*)" not in profile
    assert "(deny file-write*)" in profile
    backend = BwrapBackend()
    argv = backend.spawn_argv(str(tmp_path), "true")
    assert str(runtime_bin) not in backend.spawn_env(str(tmp_path))["PATH"].split(":")
    assert str(runtime_bin) not in argv
    assert "--unshare-all" in argv and "--share-net" not in argv


async def test_strict_sync_requests_network_without_open_fallback(tmp_path, monkeypatch):
    backend = Mock()
    backend.run_command = AsyncMock(return_value=ShellResult("ok", "", 0, 1))
    monkeypatch.setattr("agentos.capabilities.tools.terminal.get_backend", lambda: backend)
    result = await _run_sync("npm install", str(tmp_path), "strict", 30)
    assert result["stdout"] == "ok"
    backend.run_command.assert_awaited_once_with(
        workspace_path=str(tmp_path), command="npm install", timeout=30, allow_network=True
    )


async def test_strict_background_requests_network_before_launch(tmp_path, monkeypatch, db):
    monkeypatch.setattr(settings, "db_path", tmp_path / "test.db")
    backend = SeatbeltBackend()
    planned = Mock(wraps=backend.plan_launch)
    monkeypatch.setattr(backend, "plan_launch", planned)
    resolve = AsyncMock(return_value=(backend, None))
    monkeypatch.setattr("agentos.terminal.registry.resolve_terminal_backend", resolve)
    spawn = AsyncMock(return_value=FakeProcess(b"ok"))
    transport = Mock(spawn=spawn)
    owner = {"agent_id": "test-agent", "session_id": None, "run_id": "test-run"}
    registry = TerminalRegistry()
    result = await registry.start(
        db,
        command="npm install",
        workspace_path=str(tmp_path),
        sandbox_mode="strict",
        transport=transport,
        **owner,
    )
    try:
        planned.assert_called_once_with(str(tmp_path), "npm install", allow_network=True)
        argv = spawn.call_args.args[0]
        profile = argv[argv.index("-p") + 1]
        assert "(allow network*)" in profile
        assert "(deny file-write*)" in profile
        assert spawn.call_args.kwargs["env"]["npm_config_cache"].startswith(str(tmp_path.resolve()))
    finally:
        await registry.close(result["terminal_id"], **owner)


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX sandbox plans")
def test_networked_plans_preserve_filesystem_policy(tmp_path):
    seatbelt = SeatbeltBackend().plan_launch(str(tmp_path), "true", allow_network=True)
    profile = seatbelt.argv[seatbelt.argv.index("-p") + 1]
    assert profile == _build_profile(str(tmp_path), False) + "\n(allow network*)"
    bwrap = BwrapBackend().plan_launch(str(tmp_path), "true", allow_network=True)
    assert "--share-net" in bwrap.argv and "--unshare-all" in bwrap.argv
    assert "--ro-bind-try" in bwrap.argv
    assert "/etc/resolv.conf" in bwrap.argv and "/etc/ssl/certs" in bwrap.argv
    assert "/etc" not in bwrap.argv and "/Users" not in bwrap.argv
    for key, value in workspace_tool_environment("/workspace").items():
        assert ["--setenv", key, value] in [
            bwrap.argv[index : index + 3] for index in range(len(bwrap.argv) - 2)
        ]
    docker = DockerBackend().plan_launch(str(tmp_path), "true", allow_network=True)
    assert "--network" not in docker.setup_argv
    assert "--read-only" in docker.setup_argv
    assert "npm_config_cache=/workspace/.cache/npm" in docker.setup_argv


def test_windows_network_and_workspace_cache_contract():
    config = _build_config("C:\\workspace", "npm install", allow_network=True)
    assert config["network"] == {"defaultPolicy": "allow"}
    env = dict(entry.split("=", 1) for entry in config["process"]["env"])
    assert env["npm_config_cache"] == "C:\\workspace\\.cache\\npm"
    assert env["npm_config_prefix"] == "C:\\workspace\\.local"
    assert env["UV_CACHE_DIR"] == "C:\\workspace\\.cache\\uv"
