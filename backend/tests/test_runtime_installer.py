"""W11 managed installer — plan/start/job/cancel seams, all I/O mocked."""

import asyncio
import hashlib
import io
import json
import tarfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker

from agentos.dependencies import RuntimeDependencyRegistry
from agentos.runtime_installer import PlanError, RuntimeInstaller


def _install_fake_mcp(monkeypatch, capture: dict):
    """Minimal SDK stand-ins — captures StdioServerParameters, no anyio."""
    import sys
    import types

    class _Session:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def initialize(self):
            return None

    stdio_mod = types.ModuleType("mcp.client.stdio")

    class StdioServerParameters:
        def __init__(self, command, args, env):
            self.command = command
            self.args = args
            self.env = env

    class _Ctx:
        def __init__(self, params):
            capture["params"] = params

        async def __aenter__(self):
            return (object(), object())

        async def __aexit__(self, *a):
            return False

    stdio_mod.StdioServerParameters = StdioServerParameters
    stdio_mod.stdio_client = lambda params: _Ctx(params)
    http_mod = types.ModuleType("mcp.client.streamable_http")
    http_mod.streamable_http_client = lambda *a, **k: _Ctx(k)
    mcp_mod = types.ModuleType("mcp")
    mcp_mod.ClientSession = _Session
    monkeypatch.setitem(sys.modules, "mcp", mcp_mod)
    monkeypatch.setitem(sys.modules, "mcp.client", types.ModuleType("mcp.client"))
    monkeypatch.setitem(sys.modules, "mcp.client.stdio", stdio_mod)
    monkeypatch.setitem(sys.modules, "mcp.client.streamable_http", http_mod)


def _recipe_env(**dep_overrides):
    """Enveloped fixture recipes (same shape as the bundled file)."""
    recipes = {
        "git": {
            "version": "2.53.0",
            "publisher": "Test Publisher",
            "license": "MIT",
            "metadata_url": "https://example.com/m.json",
            "verification": "publisher_checksum",
            "health_versions": {"git": "2.53.0"},
            "platforms": {
                "test-plat": {
                    "url": "https://objects.githubusercontent.com/fake/git.tgz",
                    "sha256": "0" * 64,
                    "archive_format": "tar.gz",
                    "roots": ["."],
                    "executables": {"git": "bin/git"},
                    "download_bytes": None,
                }
            },
        },
        "nodejs": {
            "version": "24.21.0",
            "publisher": "Test Publisher",
            "license": "MIT",
            "metadata_url": "https://example.com/n.json",
            "verification": "publisher_checksum",
            "health_versions": {"node": "24.21.0", "npm": "11.19.0", "npx": "11.19.0"},
            "platforms": {
                "test-plat": {
                    "url": "https://objects.githubusercontent.com/fake/node.tgz",
                    "sha256": "0" * 64,
                    "archive_format": "tar.gz",
                    "roots": ["node-v24"],
                    "executables": {"node": "bin/node", "npm": "bin/npm", "npx": "bin/npx"},
                    "download_bytes": None,
                }
            },
        },
    }
    for dep, patch in dep_overrides.items():
        recipes[dep].update(patch)
    return {"schema_version": 1, "recipes": recipes}


def _tar(members: dict[str, bytes | None], extra=None) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        for name, data in members.items():
            if data is None:
                ti = tarfile.TarInfo(name)
                ti.type = tarfile.DIRTYPE
                tf.addfile(ti)
            else:
                ti = tarfile.TarInfo(name)
                ti.size = len(data)
                ti.mode = 0o755
                tf.addfile(ti, io.BytesIO(data))
        if extra:
            extra(tf)
    return buf.getvalue()


async def _healthy_runner(argv, env):
    return 0, b"2.53.0\n", b""


def _status_rows(overrides=None):
    rows = [
        {
            "id": d,
            "status": "missing",
            "source": "none",
            "version": None,
            "executables": {},
            "detail": None,
            "unlocks": "",
            "managed_recipe_available": True,
            "guidance_url": None,
        }
        for d in ("nodejs", "uv", "git", "chromium")
    ]
    for i, patch in (overrides or {}).items():
        rows[i].update(patch)
    return rows


def _installer(
    tmp_path,
    *,
    download=None,
    runner=None,
    status_rows=None,
    recipes=None,
    platform_key="test-plat",
    http_transport=None,
):
    rec = recipes or _recipe_env()
    reg = RuntimeDependencyRegistry(
        data_dir=tmp_path / "rt",
        runner=runner or _healthy_runner,
        finder=lambda cmd: None,
        platform_key=platform_key,
    )
    if status_rows is not None:

        async def fake_status(force=False):
            return status_rows

        reg.status = fake_status
    return RuntimeInstaller(
        registry=reg,
        data_dir=tmp_path / "rt",
        download=download,
        health_runner=runner or _healthy_runner,
        platform_key=platform_key,
        recipes=rec,
        http_transport=http_transport,
    )


def _download_for(blob: bytes, sha: str | None = None):
    digest = sha or hashlib.sha256(blob).hexdigest()

    async def download(url, target, job, cancel):
        target.write_bytes(blob)
        return len(blob), digest

    return download


def _with_blobs(recipes_env, **blobs):
    """Fill fixture recipe sha256 with the real digest of each blob."""
    for dep, blob in blobs.items():
        recipes_env["recipes"][dep]["platforms"]["test-plat"]["sha256"] = hashlib.sha256(
            blob
        ).hexdigest()
    return recipes_env


# -- plan --------------------------------------------------------------------


