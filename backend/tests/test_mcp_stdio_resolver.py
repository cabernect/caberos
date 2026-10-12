"""Tests for MCP stdio command resolution — runtime PATH resolution."""

import os
from unittest.mock import patch

import pytest

from agentos.mcp.client import _resolve_stdio_command


def test_resolve_absolute_path():
    """Absolute paths are used as-is."""
    resolved, env = _resolve_stdio_command("/usr/bin/echo", {})
    assert resolved == "/usr/bin/echo"
    assert "PATH" not in env  # env unchanged


def test_resolve_command_on_path():
    """Commands on the current PATH resolve to full paths."""
    # 'ls' is on every Unix PATH
    resolved, env = _resolve_stdio_command("ls", {})
    assert os.path.isabs(resolved)
    assert "PATH" in env
    # Resolved dir should be prepended to PATH
    resolved_dir = os.path.dirname(resolved)
    assert env["PATH"].startswith(resolved_dir)


def test_resolve_command_not_found():
    """Missing commands raise an actionable RuntimeError."""
    with pytest.raises(RuntimeError, match="not found"):
        _resolve_stdio_command("nonexistent_command_xyz_123", {})


def test_resolve_command_with_custom_runtime_path():
    """CABEROS_MCP_RUNTIME_PATH is searched as a fallback."""
    with patch.dict(os.environ, {"CABEROS_MCP_RUNTIME_PATH": "/custom/runtime"}):
        with pytest.raises(RuntimeError, match="/custom/runtime"):
            _resolve_stdio_command("nonexistent_command_xyz_123", {})


def test_resolve_command_with_env_path():
    """env["PATH"] is used as the subprocess's PATH."""
    # Create a fake PATH with a fake command
    fake_bin = "/tmp/fake_bin_xyz"
    os.makedirs(fake_bin, exist_ok=True)
    fake_cmd = os.path.join(fake_bin, "fake_cmd")
    with open(fake_cmd, "w") as f:
        f.write("#!/bin/sh\nexit 0\n")
    os.chmod(fake_cmd, 0o755)

    try:
        env = {"PATH": fake_bin}
        resolved, updated_env = _resolve_stdio_command("fake_cmd", env)
        assert resolved == fake_cmd
        assert updated_env["PATH"].startswith(fake_bin)
    finally:
        os.unlink(fake_cmd)
        os.rmdir(fake_bin)


def test_resolve_command_fallback_dirs():
    """Fallback directories are searched when PATH doesn't contain the command."""
    # Temporarily add a fallback dir with a fake command
    fake_bin = "/tmp/fake_fallback_xyz"
    os.makedirs(fake_bin, exist_ok=True)
    fake_cmd = os.path.join(fake_bin, "fallback_cmd")
    with open(fake_cmd, "w") as f:
        f.write("#!/bin/sh\nexit 0\n")
    os.chmod(fake_cmd, 0o755)

    try:
        # Patch _RUNTIME_DIRS to include our fake dir
        with patch(
            "agentos.mcp.client._RUNTIME_DIRS",
            ["/opt/homebrew/bin", "/usr/local/bin", fake_bin],
        ):
            resolved, env = _resolve_stdio_command("fallback_cmd", {})
            assert resolved == fake_cmd
            assert env["PATH"].startswith(fake_bin)
    finally:
        os.unlink(fake_cmd)
        os.rmdir(fake_bin)


# -- readiness-registry wiring (W11) -------------------------------------------


def _verified_registry(tmp_path, paths: dict):
    """Registry with _last_paths pre-seeded — no probes."""

    from agentos.dependencies import RuntimeDependencyRegistry

    async def runner(argv, env):
        return 0, b"2.53.0\n", b""

    reg = RuntimeDependencyRegistry(
        data_dir=tmp_path / "rt",
        runner=runner,
        finder=lambda c: None,
        platform_key="test-plat",
    )
    reg._last_paths = dict(paths)
    return reg


