"""Shared runtime-dependency primitives — path containment, executability,
child env, and the fixed npm/npx cli.js entrypoint."""

import os

from agentos.runtime_support import (
    inside,
    is_executable,
    npm_entrypoint,
    probe_environment,
)


def test_inside_accepts_child_and_rejects_sibling(tmp_path):
    parent = tmp_path / "root"
    (parent / "sub").mkdir(parents=True)
    child = parent / "sub" / "f.js"
    child.write_text("x")
    assert inside(child, parent) is True
    sibling = tmp_path / "other" / "f.js"
    sibling.parent.mkdir()
    sibling.write_text("x")
    assert inside(sibling, parent) is False


def test_is_executable_posix_and_windows_semantics(tmp_path, monkeypatch):
    f = tmp_path / "tool"
    f.write_text("x")
    # POSIX branch consults os.access(X_OK) — mocked so non-POSIX hosts
    # exercise the same semantics.
    monkeypatch.setattr("os.access", lambda p, m: True)
    assert is_executable(f, windows=False) is True
    monkeypatch.setattr("os.access", lambda p, m: False)
    assert is_executable(f, windows=False) is False
    # Windows: extension-based, never consults X_OK.
    exe = tmp_path / "tool.exe"
    exe.write_text("x")
    txt = tmp_path / "tool.txt"
    txt.write_text("x")
    calls = []
    monkeypatch.setattr(
        "os.access",
        lambda *a: (
            calls.append(a) or (_ for _ in ()).throw(AssertionError("X_OK used on Windows path"))
        ),
    )
    assert is_executable(exe, windows=True) is True
    assert is_executable(txt, windows=True) is False


def test_probe_environment_prepends_dirs_and_fixed_flags(monkeypatch, tmp_path):
    monkeypatch.setenv("PATH", "/usr/bin")
    monkeypatch.setenv("npm_config_update_notifier", "true")  # pre-set → overridden
    before = dict(os.environ)
    env = probe_environment(
        {"node": str(tmp_path / "bin" / "node"), "uv": str(tmp_path / "bin" / "uv")}
    )
    assert env["PATH"].startswith(str(tmp_path / "bin"))
    assert env["npm_config_update_notifier"] == "false"
    assert env["npm_config_audit"] == "false"
    assert env["npm_config_fund"] == "false"
    assert env["UV_NO_PROGRESS"] == "1"
    # os.environ itself is never mutated — a copy carries the fixed flags
    assert dict(os.environ) == before


def test_npm_entrypoint_requires_coinstalled_node(tmp_path):
    bindir = tmp_path / "bin"
    script = bindir / "node_modules" / "npm" / "bin" / "npm-cli.js"
    script.parent.mkdir(parents=True)
    script.write_text("x")
    npm = bindir / "npm"
    node = bindir / "node"
    npm.write_text("x")
    node.write_text("x")
    exes = {"npm": str(npm), "node": str(node)}
    out = npm_entrypoint("npm", npm, exes)
    assert out is not None
    node_path, resolved_script = out
    assert node_path == str(node)
    assert resolved_script == script

    # node elsewhere → no wrapper invocation
    other = tmp_path / "elsewhere" / "node"
    other.parent.mkdir()
    other.write_text("x")
    assert npm_entrypoint("npm", npm, {"npm": str(npm), "node": str(other)}) is None


def test_npm_entrypoint_rejects_symlink_escape_and_unknown_cmd(tmp_path):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    outside = tmp_path / "outside" / "npm-cli.js"
    outside.parent.mkdir()
    outside.write_text("x")
    link = bindir / "node_modules" / "npm" / "bin"
    link.mkdir(parents=True)
    (link / "npm-cli.js").symlink_to(outside)
    npm = bindir / "npm"
    npm.write_text("x")
    node = bindir / "node"
    node.write_text("x")
    exes = {"npm": str(npm), "node": str(node)}
    # default root is the wrapper's parent — the resolved script escapes it
    assert npm_entrypoint("npm", npm, exes) is None
    # explicit root bound — resolved script escapes root → rejected
    assert npm_entrypoint("npm", npm, exes, root=bindir) is None
    # non-npm command never gets a cli.js mapping
    assert npm_entrypoint("node", node, exes) is None
