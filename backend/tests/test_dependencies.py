"""W11 dependency readiness — registry status/resolve + operator API.
All health probes use injected runner/finder mocks; no real Node/Git."""

import asyncio

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker

from agentos.dependencies import RuntimeDependencyRegistry


def _runner_ok(versions: dict[str, str]):
    """Runner mock: {path-substring: stdout text}, else exit 0/empty."""

    async def run(argv, env):
        for key, text in versions.items():
            if any(key in a for a in argv):
                return 0, text.encode(), b""
        return 0, b"9.9.9\n", b""

    return run


def _runner_fail():
    async def run(argv, env):
        return 1, b"", b"not found"

    return run


@pytest.fixture
def registry(tmp_path):
    return RuntimeDependencyRegistry(
        data_dir=tmp_path / "managed-runtimes",
        runner=_runner_ok({}),
        finder=lambda cmd: None,  # nothing on the system
        platform_key="darwin-arm64",
    )


def _row(rows, dep_id):
    return next(r for r in rows if r["id"] == dep_id)


async def test_missing_node_is_missing_not_ready(registry):
    rows = await registry.status()
    node = _row(rows, "nodejs")
    assert node["status"] == "missing"
    assert node["source"] == "none"
    assert node["unlocks"]
    assert node["managed_recipe_available"] is True
    assert registry.resolve("node") is None


async def test_all_five_ids_present(registry):
    rows = await registry.status()
    assert {r["id"] for r in rows} == {
        "nodejs",
        "uv",
        "git",
        "libreoffice",
        "chromium",
    }


async def test_ready_node_group(registry, monkeypatch, tmp_path):
    monkeypatch.setenv("PATH", "")
    bindir = tmp_path / "bin"
    bindir.mkdir()
    for cmd in ("node", "npm", "npx"):
        f = bindir / cmd
        f.write_text("#!")
        f.chmod(0o755)

    def finder(cmd):
        p = bindir / cmd
        return str(p) if p.exists() else None

    reg = RuntimeDependencyRegistry(
        data_dir=tmp_path / "rt",
        runner=_runner_ok({"/bin/node": "v24.21.0", "/bin/npm": "11.19.0", "/bin/npx": "11.19.0"}),
        finder=finder,
        platform_key="darwin-arm64",
    )
    rows = await reg.status()
    node = _row(rows, "nodejs")
    assert node["status"] == "ready"
    assert node["source"] == "system"
    assert node["version"] == "24.21.0"
    assert reg.resolve("node") == str(bindir / "node")


async def test_node20_incompatible(tmp_path):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    for cmd in ("node", "npm", "npx"):
        f = bindir / cmd
        f.write_text("#!")
        f.chmod(0o755)
    reg = RuntimeDependencyRegistry(
        data_dir=tmp_path / "rt",
        runner=_runner_ok({"/bin/node": "v20.19.0"}),
        finder=lambda cmd: str(bindir / cmd) if (bindir / cmd).exists() else None,
        platform_key="darwin-arm64",
    )
    node = _row(await reg.status(), "nodejs")
    assert node["status"] == "incompatible"
    assert node["version"] == "20.19.0"


async def test_override_different_parents_is_error(tmp_path, monkeypatch):
    """node from one dir + npm from another is a conflict, never a mix."""
    from agentos.config import settings

    a = tmp_path / "a"
    b = tmp_path / "b"
    a.mkdir()
    b.mkdir()
    for d, cmd in ((a, "node"), (b, "npm")):
        f = d / cmd
        f.write_text("#!")
        f.chmod(0o755)
    monkeypatch.setattr(
        settings,
        "runtime_binary_overrides",
        {"node": str(a / "node"), "npm": str(b / "npm")},
    )
    reg = RuntimeDependencyRegistry(
        data_dir=tmp_path / "rt",
        runner=_runner_ok({}),
        finder=lambda cmd: None,
        platform_key="darwin-arm64",
    )
    node = _row(await reg.status(), "nodejs")
    assert node["status"] == "error"
    assert "different directories" in (node["detail"] or "")