def test_registry_verified_path_wins_over_legacy(tmp_path, monkeypatch):
    """A health-verified managed path beats the legacy fallback dirs."""
    import agentos.mcp.client as client

    managed = tmp_path / "rt" / "git" / "v" / "bin" / "git"
    managed.parent.mkdir(parents=True)
    managed.write_text("#!")
    managed.chmod(0o755)
    reg = _verified_registry(tmp_path, {"git": str(managed)})
    monkeypatch.setattr(client, "_registry_or_none", lambda: reg)

    resolved, env = _resolve_stdio_command("git", {"PATH": "/nonexistent"})
    assert resolved == str(managed)
    assert env["PATH"].startswith(str(managed.parent))


def test_caller_explicit_path_beats_registry(tmp_path, monkeypatch):
    """An operator-provided PATH entry still takes precedence."""
    import agentos.mcp.client as client

    managed = tmp_path / "rt" / "git" / "v" / "bin" / "git"
    managed.parent.mkdir(parents=True)
    managed.write_text("#!")
    managed.chmod(0o755)
    explicit = tmp_path / "explicit"
    explicit.mkdir()
    own = explicit / "git"
    own.write_text("#!")
    own.chmod(0o755)
    reg = _verified_registry(tmp_path, {"git": str(managed)})
    monkeypatch.setattr(client, "_registry_or_none", lambda: reg)

    resolved, env = _resolve_stdio_command("git", {"PATH": str(explicit)})
    assert resolved == str(own)


def test_missing_runtime_actionable_error(monkeypatch):
    import agentos.mcp.client as client

    monkeypatch.setattr(client, "_registry_or_none", lambda: None)
    monkeypatch.delenv("CABEROS_MCP_RUNTIME_PATH", raising=False)

    monkeypatch.setenv("PATH", "/nonexistent-only")
    with pytest.raises(RuntimeError) as e:
        _resolve_stdio_command("definitely-missing-cmd-xyz", {"PATH": "/nonexistent-only"})
    assert "Settings" in str(e.value)


def test_child_environment_includes_all_verified_dirs(tmp_path):
    reg = _verified_registry(
        tmp_path,
        {
            "git": "/r/git/bin/git",
            "uv": "/r/uv/uv",
            "uvx": "/r/uv/uvx",
            "node": "/r/node/bin/node",
            "npm": "/r/node/bin/npm",
            "npx": "/r/node/bin/npx",
        },
    )
    env = reg.child_environment({"PATH": "/base", "SECRET_KEY": "tok"})
    parts = env["PATH"].split(":")
    assert parts[:3] == ["/r/node/bin", "/r/uv", "/r/git/bin"]
    assert parts[-1] == "/base"
    assert env["SECRET_KEY"] == "tok"
    assert "/r/git/bin" not in os.environ.get("PATH", "")


async def test_stdio_client_receives_verified_env(tmp_path, monkeypatch):
    """Simulated connect: stdio_client gets the registry-verified command
    and child PATH; caller env secrets preserved only for the child."""
    import agentos.mcp.client as client

    captured = {}

    class FakeStdio:
        def __init__(self, params):
            captured["command"] = params.command
            captured["args"] = params.args
            captured["env"] = params.env

        async def __aenter__(self):
            return (object(), object())

        async def __aexit__(self, *a):
            return False

    managed_git = tmp_path / "rt" / "git" / "v" / "bin" / "git"
    managed_git.parent.mkdir(parents=True)
    managed_git.write_text("#!")
    managed_git.chmod(0o755)
    reg = _verified_registry(tmp_path, {"git": str(managed_git)})
    monkeypatch.setattr(client, "_registry_or_none", lambda: reg)

    import sys

    class FakeMcp:
        ClientSession = object

    class FakeStdioMod:
        @staticmethod
        def StdioServerParameters(**kw):
            return type("P", (), kw)()

        @staticmethod
        def stdio_client(params):
            return FakeStdio(params)

    monkeypatch.setitem(sys.modules, "mcp", FakeMcp)
    monkeypatch.setitem(sys.modules, "mcp.client", object())
    monkeypatch.setitem(sys.modules, "mcp.client.stdio", FakeStdioMod)

    c = client.McpClient(
        transport="stdio",
        command="git",
        args=["mcp-server"],
        env={"GIT_TOKEN": "s3cr3t", "PATH": "/nonexistent"},
    )
    # Drive the resolver path directly — the async connect requires the
    # real anyio context; the resolver seam is the contract under test.
    resolved, env = client._resolve_stdio_command(c.command, c.env)
    assert resolved == str(managed_git)
    assert env["GIT_TOKEN"] == "s3cr3t"
    assert env["PATH"].split(":")[0] == str(managed_git.parent)
    assert "/nonexistent" in env["PATH"]