async def test_plan_no_downloads_and_frozen(tmp_path):
    blob = _tar({"bin/git": b"#!"})
    installer = _installer(
        tmp_path,
        download=_download_for(blob),
        status_rows=_status_rows(),
        recipes=_with_blobs(_recipe_env(), git=blob),
    )
    plan = await installer.plan(["git"], "op-1")
    dep = plan["dependencies"][0]
    assert dep["action"] == "install"
    assert dep["version"] == "2.53.0"
    assert dep["download_url"].startswith("https://")
    assert dep["sha256"] == hashlib.sha256(blob).hexdigest()
    assert "versions/2.53.0-" in dep["destination"]
    # Public plan must not leak operator-id or internals.
    assert "operator_id" not in plan
    assert not (tmp_path / "rt" / "git").exists()


async def test_plan_rejects_invalid_sha_at_plan_time(tmp_path):
    """A recipe without a 64-hex checksum fails the plan — not post-download."""
    rec = _recipe_env()
    rec["recipes"]["git"]["platforms"]["test-plat"]["sha256"] = "not-a-sha"
    installer = _installer(tmp_path, status_rows=_status_rows(), recipes=rec)
    with pytest.raises(PlanError) as e:
        await installer.plan(["git"], "op-1")
    assert e.value.status == 409


async def test_plan_reuse_when_ready(tmp_path):
    rows = _status_rows(
        {
            2: {
                "status": "ready",
                "version": "2.53.0",
                "source": "system",
                "executables": {"git": "/usr/bin/git"},
            }
        }
    )
    rec = _with_blobs(_recipe_env(), git=b"")
    installer = _installer(tmp_path, status_rows=rows, recipes=rec)
    plan = await installer.plan(["git"], "op-1")
    assert plan["dependencies"][0]["action"] == "reuse"


async def test_plan_rejects_unknown_and_duplicate(tmp_path):
    installer = _installer(tmp_path)
    with pytest.raises(PlanError):
        await installer.plan(["git", "git"], "op-1")
    with pytest.raises(PlanError):
        await installer.plan(["ffmpeg"], "op-1")
    with pytest.raises(PlanError):
        await installer.plan([], "op-1")


async def test_plan_unsupported_platform(tmp_path):
    installer = _installer(tmp_path, platform_key="nope-os")
    with pytest.raises(PlanError) as e:
        await installer.plan(["git"], "op-1")
    assert e.value.status == 409


async def test_plan_uses_bundled_prod_envelope(tmp_path):
    """No recipes= override — the real bundled envelope loads; plan shows
    the actual publisher metadata for all three managed deps."""
    from agentos.dependencies import _platform_key

    reg = RuntimeDependencyRegistry(
        data_dir=tmp_path / "rt",
        runner=_healthy_runner,
        finder=lambda c: None,
        platform_key=_platform_key(),
    )

    async def fake_status(force=False):
        return _status_rows()

    reg.status = fake_status
    installer = RuntimeInstaller(
        registry=reg,
        data_dir=tmp_path / "rt",
        download=None,
        health_runner=_healthy_runner,
        platform_key=_platform_key(),
    )
    if _platform_key() is None:
        pytest.skip("linux platform — no bundled recipe")
    plan = await installer.plan(["nodejs", "uv", "git"], "op-1")
    by_id = {d["id"]: d for d in plan["dependencies"]}
    assert by_id["nodejs"]["version"] == "24.21.0"
    assert by_id["nodejs"]["publisher"] == "Node.js release team"
    assert by_id["uv"]["version"] == "0.12.24"
    assert by_id["git"]["version"] == "2.53.0"
    assert all(d["download_url"].startswith("https://") for d in plan["dependencies"])
    assert all(d["sha256"] and len(d["sha256"]) == 64 for d in plan["dependencies"])


# -- start --------------------------------------------------------------------


async def test_start_requires_consent(tmp_path):
    installer = _installer(tmp_path, status_rows=_status_rows())
    plan = await installer.plan(["git"], "op-1")
    with pytest.raises(PlanError):
        await installer.start(plan["id"], "op-1", False)


async def test_start_idempotent_same_job(tmp_path):
    blob = _tar({"bin/git": b"#!/git"})
    installer = _installer(
        tmp_path,
        download=_download_for(blob),
        status_rows=_status_rows(),
        recipes=_with_blobs(_recipe_env(), git=blob),
    )
    plan = await installer.plan(["git"], "op-1")
    job1 = await installer.start(plan["id"], "op-1", True)
    job2 = await installer.start(plan["id"], "op-1", True)
    assert job1["id"] == job2["id"]
    await asyncio.wait_for(installer._jobs[job1["id"]], timeout=10)
    final = installer.get_job(job1["id"], "op-1")
    assert final["state"] == "completed"
    pointer = json.loads((tmp_path / "rt" / "git" / "active.json").read_text())
    assert pointer["version"] == "2.53.0"
    assert pointer["executables"]["git"] == "bin/git"  # rel inside version dir
    assert pointer["directory"].startswith("versions/2.53.0-")


async def test_checksum_mismatch_no_activation(tmp_path):
    blob = _tar({"bin/git": b"#!/git"})
    installer = _installer(
        tmp_path,
        download=_download_for(blob, sha="0" * 64),
        status_rows=_status_rows(),
        recipes=_with_blobs(_recipe_env(), git=blob),
    )
    plan = await installer.plan(["git"], "op-1")
    job = await installer.start(plan["id"], "op-1", True)
    await asyncio.wait_for(installer._jobs[job["id"]], timeout=10)
    assert installer.get_job(job["id"], "op-1")["state"] == "failed"
    assert not (tmp_path / "rt" / "git" / "active.json").exists()