async def test_override_companions_from_same_parent_only(tmp_path, monkeypatch):
    """An explicit node must find npm/npx beside itself — a PATH install
    elsewhere is never borrowed."""
    from agentos.config import settings

    chosen = tmp_path / "chosen"
    other = tmp_path / "other"
    chosen.mkdir()
    other.mkdir()
    for d, cmds in ((chosen, ("node", "npm", "npx")), (other, ("npm", "npx"))):
        for c in cmds:
            f = d / c
            f.write_text("#!")
            f.chmod(0o755)
    monkeypatch.setattr(settings, "runtime_binary_overrides", {"node": str(chosen / "node")})
    reg = RuntimeDependencyRegistry(
        data_dir=tmp_path / "rt",
        runner=_runner_ok({"/chosen/node": "v24.0.0"}),
        finder=lambda cmd: str(other / cmd) if (other / cmd).exists() else None,
        platform_key="darwin-arm64",
    )
    node = _row(await reg.status(), "nodejs")
    assert node["status"] == "ready"
    assert node["source"] == "override"
    assert node["executables"]["npm"] == str(chosen / "npm")


async def test_managed_pointer_malformed_rejected(tmp_path):
    """Strict pointer validation — malformed JSON, wrong platform, path
    escapes and missing pairs all fail closed."""
    root = tmp_path / "rt" / "nodejs"
    root.mkdir(parents=True)
    cases = [
        b"not json",
        b'{"version":"24","platform":"darwin-arm64"}',  # missing directory
        b'{"version":"24.21.0","platform":"linux-x64","directory":"v","executables":{}}',
        b'{"version":"24.21.0","platform":"darwin-arm64","directory":"../escape","executables":{}}',
        b'{"version":"24.21.0","platform":"darwin-arm64","directory":"v","executables":{"node":"/abs"}}',
    ]
    for i, blob in enumerate(cases):
        (root / "active.json").write_bytes(blob)
        reg = RuntimeDependencyRegistry(
            data_dir=tmp_path / "rt",
            runner=_runner_fail(),
            finder=lambda cmd: None,
            platform_key="darwin-arm64",
        )
        node = _row(await reg.status(), "nodejs")
        assert node["status"] in ("missing", "error"), f"case {i}"
        assert reg.resolve("node") is None


async def test_bad_explicit_override_reports_error(tmp_path, monkeypatch):
    from agentos.config import settings

    monkeypatch.setattr(settings, "runtime_binary_overrides", {"node": str(tmp_path / "nope")})
    reg = RuntimeDependencyRegistry(
        data_dir=tmp_path / "rt",
        runner=_runner_ok({}),
        finder=lambda cmd: None,
        platform_key="darwin-arm64",
    )
    node = _row(await reg.status(), "nodejs")
    assert node["status"] == "error"
    assert "node" in (node["detail"] or "")


async def test_system_incompatible_falls_to_managed(tmp_path):
    """Node 20 system group is incompatible → the managed 24 candidate is
    health-evaluated next and wins — exact contract, not a set member."""
    bindir = tmp_path / "bin"
    bindir.mkdir()
    for cmd in ("node", "npm", "npx"):
        f = bindir / cmd
        f.write_text("#!")
        f.chmod(0o755)
    managed = tmp_path / "rt" / "nodejs" / "v24.21.0"
    (managed / "bin").mkdir(parents=True)
    for cmd in ("node", "npm", "npx"):
        f = managed / "bin" / cmd
        f.write_text("#!")
        f.chmod(0o755)
    (tmp_path / "rt" / "nodejs" / "active.json").write_text(
        '{"version":"24.21.0","platform":"darwin-arm64",'
        '"directory":"v24.21.0","executables":'
        '{"node":"bin/node","npm":"bin/npm","npx":"bin/npx"}}'
    )

    async def runner(argv, env):
        if "/v24.21.0/bin/node" in argv[0]:
            return 0, b"v24.21.0\n", b""
        if argv[0].endswith("/bin/node"):
            return 0, b"v20.0.0\n", b""
        return 0, b"11.19.0\n", b""

    reg = RuntimeDependencyRegistry(
        data_dir=tmp_path / "rt",
        runner=runner,
        finder=lambda cmd: str(bindir / cmd) if (bindir / cmd).exists() else None,
        platform_key="darwin-arm64",
    )
    node = _row(await reg.status(), "nodejs")
    assert node["status"] == "ready"
    assert node["source"] == "managed"
    assert node["version"] == "24.21.0"
    assert reg.resolve("node") == str(managed / "bin" / "node")


