"""Managed selection and narrowly scoped sandbox grants, without downloads."""

import json
import os

import pytest

from agentos.config import settings
from agentos.dependencies import RuntimeDependencyRegistry
from agentos.mcp.client import _resolve_stdio_command
from agentos.sandbox.bwrap import BwrapBackend
from agentos.sandbox.mxc import _build_config
from agentos.sandbox.seatbelt import _build_profile
from agentos.terminal_environment import terminal_path


@pytest.fixture
def managed(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "runtime_source", "managed")
    monkeypatch.setattr(settings, "runtime_binary_overrides", {})
    store = tmp_path / "private-app-data" / "managed-runtimes"
    runtime = store / "nodejs" / "versions" / "24.21.0"
    (runtime / "bin").mkdir(parents=True)
    for name in ("node", "npm", "npx"):
        path = runtime / "bin" / name
        path.write_text("#!/bin/sh\nexit 0\n")
        path.chmod(0o755)
    pointer = {
        "version": "24.21.0",
        "platform": "darwin-arm64",
        "directory": "versions/24.21.0",
        "executables": {name: f"bin/{name}" for name in ("node", "npm", "npx")},
    }
    (store / "nodejs" / "active.json").write_text(json.dumps(pointer))

    async def runner(argv, env):
        return 0, b"v24.21.0\n" if argv[0].endswith("/node") else b"11.0.0\n", b""

    def no_system_probe(command):
        raise AssertionError("Managed mode must not fall back to system discovery")

    registry = RuntimeDependencyRegistry(
        data_dir=store, runner=runner, finder=no_system_probe, platform_key="darwin-arm64"
    )
    monkeypatch.setattr("agentos.dependencies._REGISTRY", registry)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    return registry, runtime.resolve(), workspace, pointer


async def test_managed_selection_drives_mcp_and_terminal(managed, monkeypatch):
    registry, runtime, workspace, _ = managed
    rows = await registry.status()
    row = next(row for row in rows if row["id"] == "nodejs")
    assert row["source"] == "managed" and row["status"] == "ready"
    assert registry.managed_runtime_roots(str(workspace)) == (str(runtime),)
    monkeypatch.setattr("agentos.mcp.client._registry_or_none", lambda: registry)
    binary, env = _resolve_stdio_command("npm", {})
    assert binary == str(runtime / "bin" / "npm")
    assert env["PATH"].split(os.pathsep)[0] == str(runtime / "bin")
    assert terminal_path("/usr/bin:/bin").split(os.pathsep)[0] == str(runtime / "bin")


async def test_sandbox_grants_only_the_selected_version(managed):
    registry, runtime, workspace, _ = managed
    await registry.status()
    profile = _build_profile(str(workspace), True)
    escaped = str(runtime).replace("\\", "\\\\").replace('"', '\\"')
    assert f'(allow file-read* (subpath "{escaped}"))' in profile
    assert f'(deny file-write* (subpath "{escaped}"))' in profile
    assert f'(allow file-read* (subpath "{runtime.parent}"))' not in profile
    argv = BwrapBackend().spawn_argv(str(workspace), "node --version")
    assert ["--ro-bind", str(runtime), str(runtime)] in [
        argv[i : i + 3] for i in range(len(argv) - 2)
    ]
    assert str(runtime.parent) not in argv
    config = _build_config(str(workspace), "node --version", True)
    assert str(runtime) in config["filesystem"]["readonlyPaths"]
    assert config["filesystem"]["readwritePaths"] == [str(workspace)]


async def test_workspace_cannot_encompass_or_live_inside_store(managed):
    registry, runtime, workspace, _ = managed
    await registry.status()
    for location in (runtime, runtime.parent, workspace.parent):
        with pytest.raises(ValueError, match="overlap"):
            registry.managed_runtime_roots(str(location))


async def test_broken_managed_install_never_falls_back(managed):
    registry, runtime, _, _ = managed
    await registry.status()
    (runtime / "bin" / "npm").unlink()
    await registry.status(force=True)
    assert registry.resolve("node") is None
    assert registry.managed_runtime_roots() == ()


async def test_pointer_cannot_grant_entire_dependency_store(managed):
    registry, runtime, _, pointer = managed
    pointer["directory"] = "."
    dep = runtime.parent.parent
    pointer["executables"] = {
        name: f"versions/24.21.0/bin/{name}" for name in ("node", "npm", "npx")
    }
    (dep / "active.json").write_text(json.dumps(pointer))
    await registry.status()
    assert registry.resolve("node") is None
    assert registry.managed_runtime_roots() == ()


async def test_explicit_system_selection_does_not_gain_private_read_grants(managed, monkeypatch):
    registry, runtime, workspace, _ = managed
    monkeypatch.setattr(settings, "runtime_binary_overrides", {"node": str(runtime / "bin/node")})
    rows = await registry.status()
    assert next(r for r in rows if r["id"] == "nodejs")["source"] == "override"
    assert registry.managed_runtime_roots(str(workspace)) == ()