async def test_health_failure_retains_old_pointer(tmp_path):
    """Health gate runs against the extracted bytes — runner CALLS counted
    to prove the failure is at verify, not checksum."""
    calls = []
    root = tmp_path / "rt" / "git"
    (root / "old" / "bin").mkdir(parents=True)
    old_git = root / "old" / "bin" / "git"
    old_git.write_text("#!")
    old_git.chmod(0o755)
    (root / "active.json").write_text(
        json.dumps(
            {
                "version": "2.40.0",
                "platform": "test-plat",
                "directory": "old",
                "executables": {"git": "bin/git"},
            }
        )
    )
    blob = _tar({"bin/git": b"#!/git"})

    async def bad_runner(argv, env):
        calls.append(argv[0])
        return 1, b"", b""

    installer = _installer(
        tmp_path,
        download=_download_for(blob),
        runner=bad_runner,
        status_rows=_status_rows(),
        recipes=_with_blobs(_recipe_env(), git=blob),
    )
    plan = await installer.plan(["git"], "op-1")
    job = await installer.start(plan["id"], "op-1", True)
    await asyncio.wait_for(installer._jobs[job["id"]], timeout=10)
    final = installer.get_job(job["id"], "op-1")
    assert final["state"] == "failed"
    assert calls, "health runner must have been invoked"
    pointer = json.loads((root / "active.json").read_text())
    assert pointer["version"] == "2.40.0"


async def test_archive_traversal_rejected(tmp_path):
    blob = _tar({"../escape/evil": b"x", "bin/git": b"#!"})
    installer = _installer(
        tmp_path,
        download=_download_for(blob),
        status_rows=_status_rows(),
        recipes=_with_blobs(_recipe_env(), git=blob),
    )
    plan = await installer.plan(["git"], "op-1")
    job = await installer.start(plan["id"], "op-1", True)
    await asyncio.wait_for(installer._jobs[job["id"]], timeout=10)
    assert installer.get_job(job["id"], "op-1")["state"] == "failed"
    assert not (tmp_path / "escape").exists()


async def test_symlink_escape_rejected_but_contained_allowed(tmp_path):
    def escaping(tf):
        ti = tarfile.TarInfo("bin/link")
        ti.type = tarfile.SYMTYPE
        ti.linkname = "../../etc/passwd"
        tf.addfile(ti)

    blob = _tar({"bin/git": b"#!"}, extra=escaping)
    installer = _installer(
        tmp_path,
        download=_download_for(blob),
        status_rows=_status_rows(),
        recipes=_with_blobs(_recipe_env(), git=blob),
    )
    plan = await installer.plan(["git"], "op-1")
    job = await installer.start(plan["id"], "op-1", True)
    await asyncio.wait_for(installer._jobs[job["id"]], timeout=10)
    assert installer.get_job(job["id"], "op-1")["state"] == "failed"

    # Contained relative links (Node-style ../lib/...) are legal.
    def contained(tf):
        d = tarfile.TarInfo("node-v24/lib/node_modules/npm/bin")
        d.type = tarfile.DIRTYPE
        tf.addfile(d)
        cli = tarfile.TarInfo("node-v24/lib/node_modules/npm/bin/npm-cli.js")
        cli.size = 2
        cli.mode = 0o755
        tf.addfile(cli, io.BytesIO(b"//"))
        lnk = tarfile.TarInfo("node-v24/bin/npm")
        lnk.type = tarfile.SYMTYPE
        lnk.linkname = "../lib/node_modules/npm/bin/npm-cli.js"
        tf.addfile(lnk)

    blob2 = _tar({"node-v24/bin/node": b"#!", "node-v24/bin/npx": b"#"}, extra=contained)
    rec2 = _with_blobs(_recipe_env(), nodejs=blob2)
    reg2 = RuntimeDependencyRegistry(
        data_dir=tmp_path / "rt2",
        runner=None,
        finder=lambda c: None,
        platform_key="test-plat",
    )

    async def fake_status(force=False):
        return _status_rows()

    reg2.status = fake_status

    async def node_runner(argv, env):
        out = b"24.21.0\n" if argv[0].endswith("node") else b"11.19.0\n"
        return 0, out, b""

    installer2 = RuntimeInstaller(
        registry=reg2,
        data_dir=tmp_path / "rt2",
        download=_download_for(blob2),
        health_runner=node_runner,
        platform_key="test-plat",
        recipes=rec2,
    )
    plan2 = await installer2.plan(["nodejs"], "op-1")
    job2 = await installer2.start(plan2["id"], "op-1", True)
    await asyncio.wait_for(installer2._jobs[job2["id"]], timeout=10)
    assert installer2.get_job(job2["id"], "op-1")["state"] == "completed"
    # The ../ symlink survived inside the version dir.
    version_dir = (
        tmp_path
        / "rt2"
        / "nodejs"
        / json.loads((tmp_path / "rt2" / "nodejs" / "active.json").read_text())["directory"]
    )
    assert (version_dir / "bin" / "npm").is_symlink()
    # The resolved link target stays inside the install — no escape.
    target = (version_dir / "bin" / "npm").resolve()
    assert str(target).startswith(str(version_dir))