async def test_coalesced_force_recheck(tmp_path):
    """Two concurrent force reads share ONE pass: the git group costs
    exactly one health exec, not two."""
    bindir = tmp_path / "bin"
    bindir.mkdir()
    f = bindir / "git"
    f.write_text("#!")
    f.chmod(0o755)
    calls = []
    gate = asyncio.Event()

    async def runner(argv, env):
        calls.append(argv[0])
        await gate.wait()
        return 0, b"git version 2.53.0\n", b""

    reg = RuntimeDependencyRegistry(
        data_dir=tmp_path / "rt",
        runner=runner,
        finder=lambda cmd: str(bindir / cmd) if cmd == "git" else None,
        platform_key="darwin-arm64",
    )
    first = asyncio.create_task(reg.status(force=True))
    await asyncio.sleep(0)  # let the first pass reach the runner
    second = asyncio.create_task(reg.status(force=True))
    gate.set()
    a, b = await asyncio.gather(first, second)
    assert a == b
    assert calls.count(str(bindir / "git")) == 1
    await reg.status()
    assert calls.count(str(bindir / "git")) == 1


async def test_resolve_only_ready_paths(registry):
    assert registry.resolve("node") is None
    await registry.status()
    assert registry.resolve("uvx") is None


async def test_last_paths_evicted_when_ready_becomes_missing(tmp_path):
    """A previously-ready path must not survive a later failed pass."""
    bindir = tmp_path / "bin"
    bindir.mkdir()
    f = bindir / "git"
    f.write_text("#!")
    f.chmod(0o755)
    present = {"git": True}

    async def runner(argv, env):
        return 0, b"git version 2.53.0\n", b""

    reg = RuntimeDependencyRegistry(
        data_dir=tmp_path / "rt",
        runner=runner,
        finder=lambda cmd: str(bindir / cmd) if cmd == "git" and present["git"] else None,
        platform_key="darwin-arm64",
    )
    await reg.status()
    assert reg.resolve("git") == str(bindir / "git")
    present["git"] = False
    await reg.status(force=True)
    assert reg.resolve("git") is None


async def test_status_returns_deep_copies(tmp_path):
    reg = RuntimeDependencyRegistry(
        data_dir=tmp_path / "rt",
        runner=_runner_fail(),
        finder=lambda cmd: None,
        platform_key="darwin-arm64",
    )
    first = await reg.status()
    first[0]["executables"]["node"] = "/tmp/evil"
    first[0]["status"] = "ready"
    second = await reg.status()
    assert second[0]["executables"] == {}
    assert second[0]["status"] != "ready"


async def test_version_probe_timeout_marks_error(tmp_path):
    async def runner(argv, env):
        raise TimeoutError

    bindir = tmp_path / "bin"
    bindir.mkdir()
    f = bindir / "git"
    f.write_text("#!")
    f.chmod(0o755)
    reg = RuntimeDependencyRegistry(
        data_dir=tmp_path / "rt",
        runner=runner,
        finder=lambda cmd: str(bindir / cmd) if cmd == "git" else None,
        platform_key="darwin-arm64",
    )
    git = _row(await reg.status(), "git")
    assert git["status"] == "error"


@pytest.fixture
def api_client():
    from agentos.auth import require_operator
    from agentos.main import app

    async def mock_auth():
        return {"id": "op-1", "username": "admin"}

    prior = dict(app.dependency_overrides)
    app.dependency_overrides[require_operator] = mock_auth
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(prior)


def test_dependencies_api_returns_five(api_client, tmp_path, monkeypatch):
    reg = RuntimeDependencyRegistry(
        data_dir=tmp_path / "rt",
        runner=_runner_fail(),
        finder=lambda cmd: None,
        platform_key="darwin-arm64",
    )
    import agentos.dependencies as deps

    monkeypatch.setattr(deps, "_REGISTRY", reg)
    resp = api_client.get("/api/dependencies")
    assert resp.status_code == 200
    rows = resp.json()["dependencies"]
    assert {r["id"] for r in rows} == {
        "nodejs",
        "uv",
        "git",
        "libreoffice",
        "chromium",
    }
    resp2 = api_client.post("/api/dependencies/recheck")
    assert resp2.status_code == 200
    assert resp2.json()["dependencies"]


# -- runner / shim / chromium contract -------------------------------------


@pytest.fixture(autouse=True)
def fake_chromium(monkeypatch):
    """Registry tests never observe the host browser."""
    import agentos.browser.runtime as br

    monkeypatch.setattr(
        br,
        "runtime_status",
        lambda: {"status": "runtime_unavailable", "installable": False, "detail": None},
    )
    monkeypatch.setattr(br, "_platform_key", lambda: None)
    yield