def test_remote_transport_never_touches_registry(monkeypatch):
    import agentos.mcp.client as client

    called = []
    monkeypatch.setattr(client, "_registry_or_none", lambda: called.append(1) or None)
    client.McpClient(transport="http", url="https://example.com/mcp")
    assert called == []


# -- real async connect seam (W11) ---------------------------------------------


class _FakeSession:
    """Minimal ClientSession stand-in for the anyio-owned context."""

    def __init__(self, read, write, **kw):
        self.read = read
        self.write = write

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def initialize(self):
        return None


def _install_fake_mcp(monkeypatch, capture: dict):
    import sys
    import types

    stdio_mod = types.ModuleType("mcp.client.stdio")

    class StdioServerParameters:
        def __init__(self, command, args, env):
            self.command = command
            self.args = args
            self.env = env

    class _StdioCtx:
        def __init__(self, params):
            capture["params"] = params

        async def __aenter__(self):
            return (object(), object())

        async def __aexit__(self, *a):
            return False

    stdio_mod.StdioServerParameters = StdioServerParameters
    stdio_mod.stdio_client = lambda params: _StdioCtx(params)

    http_mod = types.ModuleType("mcp.client.streamable_http")

    class _HttpCtx:
        def __init__(self, *a, **k):
            capture["http_called"] = True

        async def __aenter__(self):
            return (object(), object(), object())

        async def __aexit__(self, *a):
            return False

    http_mod.streamable_http_client = lambda *a, **k: _HttpCtx()

    mcp_mod = types.ModuleType("mcp")
    mcp_mod.ClientSession = _FakeSession
    client_pkg = types.ModuleType("mcp.client")

    monkeypatch.setitem(sys.modules, "mcp", mcp_mod)
    monkeypatch.setitem(sys.modules, "mcp.client", client_pkg)
    monkeypatch.setitem(sys.modules, "mcp.client.stdio", stdio_mod)
    monkeypatch.setitem(sys.modules, "mcp.client.streamable_http", http_mod)


async def test_connect_uses_verified_managed_path(tmp_path, monkeypatch):
    """REAL connect() — the managed verified path reaches StdioServerParameters."""
    import agentos.mcp.client as client

    managed_git = tmp_path / "rt" / "git" / "v" / "bin" / "git"
    managed_git.parent.mkdir(parents=True)
    managed_git.write_text("#!")
    managed_git.chmod(0o755)
    reg = _verified_registry(tmp_path, {"git": str(managed_git)})

    async def _status(force=False):
        return []

    reg.status = _status
    monkeypatch.setattr(client, "_registry_or_none", lambda: reg)
    capture: dict = {}
    _install_fake_mcp(monkeypatch, capture)

    c = client.McpClient(
        transport="stdio",
        command="git",
        args=["mcp-server"],
        env={"GIT_TOKEN": "s3cr3t"},
    )
    await c.connect()
    params = capture["params"]
    assert params.command == str(managed_git)
    assert params.args == ["mcp-server"]
    # Child env carries the caller's credential and the verified dir.
    assert params.env["GIT_TOKEN"] == "s3cr3t"
    assert params.env["PATH"].split(":")[0] == str(managed_git.parent)
    # The process env was NOT mutated.
    import os as _os

    assert str(managed_git.parent) not in _os.environ.get("PATH", "")
    await c.disconnect()


async def test_connect_remote_never_loads_registry(monkeypatch):
    import agentos.mcp.client as client

    called = []
    monkeypatch.setattr(client, "_registry_or_none", lambda: called.append(1) or None)
    capture: dict = {}
    _install_fake_mcp(monkeypatch, capture)
    c = client.McpClient(transport="http", url="https://example.com/mcp")
    await c.connect()
    assert called == []
    await c.disconnect()


