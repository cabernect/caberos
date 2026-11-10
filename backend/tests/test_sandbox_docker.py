"""Test the Docker sandbox backend."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agentos.sandbox.base import SandboxLaunch
from agentos.sandbox.docker import DockerBackend
from tests.process_fakes import FakeProcess


@pytest.fixture(autouse=True)
def _clear_probe_cache():
    DockerBackend._probe_cache = None
    yield
    DockerBackend._probe_cache = None


def test_unavailable_when_docker_not_on_path():
    with patch("agentos.sandbox.docker.shutil.which", return_value=None):
        backend = DockerBackend()
        assert backend.is_available() is False
        assert "not installed" in (backend.unavailable_reason() or "")


def test_unavailable_when_daemon_not_responding():
    with (
        patch("agentos.sandbox.docker.shutil.which", return_value="/usr/bin/docker"),
        patch("agentos.sandbox.docker.subprocess.run", side_effect=OSError("no daemon")),
    ):
        backend = DockerBackend()
        assert backend.is_available() is False
        assert "daemon" in (backend.unavailable_reason() or "")


def test_available_when_daemon_responds():
    completed = MagicMock(returncode=0)
    with (
        patch("agentos.sandbox.docker.shutil.which", return_value="/usr/bin/docker"),
        patch("agentos.sandbox.docker.subprocess.run", return_value=completed),
    ):
        backend = DockerBackend()
        assert backend.is_available() is True
        assert backend.unavailable_reason() is None


def test_probe_result_is_cached_per_instance():
    """is_available() does two subprocess.run calls internally (version check
    + image presence check) on a fresh probe, but a second call must add zero
    more — the result is cached on the instance, not re-probed."""
    completed = MagicMock(returncode=0)
    with (
        patch("agentos.sandbox.docker.shutil.which", return_value="/usr/bin/docker"),
        patch("agentos.sandbox.docker.subprocess.run", return_value=completed) as run,
    ):
        backend = DockerBackend()
        backend.is_available()
        calls_after_first_probe = run.call_count
        backend.is_available()
    assert run.call_count == calls_after_first_probe


def test_missing_image_refuses_without_downloading():
    """A readiness probe must not acquire network/download authority."""
    inspect_missing = MagicMock(returncode=1)
    version_ok = MagicMock(returncode=0)

    calls = []

    def fake_run(args, **kwargs):
        calls.append(args)
        if args[1] == "version":
            return version_ok
        if args[1:3] == ["image", "inspect"]:
            return inspect_missing
        raise AssertionError(f"unexpected docker subcommand: {args}")

    with (
        patch("agentos.sandbox.docker.shutil.which", return_value="/usr/bin/docker"),
        patch("agentos.sandbox.docker.subprocess.run", side_effect=fake_run),
    ):
        backend = DockerBackend()
        assert backend.is_available() is False
        reason = backend.unavailable_reason() or ""
        assert "docker pull alpine:3.20" in reason
        assert "does not download" in reason
        assert backend.needs_host_setup() is False

    assert [c[1:3] for c in calls] == [
        ["version", "--format"],
        ["image", "inspect"],
    ]


def test_unavailable_when_image_inspection_fails():
    version_ok = MagicMock(returncode=0)
    inspect_missing = MagicMock(returncode=1)

    def fake_run(args, **kwargs):
        if args[1] == "version":
            return version_ok
        if args[1:3] == ["image", "inspect"]:
            return inspect_missing
        raise AssertionError(f"unexpected docker subcommand: {args}")

    with (
        patch("agentos.sandbox.docker.shutil.which", return_value="/usr/bin/docker"),
        patch("agentos.sandbox.docker.subprocess.run", side_effect=fake_run),
    ):
        backend = DockerBackend()
        assert backend.is_available() is False
        assert "missing or cannot be inspected" in (backend.unavailable_reason() or "")


def test_image_inspection_error_does_not_attempt_install():
    calls = []

    def fake_run(args, **kwargs):
        calls.append(args)
        if args[1] == "version":
            return MagicMock(returncode=0)
        raise OSError("local image inspection failed")

    with (
        patch("agentos.sandbox.docker.shutil.which", return_value="/usr/bin/docker"),
        patch("agentos.sandbox.docker.subprocess.run", side_effect=fake_run),
    ):
        backend = DockerBackend()
        assert backend.is_available() is False
        assert "does not download" in (backend.unavailable_reason() or "")
    assert len(calls) == 2
    assert calls[-1][1:3] == ["image", "inspect"]


def test_background_spawn_cannot_implicitly_pull_image():
    args = DockerBackend().spawn_argv("/workspace", "echo hello")
    assert args[:3] == ["docker", "run", "--pull=never"]
    assert "--network" in args and "none" in args


@pytest.mark.asyncio
async def test_run_command_builds_expected_argv(tmp_path):
    captured = {}

    async def fake_create_subprocess_exec(*args, **kwargs):
        captured["args"] = args
        return FakeProcess(b"hello\n")

    with patch("asyncio.create_subprocess_exec", side_effect=fake_create_subprocess_exec):
        backend = DockerBackend()
        result = await backend.run_command(str(tmp_path), "echo hello")

    assert result.exit_code == 0
    assert result.stdout == "hello\n"
    args = captured["args"]
    assert args[0:2] == ("docker", "run")
    assert "--pull=never" in args
    assert "--rm" in args
    assert "--network" in args and "none" in args
    assert "-v" in args
    mount_arg = args[args.index("-v") + 1]
    assert mount_arg.endswith(":/workspace")
    assert args[-4:] == ("alpine:3.20", "/bin/sh", "-c", "echo hello")
    assert "-e" in args and args[args.index("-e") + 1] == "HOME=/workspace"


@pytest.mark.asyncio
async def test_run_command_allows_network_when_requested(tmp_path):
    captured = {}

    async def fake_create_subprocess_exec(*args, **kwargs):
        captured["args"] = args
        return FakeProcess()

    with patch("asyncio.create_subprocess_exec", side_effect=fake_create_subprocess_exec):
        backend = DockerBackend()
        await backend.run_command(str(tmp_path), "true", allow_network=True)

    assert "--network" not in captured["args"]
    assert "--pull=never" in captured["args"]


@pytest.mark.asyncio
async def test_timeout_kills_the_container(tmp_path):
    """A timed-out command must stop the container, not just the local
    `docker run` client process."""
    docker_calls = []

    async def fake_create_subprocess_exec(*args, **kwargs):
        docker_calls.append(args)
        if args[0:2] == ("docker", "kill"):
            return FakeProcess()
        return FakeProcess(hang=True)

    with patch("asyncio.create_subprocess_exec", side_effect=fake_create_subprocess_exec):
        backend = DockerBackend()
        result = await backend.run_command(str(tmp_path), "sleep 30", timeout=0.05)

    assert result.exit_code == -1
    assert "timed out" in result.stderr
    kill_calls = [c for c in docker_calls if c[0:2] == ("docker", "kill")]
    assert kill_calls, "expected `docker kill <container>` to be invoked on timeout"


async def test_background_prepares_resource_before_attaching(tmp_path):
    backend = DockerBackend()
    with patch.object(backend, "_control", AsyncMock(return_value=b"a" * 64)) as control:
        launch = await backend.prepare_launch(str(tmp_path), "echo --name not-the-resource")
    args = control.call_args.args
    assert args[0] == "create"
    assert "--pull=never" in args
    assert "--rm" not in args
    assert launch.argv == ["docker", "start", "--attach", launch.resource_id]
    assert args[args.index("--name") + 1] == launch.resource_id
    assert f"io.caberos.sandbox={launch.resource_id}" in args


async def test_failed_resource_creation_attempts_cleanup(tmp_path):
    backend = DockerBackend()
    with (
        patch.object(backend, "_control", AsyncMock(side_effect=RuntimeError("dummy failure"))),
        patch.object(backend, "cleanup_launch", AsyncMock(return_value=False)) as cleanup,
    ):
        with pytest.raises(RuntimeError, match="dummy failure"):
            await backend.prepare_launch(str(tmp_path), "true")
    cleanup.assert_awaited_once()


async def test_cleanup_requires_matching_ownership_label():
    name = "caberos-sandbox-" + "a" * 32
    backend = DockerBackend()
    with patch.object(backend, "_control", AsyncMock(return_value=b"someone-else")) as control:
        confirmed = await backend.cleanup_launch(SandboxLaunch([], None, name), None)
    assert confirmed is False
    assert control.await_count == 1
    assert control.call_args.args[0] == "inspect"


async def test_cleanup_removes_only_the_captured_owned_resource():
    name = "caberos-sandbox-" + "a" * 32
    backend = DockerBackend()
    with patch.object(
        backend, "_control", AsyncMock(side_effect=[name.encode(), name.encode()])
    ) as control:
        confirmed = await backend.cleanup_launch(SandboxLaunch([], None, name), None)
    assert confirmed is True
    assert control.call_args.args == ("rm", "--force", name)


@pytest.mark.parametrize("identity", [None, "other-container", "--all"])
async def test_invalid_cleanup_identity_never_reaches_docker(identity):
    backend = DockerBackend()
    with patch.object(backend, "_control", AsyncMock()) as control:
        confirmed = await backend.cleanup_launch(SandboxLaunch([], None, identity), None)
    assert confirmed is False
    control.assert_not_awaited()


@pytest.mark.parametrize("remaining", [b"", b"existing-container"])
async def test_failed_inspect_needs_separate_absence_evidence(remaining):
    name = "caberos-sandbox-" + "a" * 32
    backend = DockerBackend()
    with patch.object(
        backend, "_control", AsyncMock(side_effect=[RuntimeError("inspect failed"), remaining])
    ) as control:
        confirmed = await backend.cleanup_launch(SandboxLaunch([], None, name), None)
    assert confirmed is (remaining == b"")
    assert control.call_args.args == (
        "ps",
        "--all",
        "--filter",
        f"name=^/{name}$",
        "--format",
        "{{.ID}}",
    )


async def test_daemon_disconnect_never_claims_resource_stopped():
    name = "caberos-sandbox-" + "a" * 32
    backend = DockerBackend()
    with patch.object(backend, "_control", AsyncMock(side_effect=OSError("offline"))):
        confirmed = await backend.cleanup_launch(SandboxLaunch([], None, name), None)
    assert confirmed is False


def test_container_limits_apply_even_when_network_is_authorized(tmp_path):
    backend = DockerBackend()
    for network in (False, True):
        args = backend.spawn_argv(str(tmp_path), "true", allow_network=network)
        assert {
            "--pull=never",
            "--cap-drop=ALL",
            "--security-opt=no-new-privileges",
            "--read-only",
            "--pids-limit=64",
            "--memory=256m",
            "--memory-swap=256m",
            "--cpus=1",
        }.issubset(args)
        assert args[args.index("--tmpfs") + 1] == "/tmp:rw,nosuid,nodev,noexec,size=32m,mode=1777"
        assert "nofile=256:256" in args
        assert "fsize=67108864:67108864" in args
        assert "--privileged" not in args


def test_root_controller_never_selects_root_container_user(tmp_path, monkeypatch):
    monkeypatch.setattr("agentos.sandbox.docker.os.getuid", lambda: 0, raising=False)
    monkeypatch.setattr("agentos.sandbox.docker.os.getgid", lambda: 0, raising=False)
    args = DockerBackend().spawn_argv(str(tmp_path), "true")
    assert args[args.index("--user") + 1] == "65534:65534"