async def test_default_runner_kills_own_child_on_timeout(monkeypatch):
    import agentos.dependencies as deps

    killed = []
    waited = []

    class FakeStream:
        async def read(self, n):
            await asyncio.sleep(60)
            return b""

    class FakeProc:
        def __init__(self):
            self.returncode = None
            self.stdout = FakeStream()
            self.stderr = FakeStream()

        def kill(self):
            killed.append(True)
            self.returncode = -9

        async def wait(self):
            waited.append(True)
            if self.returncode is None:
                await asyncio.sleep(60)  # alive until killed
            return self.returncode

    monkeypatch.setattr(deps.asyncio, "create_subprocess_exec", lambda *a, **k: _af(FakeProc()))
    with pytest.raises(TimeoutError):
        await deps._default_runner(["x", "--version"], env={})
    assert killed and waited


async def test_default_runner_output_bound_kills_and_raises(monkeypatch):
    import agentos.dependencies as deps

    killed = []

    class BigStream:
        async def read(self, n):
            return b"x" * n  # never EOF — blows the cap immediately

    class FakeProc:
        def __init__(self):
            self.returncode = None
            self.stdout = BigStream()
            self.stderr = BigStream()

        def kill(self):
            killed.append(True)
            self.returncode = -9

        async def wait(self):
            return self.returncode if self.returncode is not None else 0

    monkeypatch.setattr(deps.asyncio, "create_subprocess_exec", lambda *a, **k: _af(FakeProc()))
    with pytest.raises(deps.OutputLimitExceeded):
        await deps._default_runner(["x", "--version"], env={})
    assert killed


async def _af(value):
    return value


async def test_git_shim_blocked_never_probes_usr_bin_git(tmp_path, monkeypatch):
    """Apple shim without developer tools → managed candidate is used;
    /usr/bin/git is never executed."""
    calls = []
    managed = tmp_path / "rt" / "git" / "v2"
    managed.mkdir(parents=True)
    f = managed / "git"
    f.write_text("#!")
    f.chmod(0o755)
    (tmp_path / "rt" / "git" / "active.json").write_text(
        '{"version":"2.53.0","platform":"darwin-arm64","directory":"v2",'
        '"executables":{"git":"git"}}'
    )

    async def runner(argv, env):
        calls.append(argv[0])
        if argv[0] == "/usr/bin/xcode-select":
            return 1, b"", b""
        return 0, b"git version 2.53.0\n", b""

    monkeypatch.setattr("agentos.dependencies.platform.system", lambda: "Darwin")
    reg = RuntimeDependencyRegistry(
        data_dir=tmp_path / "rt",
        runner=runner,
        finder=lambda cmd: "/usr/bin/git" if cmd == "git" else None,
        platform_key="darwin-arm64",
    )
    git = _row(await reg.status(), "git")
    assert "/usr/bin/git" not in calls
    assert calls == ["/usr/bin/xcode-select", str(f)]
    assert git["status"] == "ready"
    assert git["source"] == "managed"


async def test_chromium_system_version_not_pinned_claim(tmp_path, monkeypatch):
    """A system Chrome 149 must not wear the managed 145 pin."""
    import agentos.browser.runtime as br

    monkeypatch.setattr(
        br,
        "runtime_status",
        lambda: {
            "status": "ok",
            "binary": "/Applications/Google Chrome.app/chrome",
            "managed": False,
            "source": "system",
            "version": "145.0.7632.6",
        },
    )
    reg = RuntimeDependencyRegistry(
        data_dir=tmp_path / "rt",
        runner=_runner_fail(),
        finder=lambda cmd: None,
        platform_key="darwin-arm64",
    )
    chrome = _row(await reg.status(), "chromium")
    assert chrome["status"] == "ready"
    assert chrome["source"] == "system"
    assert chrome["version"] is None


def test_dependencies_api_unauthenticated_rejected(db_engine, monkeypatch, tmp_path):
    """Real require_operator — no auth override → 401, not an open seam."""
    import agentos.dependencies as deps
    from agentos.db import get_db
    from agentos.main import app

    reg = RuntimeDependencyRegistry(
        data_dir=tmp_path / "rt",
        runner=_runner_fail(),
        finder=lambda cmd: None,
        platform_key="darwin-arm64",
    )
    monkeypatch.setattr(deps, "_REGISTRY", reg)
    factory = async_sessionmaker(db_engine, expire_on_commit=False)

    async def get_test_db():
        async with factory() as session:
            yield session

    prior = dict(app.dependency_overrides)
    app.dependency_overrides[get_db] = get_test_db
    try:
        resp = TestClient(app).get("/api/dependencies")
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(prior)
    assert resp.status_code == 401