async def test_connect_stale_cached_path_fails_actionably(tmp_path, monkeypatch):
    """Operator removed the managed runtime AFTER the cached health check.
    A stale pointer must not pass the ready-guard — and the resolver must
    never fall back to an incompatible legacy binary."""
    import agentos.mcp.client as client

    managed_git = tmp_path / "rt" / "git" / "v" / "bin" / "git"
    managed_git.parent.mkdir(parents=True)
    managed_git.write_text("#!")
    managed_git.chmod(0o755)
    reg = _verified_registry(tmp_path, {"git": str(managed_git)})
    monkeypatch.setattr(client, "_registry_or_none", lambda: reg)

    async def _status(force=False):
        # Cache is still warm (< TTL) — status does NOT recompute, the
        # stale _last_paths survives unless the connect path forces it.
        return []

    monkeypatch.setattr(reg, "status", _status)
    capture: dict = {}
    _install_fake_mcp(monkeypatch, capture)
    # The managed file is gone — the cached pointer is stale.
    managed_git.unlink()

    c = client.McpClient(
        transport="stdio",
        command="git",
        args=["mcp-server"],
        env={},
    )
    with pytest.raises(RuntimeError, match="no verified"):
        await c.connect()
    # The SDK was never reached — no legacy fallback, no subprocess.
    assert "params" not in capture


async def test_connect_healthy_alternative_after_forced_refresh(tmp_path, monkeypatch):
    """A removed managed path triggers ONE forced re-check; a healthy
    replacement found there wins — child env updated to the NEW dir."""
    import agentos.mcp.client as client

    stale = tmp_path / "rt" / "git" / "old" / "bin" / "git"
    stale.parent.mkdir(parents=True)
    stale.write_text("#!")
    stale.chmod(0o755)
    fresh = tmp_path / "rt" / "git" / "new" / "bin" / "git"
    fresh.parent.mkdir(parents=True)
    fresh.write_text("#!")
    fresh.chmod(0o755)
    reg = _verified_registry(tmp_path, {"git": str(stale)})
    monkeypatch.setattr(client, "_registry_or_none", lambda: reg)

    async def _status(force=False):
        # Simulated forced probe: the stale path is gone, the fresh one is
        # verified — _last_paths rewritten as a real probe pass would.
        if force:
            reg._last_paths = {"git": str(fresh)}
        return []

    monkeypatch.setattr(reg, "status", _status)
    capture: dict = {}
    _install_fake_mcp(monkeypatch, capture)
    stale.unlink()  # operator removed the managed install

    c = client.McpClient(
        transport="stdio",
        command="git",
        args=["mcp-server"],
        env={},
    )
    await c.connect()
    params = capture["params"]
    assert params.command == str(fresh)
    assert params.env["PATH"].split(":")[0] == str(fresh.parent)
    await c.disconnect()


async def test_connect_companion_stale_removed_git_dropped_from_env(tmp_path, monkeypatch):
    """uvx launches while the cached Git companion was removed — ONE
    forced re-check drops the deleted dir from the child's PATH."""
    import agentos.mcp.client as client

    uvx = tmp_path / "rt" / "uv" / "v" / "bin" / "uvx"
    uvx.parent.mkdir(parents=True)
    uvx.write_text("#!")
    uvx.chmod(0o755)
    git = tmp_path / "rt" / "git" / "v" / "bin" / "git"
    git.parent.mkdir(parents=True)
    git.write_text("#!")
    git.chmod(0o755)
    reg = _verified_registry(tmp_path, {"uvx": str(uvx), "git": str(git)})
    monkeypatch.setattr(client, "_registry_or_none", lambda: reg)

    force_calls = []

    async def _status(force=False):
        # Warm cache never recomputes; the forced pass rewrites the
        # verified set WITHOUT the deleted git.
        if force:
            force_calls.append(1)
            reg._last_paths = {"uvx": str(uvx)}
        return []

    monkeypatch.setattr(reg, "status", _status)
    capture: dict = {}
    _install_fake_mcp(monkeypatch, capture)
    git.unlink()  # operator removed the managed git

    c = client.McpClient(
        transport="stdio",
        command="uvx",
        args=["mcp-server"],
        env={},
    )
    await c.connect()
    params = capture["params"]
    assert params.command == str(uvx)
    assert str(git.parent) not in params.env["PATH"]
    assert str(uvx.parent) in params.env["PATH"]
    assert len(force_calls) == 1  # exactly one forced re-check
    await c.disconnect()