async def test_pointer_drives_registry_resolve_and_mcp(tmp_path):
    """End-to-end: installed managed runtime → registry resolve → MCP
    resolver selects the verified executable with the install dir on the
    child PATH."""
    blob = _tar({"bin/git": b"#!"})
    calls = []

    async def git_runner(argv, env):
        calls.append(argv[0])
        return 0, b"git version 2.53.0\n", b""

    recipes = _with_blobs(_recipe_env(), git=blob)
    reg = RuntimeDependencyRegistry(
        data_dir=tmp_path / "rt",
        runner=git_runner,
        finder=lambda c: None,
        platform_key="test-plat",
    )
    installer = RuntimeInstaller(
        registry=reg,
        data_dir=tmp_path / "rt",
        download=_download_for(blob),
        health_runner=git_runner,
        platform_key="test-plat",
        recipes=recipes,
    )
    plan = await installer.plan(["git"], "op-1")
    job = await installer.start(plan["id"], "op-1", True)
    await asyncio.wait_for(installer._jobs[job["id"]], timeout=10)
    assert installer.get_job(job["id"], "op-1")["state"] == "completed"
    # Registry health-verifies the managed install (same runner seam).
    rows = await reg.status(force=True)
    git_row = next(r for r in rows if r["id"] == "git")
    assert git_row["status"] == "ready"
    assert git_row["source"] == "managed"
    resolved = reg.resolve("git")
    assert resolved and resolved.endswith("bin/git")

    import agentos.mcp.client as client

    monkeypatch_client = client._registry_or_none
    client._registry_or_none = lambda: reg
    try:
        cmd, env = client._resolve_stdio_command("git", {"PATH": "/nonexistent"})
    finally:
        client._registry_or_none = monkeypatch_client
    assert cmd == resolved
    assert env["PATH"].split(":")[0] == str(Path(resolved).parent)


async def test_plan_recipe_change_rejected(tmp_path):
    blob = _tar({"bin/git": b"#!/git"})
    rec = _with_blobs(_recipe_env(), git=blob)
    installer = _installer(
        tmp_path,
        download=_download_for(blob),
        status_rows=_status_rows(),
        recipes=rec,
    )
    plan = await installer.plan(["git"], "op-1")
    rec["recipes"]["git"]["version"] = "9.9.9"  # upstream metadata drifted
    with pytest.raises(PlanError) as e:
        await installer.start(plan["id"], "op-1", True)
    assert e.value.status == 409
    # A FRESH plan works against the new bundle — no restart needed.
    plan2 = await installer.plan(["git"], "op-1")
    assert plan2["dependencies"][0]["version"] == "9.9.9"


async def test_plan_expired_rejected_via_clock(tmp_path, monkeypatch):
    installer = _installer(tmp_path, status_rows=_status_rows())
    plan = await installer.plan(["git"], "op-1")
    import agentos.runtime_installer as ri

    real = ri.utcnow
    monkeypatch.setattr(ri, "utcnow", lambda: real() + __import__("datetime").timedelta(hours=1))
    with pytest.raises(PlanError) as e:
        await installer.start(plan["id"], "op-1", True)
    assert e.value.status == 409


async def test_conflicting_dependency_serialized(tmp_path):
    blob = _tar({"bin/git": b"#!/git"})
    installer = _installer(
        tmp_path,
        download=_download_for(blob),
        status_rows=_status_rows(),
        recipes=_with_blobs(_recipe_env(), git=blob),
    )
    plan1 = await installer.plan(["git"], "op-1")
    job1 = await installer.start(plan1["id"], "op-1", True)
    plan2 = await installer.plan(["git"], "op-1")
    with pytest.raises(PlanError) as e:
        await installer.start(plan2["id"], "op-1", True)
    assert e.value.status == 409
    await asyncio.wait_for(installer._jobs[job1["id"]], timeout=10)


async def test_get_job_owner_scoped(tmp_path):
    installer = _installer(tmp_path, status_rows=_status_rows())
    with pytest.raises(PlanError) as e:
        installer.get_job("nope", "op-2")
    assert e.value.status == 404


async def test_interrupted_reconcile(tmp_path):
    root = tmp_path / "rt"
    (root / "jobs").mkdir(parents=True)
    (root / "jobs" / ("a" * 32 + ".json")).write_text(
        json.dumps(
            {
                "id": "a" * 32,
                "operator_id": "op-1",
                "state": "downloading",
                "dependencies": [{"id": "git", "action": "install"}],
            }
        )
    )
    installer = _installer(tmp_path)
    job = installer.get_job("a" * 32, "op-1")
    assert job["state"] == "interrupted"


async def test_queued_cancel_resolves(tmp_path):
    """A cancel before the worker's first await still terminates: the
    event is pre-set and the done callback releases the lock."""

    async def slow_download(url, target, job, cancel):
        await asyncio.sleep(5)
        return 0, hashlib.sha256(b"").hexdigest()

    recipes = _with_blobs(_recipe_env(), git=b"")
    installer = _installer(
        tmp_path, download=slow_download, status_rows=_status_rows(), recipes=recipes
    )
    plan = await installer.plan(["git"], "op-1")
    job = await installer.start(plan["id"], "op-1", True)
    cancelled = await installer.cancel(job["id"], "op-1")
    assert cancelled["state"] == "cancelling"
    task = installer._jobs[job["id"]]
    try:
        await asyncio.wait_for(task, timeout=10)
    except asyncio.CancelledError:
        pass
    final = installer.get_job(job["id"], "op-1")
    assert final["state"] == "cancelled"
    dep = next(d for d in final["dependencies"] if d["id"] == "git")
    assert dep["status"] == "not_started"  # worker never reached it