# -- strict runner / pointer / windows contracts -----------------------------


async def test_runner_output_overrun_raises_limit_not_timeout(monkeypatch):
    """A live stdout flood raises OutputLimitExceeded immediately and the
    child is still killed — not a misleading TimeoutError."""
    import agentos.dependencies as deps

    killed = []

    class Flood:
        async def read(self, n):
            return b"x" * n

    class FakeProc:
        def __init__(self):
            self.returncode = None
            self.stdout = Flood()
            self.stderr = Flood()

        def kill(self):
            killed.append(True)
            self.returncode = -9

        async def wait(self):
            if self.returncode is None:
                await asyncio.sleep(60)
            return self.returncode

    monkeypatch.setattr(deps.asyncio, "create_subprocess_exec", lambda *a, **k: _af(FakeProc()))
    with pytest.raises(deps.OutputLimitExceeded):
        await deps._default_runner(["x", "--version"], env={})
    assert killed


async def test_runner_deadline_when_process_exited_but_pipes_open(monkeypatch):
    """Child exited (returncode 0) but inherited pipes stay open → the
    whole call still respects the deadline."""
    import agentos.dependencies as deps

    monkeypatch.setattr(deps, "_CMD_TIMEOUT", 0.2)

    class OpenPipe:
        async def read(self, n):
            await asyncio.sleep(60)
            return b""

    class FakeProc:
        def __init__(self):
            self.returncode = 0  # already exited
            self.stdout = OpenPipe()
            self.stderr = OpenPipe()

        def kill(self):
            pass

        async def wait(self):
            return 0

    monkeypatch.setattr(deps.asyncio, "create_subprocess_exec", lambda *a, **k: _af(FakeProc()))
    with pytest.raises(TimeoutError):
        await deps._default_runner(["x", "--version"], env={})


async def test_pointer_read_is_bounded_and_contained(tmp_path):
    """dep-root/pointer escapes and oversized pointers never even open a
    probe — no health call runs against them."""
    root = tmp_path / "rt"
    dep_dir = root / "git"
    dep_dir.mkdir(parents=True)
    # Oversized pointer under a contained path → rejected, no health call.
    (dep_dir / "active.json").write_bytes(b" " * 20000)
    calls = []

    async def runner(argv, env):
        calls.append(argv[0])
        return 0, b"git version 2.0.0\n", b""

    reg = RuntimeDependencyRegistry(
        data_dir=root,
        runner=runner,
        finder=lambda cmd: None,
        platform_key="darwin-arm64",
    )
    git = _row(await reg.status(), "git")
    assert git["status"] != "ready"
    assert str(dep_dir) not in str(calls)

    # dep root symlinked outside the configured root → rejected before read.
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "active.json").write_text(
        '{"version":"2.0.0","platform":"darwin-arm64","directory":"v","executables":{"git":"git"}}'
    )
    (outside / "v").mkdir()
    (outside / "v" / "git").write_text("#!")
    (outside / "v" / "git").chmod(0o755)
    root2 = tmp_path / "rt2"
    root2.mkdir()
    (root2 / "git").symlink_to(outside, target_is_directory=True)
    reg2 = RuntimeDependencyRegistry(
        data_dir=root2,
        runner=runner,
        finder=lambda cmd: None,
        platform_key="darwin-arm64",
    )
    git2 = _row(await reg2.status(), "git")
    assert git2["status"] != "ready"


async def test_first_bad_system_candidate_falls_through(tmp_path):
    """Two system git installs — the first fails health, the second is
    ready. Single-command candidates iterate every location."""
    a = tmp_path / "a"
    b = tmp_path / "b"
    a.mkdir()
    b.mkdir()
    for d in (a, b):
        f = d / "git"
        f.write_text("#!")
        f.chmod(0o755)
    monkey_paths = [str(a / "git"), str(b / "git")]

    async def runner(argv, env):
        if argv[0] == str(a / "git"):
            return 1, b"", b"broken"
        return 0, b"git version 2.53.0\n", b""

    def find_all(self, command, dirs):
        if command == "git":
            return list(monkey_paths)
        return []

    reg = RuntimeDependencyRegistry(
        data_dir=tmp_path / "rt",
        runner=runner,
        finder=None,
        platform_key="darwin-arm64",
    )
    # Patch the instance method so we control the dir scan deterministically.
    reg._find_all_in_dirs = find_all.__get__(reg, RuntimeDependencyRegistry)
    git = _row(await reg.status(), "git")
    assert git["status"] == "ready"
    assert git["executables"]["git"] == str(b / "git")