async def test_missing_managed_runtime_is_not_installed_automatically(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "runtime_source", "managed")
    registry = RuntimeDependencyRegistry(data_dir=tmp_path / "not-created")
    rows = await registry.status()
    assert next(row for row in rows if row["id"] == "nodejs")["status"] == "missing"
    assert registry.resolve("npm") is None
    assert not registry._root.exists()


@pytest.fixture
def public_node(tmp_path, monkeypatch):
    prefix = tmp_path / "homebrew"
    bindir = prefix / "bin"
    bindir.mkdir(parents=True)
    for command in ("node", "npm", "npx"):
        executable = bindir / command
        executable.write_text("#!/bin/sh\nexit 0\n")
        executable.chmod(0o755)
    monkeypatch.setattr("agentos.dependencies.standard_runtime_directories", lambda: [str(bindir)])
    monkeypatch.setattr("agentos.dependencies.standard_runtime_roots", lambda: [str(prefix)])
    monkeypatch.setattr(
        "agentos.terminal_environment.standard_runtime_directories", lambda: [str(bindir)]
    )
    monkeypatch.setattr(settings, "runtime_source", "auto")
    monkeypatch.setattr(settings, "runtime_binary_overrides", {})
    return bindir


async def test_auto_reuses_public_node_without_managed_install(tmp_path, public_node, monkeypatch):
    calls = []

    async def runner(argv, env):
        calls.append(argv[0])
        return 0, b"v24.21.0\n" if argv[0].endswith("node") else b"11.0.0\n", b""

    registry = RuntimeDependencyRegistry(data_dir=tmp_path / "not-created", runner=runner)
    monkeypatch.setattr("agentos.dependencies._REGISTRY", registry)
    rows = await registry.status()
    assert next(row for row in rows if row["id"] == "nodejs")["source"] == "system"
    assert registry.resolve("npm") == str(public_node / "npm")
    assert registry.managed_runtime_roots() == ()
    assert terminal_path(os.defpath).split(os.pathsep)[0] == str(public_node)
    monkeypatch.setattr("agentos.mcp.client._registry_or_none", lambda: registry)
    assert _resolve_stdio_command("npm", {})[0] == str(public_node / "npm")
    assert calls == [str(public_node / name) for name in ("node", "npm", "npx")]
    assert not registry._root.exists()


async def test_auto_keeps_existing_ready_managed_runtime(managed, public_node, monkeypatch):
    registry, runtime, _, _ = managed
    monkeypatch.setattr(registry, "_finder", None)
    await registry.status()
    assert registry.resolve("node") == str(runtime / "bin" / "node")
    assert registry.managed_runtime_roots() == (str(runtime),)


async def test_auto_rejects_public_symlink_into_private_install(tmp_path, public_node):
    private = tmp_path / ".hermes"
    private.mkdir()
    target = private / "npm"
    target.write_text("#!/bin/sh\nexit 0\n")
    target.chmod(0o755)
    (public_node / "npm").unlink()
    (public_node / "npm").symlink_to(target)

    async def never_probe(argv, env):
        pytest.fail("A rejected private runtime must not be health-executed")

    registry = RuntimeDependencyRegistry(data_dir=tmp_path / "not-created", runner=never_probe)
    await registry.status()
    assert registry.resolve("node") is None
    assert registry.resolve("npm") is None


async def test_auto_does_not_mix_node_group_across_directories(tmp_path, public_node, monkeypatch):
    other = public_node.parent / "other-bin"
    other.mkdir()
    (public_node / "npm").rename(other / "npm")
    monkeypatch.setattr(
        "agentos.dependencies.standard_runtime_directories", lambda: [str(public_node), str(other)]
    )
    registry = RuntimeDependencyRegistry(data_dir=tmp_path / "not-created")
    await registry.status()
    assert registry.resolve("node") is None


async def test_auto_rejects_public_prefix_relocated_into_private_tree(tmp_path, public_node):
    prefix = public_node.parent
    private = tmp_path / ".hermes"
    prefix.rename(private)
    prefix.symlink_to(private, target_is_directory=True)

    async def never_probe(argv, env):
        pytest.fail("A relocated private runtime must not be health-executed")

    registry = RuntimeDependencyRegistry(data_dir=tmp_path / "not-created", runner=never_probe)
    await registry.status()
    assert registry.resolve("node") is None


async def test_auto_does_not_fall_back_from_bad_override(tmp_path, public_node, monkeypatch):
    monkeypatch.setattr(
        settings, "runtime_binary_overrides", {"node": str(public_node / "missing")}
    )
    registry = RuntimeDependencyRegistry(data_dir=tmp_path / "not-created")
    row = next(row for row in await registry.status() if row["id"] == "nodejs")
    assert row["status"] == "error" and row["source"] == "override"
    assert registry.resolve("node") is None