async def test_cancel_marks_dependency_states(tmp_path):
    """Cancelling mid-download finalizes every pending dep honestly —
    the in-flight one is 'cancelled', later ones 'not_started', and the
    same statuses survive a persistence reload."""
    entered = asyncio.Event()

    async def held_download(url, target, job, cancel):
        entered.set()
        await asyncio.Future()
        return 0, hashlib.sha256(b"").hexdigest()

    recipes = _with_blobs(_recipe_env(), git=b"", nodejs=b"")
    installer = _installer(
        tmp_path,
        download=held_download,
        status_rows=_status_rows(),
        recipes=recipes,
    )
    plan = await installer.plan(["git", "nodejs"], "op-1")
    job = await installer.start(plan["id"], "op-1", True)
    await asyncio.wait_for(entered.wait(), timeout=2.0)
    await installer.cancel(job["id"], "op-1")
    task = installer._jobs[job["id"]]
    try:
        await asyncio.wait_for(task, timeout=10)
    except asyncio.CancelledError:
        pass

    final = installer.get_job(job["id"], "op-1")
    assert final["state"] == "cancelled"
    statuses = {d["id"]: d["status"] for d in final["dependencies"]}
    assert statuses["git"] == "cancelled"
    assert statuses["nodejs"] == "not_started"

    # Same truthful statuses survive a fresh process reload.
    reloaded = _installer(tmp_path, status_rows=_status_rows(), recipes=recipes).get_job(
        job["id"], "op-1"
    )
    assert {d["id"]: d["status"] for d in reloaded["dependencies"]} == statuses

    # Dep lock released — a new install plan for git is not blocked.
    assert not installer._dep_locks["git"].locked()


@pytest.mark.asyncio
@pytest.mark.parametrize("preceding", ["completed", "reused"])
async def test_cancel_preserves_earlier_dep_status(tmp_path, preceding):
    """A cancelled job must not rewrite deps that already finished —
    completed/reused survives; only the held dep is cancelled."""
    entered = asyncio.Event()
    git_blob = _tar({"bin/git": b"#!"})
    git_dl = _download_for(git_blob)

    async def download(url, target, job, cancel):
        if job["current_dep"] == "git" and preceding == "completed":
            return await git_dl(url, target, job, cancel)
        entered.set()
        await asyncio.Future()
        return 0, hashlib.sha256(b"").hexdigest()

    if preceding == "completed":
        recipes = _with_blobs(_recipe_env(), git=git_blob, nodejs=b"")
        status_rows = _status_rows()
    else:  # git already ready via system — plan reuses it
        recipes = _with_blobs(_recipe_env(), nodejs=b"")
        status_rows = _status_rows(
            {2: {"status": "ready", "source": "system", "version": "2.53.0"}}
        )
    installer = _installer(tmp_path, download=download, status_rows=status_rows, recipes=recipes)
    plan = await installer.plan(["git", "nodejs"], "op-1")
    job = await installer.start(plan["id"], "op-1", True)
    await asyncio.wait_for(entered.wait(), timeout=5.0)

    await installer.cancel(job["id"], "op-1")
    task = installer._jobs[job["id"]]
    try:
        await asyncio.wait_for(task, timeout=10)
    except asyncio.CancelledError:
        pass
    # Second cancel is idempotent — still terminal, same statuses.
    await installer.cancel(job["id"], "op-1")

    final = installer.get_job(job["id"], "op-1")
    assert final["state"] == "cancelled"
    statuses = {d["id"]: d["status"] for d in final["dependencies"]}
    assert statuses["git"] == preceding  # untouched prior result
    assert statuses["nodejs"] == "cancelled"


async def test_http_transport_bounded_download(tmp_path):
    """MockTransport exercises the real httpx path — redirect chain,
    incremental progress persistence, checksum verify."""
    import httpx

    blob = _tar({"bin/git": b"#!"})

    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        if "redirect" in request.url.path:
            return httpx.Response(
                302,
                headers={"location": "https://release-assets.githubusercontent.com/real/git.tgz"},
            )
        return httpx.Response(200, content=blob)

    recipes = _with_blobs(_recipe_env(), git=blob)
    # Point the fixture URL at a redirect hop first.
    recipes["recipes"]["git"]["platforms"]["test-plat"]["url"] = (
        "https://github.com/redirect/git.tgz"
    )
    installer = _installer(
        tmp_path,
        status_rows=_status_rows(),
        recipes=recipes,
        http_transport=httpx.MockTransport(handler),
    )
    plan = await installer.plan(["git"], "op-1")
    job = await installer.start(plan["id"], "op-1", True)
    await asyncio.wait_for(installer._jobs[job["id"]], timeout=10)
    assert installer.get_job(job["id"], "op-1")["state"] == "completed"
    assert "github.com/redirect" in calls[0]
    assert any("release-assets" in c for c in calls)


async def test_http_blocked_host_and_port(tmp_path):

    installer = _installer(tmp_path, status_rows=_status_rows())
    with pytest.raises(PlanError) as e:
        installer._validate_url("http://github.com/x.tgz")
    assert e.value.status == 409
    with pytest.raises(PlanError):
        installer._validate_url("https://evil.com/x.tgz")
    with pytest.raises(PlanError):
        installer._validate_url("https://github.com:8080/x.tgz")
    with pytest.raises(PlanError):
        installer._validate_url("https://user:pw@github.com/x.tgz")


async def test_http_oversize_rejected(tmp_path):
    import httpx

    recipes = _with_blobs(_recipe_env(), git=b"x")
    installer = _installer(
        tmp_path,
        status_rows=_status_rows(),
        recipes=recipes,
        http_transport=httpx.MockTransport(
            lambda req: httpx.Response(
                200, content=b"x", headers={"content-length": str(300 * 1024 * 1024)}
            )
        ),
    )
    plan = await installer.plan(["git"], "op-1")
    job = await installer.start(plan["id"], "op-1", True)
    await asyncio.wait_for(installer._jobs[job["id"]], timeout=10)
    assert installer.get_job(job["id"], "op-1")["state"] == "failed"