@pytest.mark.asyncio
async def test_windows_node_group_via_trusted_cli(monkeypatch, tmp_path):
    """Simulated Windows: npm/npx .cmd wrappers run through the co-installed
    node.exe + fixed cli.js — exact argv, never a shell."""
    import agentos.dependencies as deps_mod

    monkeypatch.setattr(deps_mod.platform, "system", lambda: "Windows")
    install = tmp_path / "node"
    (install / "node_modules" / "npm" / "bin").mkdir(parents=True)
    for name, text in (
        ("node.exe", "x"),
        ("npm.cmd", "x"),
        ("npx.cmd", "x"),
        ("node_modules/npm/bin/npm-cli.js", "x"),
        ("node_modules/npm/bin/npx-cli.js", "x"),
    ):
        (install / name).write_text(text)
    argv_seen = []

    async def runner(argv, env):
        argv_seen.append(argv)
        if argv[0].endswith("node.exe") and len(argv) == 2:
            return 0, b"v22.22.3\n", b""
        return 0, b"11.19.0\n", b""

    def finder(cmd):
        names = {"node": "node.exe", "npm": "npm.cmd", "npx": "npx.cmd"}
        p = install / names[cmd]
        return str(p) if p.exists() else None

    reg = RuntimeDependencyRegistry(
        data_dir=tmp_path / "rt",
        runner=runner,
        finder=finder,
        platform_key="windows-arm64",
    )
    node = _row(await reg.status(), "nodejs")
    assert node["status"] == "ready"
    node_exe = str(install / "node.exe")
    # npm/npx probed via node.exe + the trusted cli.js, never the .cmd.
    assert any(
        a == [node_exe, str(install / "node_modules" / "npm" / "bin" / "npm-cli.js"), "--version"]
        for a in argv_seen
    )
    assert not any(str(a[0]).endswith(".cmd") for a in argv_seen)


async def test_windows_untrusted_wrapper_never_executes(monkeypatch, tmp_path):
    """A .cmd whose cli.js is absent (or escapes the install) is not a
    ready runtime — and is never passed to a shell."""
    import agentos.dependencies as deps_mod

    monkeypatch.setattr(deps_mod.platform, "system", lambda: "Windows")
    install = tmp_path / "node"
    install.mkdir()
    for name in ("node.exe", "npm.cmd", "npx.cmd"):
        (install / name).write_text("x")
    argv_seen = []

    async def runner(argv, env):
        argv_seen.append(argv)
        return 0, b"v22.0.0\n", b""

    def finder(cmd):
        names = {"node": "node.exe", "npm": "npm.cmd", "npx": "npx.cmd"}
        p = install / names[cmd]
        return str(p) if p.exists() else None

    reg = RuntimeDependencyRegistry(
        data_dir=tmp_path / "rt",
        runner=runner,
        finder=finder,
        platform_key="windows-arm64",
    )
    node = _row(await reg.status(), "nodejs")
    assert node["status"] != "ready"
    assert not any(str(a[0]).endswith(".cmd") for a in argv_seen)


async def test_windows_libreoffice_programfiles(monkeypatch, tmp_path):
    """PROGRAMFILES well-known dir resolves soffice.exe on simulated
    Windows."""
    import agentos.dependencies as deps_mod

    monkeypatch.setattr(deps_mod.platform, "system", lambda: "Windows")
    prog = tmp_path / "Program Files"
    soffice = prog / "LibreOffice" / "program" / "soffice.exe"
    soffice.parent.mkdir(parents=True)
    soffice.write_text("x")
    monkeypatch.setenv("PROGRAMFILES", str(prog))
    argv_seen = []

    async def runner(argv, env):
        argv_seen.append(argv)
        return 0, b"LibreOffice 25.2.0\n", b""

    reg = RuntimeDependencyRegistry(
        data_dir=tmp_path / "rt",
        runner=runner,
        platform_key="windows-arm64",
    )
    lo = _row(await reg.status(), "libreoffice")
    assert lo["status"] == "ready"
    assert lo["version"] == "25.2.0"
    assert [str(soffice), "--version"] in argv_seen