# -- API seams ----------------------------------------------------------------


@pytest.fixture
def api_client(tmp_path, monkeypatch):
    import agentos.runtime_installer as ri
    from agentos.auth import require_operator
    from agentos.main import app

    installer = _installer(tmp_path, status_rows=_status_rows())
    monkeypatch.setattr(ri, "_INSTALLER", installer)

    async def mock_auth():
        return type("Op", (), {"id": "op-1", "username": "admin"})()

    prior = dict(app.dependency_overrides)
    app.dependency_overrides[require_operator] = mock_auth
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(prior)


def test_plan_install_flow_api(api_client):
    plan = api_client.post("/api/dependencies/plan", json={"dependency_ids": ["git"]}).json()
    assert plan["dependencies"][0]["action"] == "install"
    bad = api_client.post(
        "/api/dependencies/install", json={"plan_id": plan["id"], "consent": False}
    )
    assert bad.status_code == 422
    job = api_client.post(
        "/api/dependencies/install", json={"plan_id": plan["id"], "consent": True}
    ).json()
    assert job["id"]
    listed = api_client.get("/api/dependencies/jobs").json()["jobs"]
    assert any(j["id"] == job["id"] for j in listed)
    got = api_client.get(f"/api/dependencies/jobs/{job['id']}").json()
    assert got["id"] == job["id"]


def test_plan_extra_fields_rejected(api_client):
    resp = api_client.post(
        "/api/dependencies/plan",
        json={"dependency_ids": ["git"], "url": "https://evil.com"},
    )
    assert resp.status_code == 422


def test_job_owner_isolated(api_client):
    plan = api_client.post("/api/dependencies/plan", json={"dependency_ids": ["git"]}).json()
    job = api_client.post(
        "/api/dependencies/install", json={"plan_id": plan["id"], "consent": True}
    ).json()
    resp = api_client.get(f"/api/dependencies/jobs/{job['id']}")
    assert resp.status_code == 200
    import agentos.runtime_installer as ri

    with pytest.raises(PlanError):
        ri._INSTALLER.get_job(job["id"], "op-2")


def test_dependencies_api_unauthenticated_rejected(db_engine, monkeypatch, tmp_path):
    import agentos.dependencies as deps
    from agentos.db import get_db
    from agentos.main import app

    reg = RuntimeDependencyRegistry(
        data_dir=tmp_path / "rt",
        runner=None,
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
        resp = TestClient(app).post("/api/dependencies/plan", json={"dependency_ids": ["git"]})
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(prior)
    assert resp.status_code == 401


# -- final-batch contract cases -------------------------------------------------


async def test_dugite_dot_prefixed_layout(tmp_path):
    """The publisher's real tar layout ('./bin/git') must extract and
    health-verify — normalized member names in both passes."""

    def dugite(tf):
        for name in ("./", "./bin", "./libexec/git-core"):
            d = tarfile.TarInfo(name)
            d.type = tarfile.DIRTYPE
            tf.addfile(d)
        for name, body in (
            ("./bin/git", b"#!"),
            ("./libexec/git-core/git-remote-http", b"#!"),
            ("./COPYING", b"GPL-2.0"),
        ):
            ti = tarfile.TarInfo(name)
            ti.size = len(body)
            ti.mode = 0o755
            tf.addfile(ti, io.BytesIO(body))

    blob = _tar({}, extra=dugite)

    async def git_runner(argv, env):
        return 0, b"git version 2.53.0\n", b""

    recipes = _with_blobs(_recipe_env(), git=blob)
    reg = RuntimeDependencyRegistry(
        data_dir=tmp_path / "rt",
        runner=git_runner,
        finder=lambda c: None,
        platform_key="test-plat",
    )
    installer = RuntimeInstaller(
        registry=reg,
        data_dir=tmp_path / "rt",
        download=_download_for(blob),
        health_runner=git_runner,
        platform_key="test-plat",
        recipes=recipes,
    )
    plan = await installer.plan(["git"], "op-1")
    job = await installer.start(plan["id"], "op-1", True)
    await asyncio.wait_for(installer._jobs[job["id"]], timeout=10)
    assert installer.get_job(job["id"], "op-1")["state"] == "completed"
    # Registry health-verifies the managed git from the pointer.
    rows = await reg.status(force=True)
    git_row = next(r for r in rows if r["id"] == "git")
    assert git_row["status"] == "ready" and git_row["source"] == "managed"
    # Companions and notices survived the lift.
    version = (
        tmp_path
        / "rt"
        / "git"
        / json.loads((tmp_path / "rt" / "git" / "active.json").read_text())["directory"]
    )
    assert (version / "libexec" / "git-core" / "git-remote-http").is_file()
    assert (version / "COPYING").is_file()


async def test_staging_and_jobs_symlink_escape_rejected(tmp_path):
    """A symlinked .staging/jobs directory outside the root must fail
    before any open — nothing written outside the configured store."""
    outside = tmp_path / "outside"
    outside.mkdir()
    root = tmp_path / "rt"
    root.mkdir()
    (root / "jobs").symlink_to(outside / "jobs", target_is_directory=True)
    (outside / "jobs").mkdir()
    blob = _tar({"bin/git": b"#!"})
    installer = _installer(
        tmp_path,
        download=_download_for(blob),
        status_rows=_status_rows(),
        recipes=_with_blobs(_recipe_env(), git=blob),
    )
    # _jobs_dir resolves jobs/ → outside root? _owned_path protects writes.
    # The plan+start path surfaces the escape instead of writing through it.
    plan = await installer.plan(["git"], "op-1")
    try:
        job = await installer.start(plan["id"], "op-1", True)
        await asyncio.wait_for(installer._jobs[job["id"]], timeout=10)
        final = installer.get_job(job["id"], "op-1")
        assert final["state"] in ("failed", "cancelled", "interrupted")
    except PlanError:
        pass  # rejected outright is also correct
    # Whatever happened — nothing landed in the escape target.
    assert not (outside / "jobs").exists() or not any((outside / "jobs").glob("*.json"))


async def test_bundle_mutates_during_status_then_fresh_plan(tmp_path):
    """Plan snapshots the bundle BEFORE the status await — a mid-plan
    mutation must fail start (old plan) but a fresh plan succeeds."""
    blob = _tar({"bin/git": b"#!/git"})
    rec = _with_blobs(_recipe_env(), git=blob)
    reg = RuntimeDependencyRegistry(
        data_dir=tmp_path / "rt",
        runner=_healthy_runner,
        finder=lambda c: None,
        platform_key="test-plat",
    )
    mutated = {"done": False}

    async def slow_status(force=False):
        if not mutated["done"]:
            rec["recipes"]["git"]["version"] = "9.9.9"
            mutated["done"] = True
        return _status_rows()

    reg.status = slow_status
    installer = RuntimeInstaller(
        registry=reg,
        data_dir=tmp_path / "rt",
        download=_download_for(blob),
        health_runner=_healthy_runner,
        platform_key="test-plat",
        recipes=rec,
    )
    plan = await installer.plan(["git"], "op-1")
    with pytest.raises(PlanError) as e:
        await installer.start(plan["id"], "op-1", True)
    assert e.value.status == 409
    plan2 = await installer.plan(["git"], "op-1")
    assert plan2["dependencies"][0]["version"] == "9.9.9"


async def test_mcp_uvx_child_env_carries_git_dir(tmp_path, monkeypatch):
    """uvx launch gets the managed uv bin AND git bin on the child PATH —
    nested spawns (uvx → python/git) resolve in one environment."""
    import agentos.mcp.client as client

    uv_bin = tmp_path / "rt" / "uv" / "v" / "bin"
    git_bin = tmp_path / "rt" / "git" / "v" / "bin"
    for d, name in ((uv_bin, "uvx"), (uv_bin, "uv"), (git_bin, "git")):
        f = d / name
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("#!")
        f.chmod(0o755)
    paths = {"uv": str(uv_bin / "uv"), "uvx": str(uv_bin / "uvx"), "git": str(git_bin / "git")}
    reg = _mcp_verified_registry(tmp_path, paths)
    monkeypatch.setattr(client, "_registry_or_none", lambda: reg)
    capture: dict = {}
    _install_fake_mcp(monkeypatch, capture)
    c = client.McpClient(
        transport="stdio",
        command="uvx",
        args=["pkg"],
        env={"UV_TOKEN": "s3cr3t", "PATH": str(uv_bin)},
    )
    await c.connect()
    env = capture["params"].env
    parts = env["PATH"].split(":")
    assert parts[0] == str(uv_bin)  # explicit caller dir wins
    assert str(git_bin) in parts  # managed companion dir merged
    assert env["UV_TOKEN"] == "s3cr3t"
    await c.disconnect()


async def test_mcp_unready_known_command_blocked(tmp_path, monkeypatch):
    """A known bare command with no verified install and no explicit
    caller PATH must fail BEFORE stdio_client — never Node-20 fallback."""
    import agentos.mcp.client as client

    reg = _mcp_verified_registry(tmp_path, {})  # nothing verified

    async def _status(force=False):
        return []

    reg.status = _status
    monkeypatch.setattr(client, "_registry_or_none", lambda: reg)
    capture: dict = {}
    _install_fake_mcp(monkeypatch, capture)
    monkeypatch.setenv("PATH", "/nonexistent")  # nothing on PATH either
    c = client.McpClient(transport="stdio", command="node", args=["srv"], env={})
    with pytest.raises(RuntimeError, match="verified|Prepare"):
        await c.connect()
    assert "params" not in capture


def _mcp_verified_registry(tmp_path, paths):
    from agentos.dependencies import RuntimeDependencyRegistry

    async def runner(argv, env):
        return 0, b"2.53.0\n", b""

    reg = RuntimeDependencyRegistry(
        data_dir=tmp_path / "rt",
        runner=runner,
        finder=lambda c: None,
        platform_key="test-plat",
    )

    async def _status(force=False):
        return []

    reg.status = _status
    reg._last_paths = dict(paths)
    return reg


async def test_windows_npx_wrapper_strict(monkeypatch, tmp_path):
    """Invalid wrapper combos must raise before the SDK — never a native
    .cmd launch and never a foreign node.exe."""
    from agentos.mcp.client import McpClient

    install = tmp_path / "node"
    install.mkdir()
    (install / "npx.cmd").write_text("x")
    (install / "node.exe").write_text("x")
    # Missing cli.js → must raise. (No sibling node.exe yet, so the
    # co-installed preference can't mask the bad script.)
    (install / "node.exe").unlink()
    reg = _mcp_verified_registry(tmp_path, {"node": str(install / "node.exe")})
    with pytest.raises(RuntimeError, match="cli.js|Cannot launch"):
        McpClient._windows_wrapper_argv("npx", str(install / "npx.cmd"), ["pkg"], reg)
    # Foreign node (different parent, no sibling node.exe) → raise.
    other = tmp_path / "other"
    other.mkdir()
    (other / "node.exe").write_text("x")
    (install / "node_modules" / "npm" / "bin").mkdir(parents=True)
    (install / "node_modules" / "npm" / "bin" / "npx-cli.js").write_text("x")
    reg2 = _mcp_verified_registry(tmp_path, {"node": str(other / "node.exe")})
    with pytest.raises(RuntimeError):
        McpClient._windows_wrapper_argv("npx", str(install / "npx.cmd"), ["pkg"], reg2)
    # Valid → co-installed node.exe + cli.js argv, args preserved.
    (install / "node.exe").write_text("x")
    reg3 = _mcp_verified_registry(tmp_path, {"node": str(install / "node.exe")})
    cmd, args = McpClient._windows_wrapper_argv("npx", str(install / "npx.cmd"), ["pkg"], reg3)
    assert cmd == str((install / "node.exe").resolve())
    assert args[0].endswith("npx-cli.js") and args[1] == "pkg"


async def test_oversized_malformed_pointer_reconcile(tmp_path):
    """A job file over the cap or with a malformed dep shape is skipped —
    reconcile never reads unbounded bytes."""
    root = tmp_path / "rt"
    (root / "jobs").mkdir(parents=True)
    (root / "jobs" / ("b" * 32 + ".json")).write_text(
        json.dumps(
            {
                "id": "b" * 32,
                "operator_id": "op",
                "state": "downloading",
                "dependencies": [{"id": "../escape", "action": "install"}],
            }
        )
    )
    (root / "jobs" / ("c" * 32 + ".json")).write_text(
        json.dumps(
            {
                "id": "c" * 32,
                "operator_id": "op",
                "state": "downloading",
                "dependencies": [{"id": "git", "action": "install"}],
                "padding": "x" * 90000,
            }
        )
    )
    installer = _installer(tmp_path)
    # Both skipped as malformed/oversized — no crash, no unbounded read.
    assert installer._load_job("b" * 32) is None
    assert installer._load_job("c" * 32) is None


async def test_public_plan_mutation_cannot_alter_job_plan(tmp_path):
    """Mutating the returned public plan dict must not change the frozen
    snapshot persisted on the job."""
    blob = _tar({"bin/git": b"#!/git"})
    installer = _installer(
        tmp_path,
        download=_download_for(blob),
        status_rows=_status_rows(),
        recipes=_with_blobs(_recipe_env(), git=blob),
    )
    plan = await installer.plan(["git"], "op-1")
    job = await installer.start(plan["id"], "op-1", True)
    await asyncio.wait_for(installer._jobs[job["id"]], timeout=10)
    plan["dependencies"][0]["version"] = "HACKED"
    plan["dependencies"][0]["sha256"] = "f" * 64
    final = installer.get_job(job["id"], "op-1")
    assert final["plan"]["dependencies"][0]["version"] == "2.53.0"


async def test_windows_explicit_npx_connect(tmp_path, monkeypatch):
    """Explicit Windows PATH with npx.cmd + co-installed node.exe + own
    cli.js → real connect captures node.exe + cli.js argv, original args
    preserved, no foreign registry node."""
    import platform as _platform

    import agentos.mcp.client as client

    install = tmp_path / "node"
    (install / "node_modules" / "npm" / "bin").mkdir(parents=True)
    (install / "node_modules" / "npm" / "bin" / "npx-cli.js").write_text("x")
    (install / "npx.cmd").write_text("x")
    (install / "npx.cmd").chmod(0o755)
    (install / "node.exe").write_text("x")
    (install / "node.exe").chmod(0o755)
    monkeypatch.setattr(_platform, "system", lambda: "Windows")
    reg = _mcp_verified_registry(tmp_path, {})  # no registry node at all
    monkeypatch.setattr(client, "_registry_or_none", lambda: reg)
    capture: dict = {}
    _install_fake_mcp(monkeypatch, capture)
    c = client.McpClient(
        transport="stdio",
        command="npx",
        args=["mcp-srv", "--flag"],
        env={"PATH": str(install)},
    )
    await c.connect()
    params = capture["params"]
    assert params.command == str((install / "node.exe").resolve())
    assert params.args[0].endswith("npx-cli.js")
    assert params.args[1:] == ["mcp-srv", "--flag"]
    await c.disconnect()


def test_jobs_route_real_orm_operator(db_engine, tmp_path, monkeypatch):
    """The jobs route must use the ORM Operator instance — never dict
    subscripting. Regression for the 500 'Operator is not subscriptable'."""
    import agentos.runtime_installer as ri
    from agentos.auth import require_operator
    from agentos.db import get_db
    from agentos.main import app
    from agentos.models.operator import Operator

    installer = _installer(tmp_path, status_rows=_status_rows())
    monkeypatch.setattr(ri, "_INSTALLER", installer)
    op = Operator(id="op-orm-1", username="admin", password_hash="x")
    factory = async_sessionmaker(db_engine, expire_on_commit=False)

    async def fake_auth():
        return op

    async def get_test_db():
        async with factory() as session:
            yield session

    prior = dict(app.dependency_overrides)
    app.dependency_overrides[require_operator] = fake_auth
    app.dependency_overrides[get_db] = get_test_db
    try:
        resp = TestClient(app).get("/api/dependencies/jobs")
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(prior)
    assert resp.status_code == 200
    assert resp.json()["jobs"] == []
