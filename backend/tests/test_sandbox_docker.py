"""Test the Docker sandbox backend."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agentos.sandbox.docker import DockerBackend


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


def test_image_pulled_when_not_already_present():
    """If the sandbox image isn't cached locally, is_available() pulls it
    during the probe rather than deferring that cost to the first command."""
    inspect_missing = MagicMock(returncode=1)
    pull_ok = MagicMock(returncode=0)
    version_ok = MagicMock(returncode=0)

    calls = []

    def fake_run(args, **kwargs):
        calls.append(args)
        if args[1] == "version":
            return version_ok
        if args[1:3] == ["image", "inspect"]:
            return inspect_missing
        if args[1] == "pull":
            return pull_ok
        raise AssertionError(f"unexpected docker subcommand: {args}")

    with (
        patch("agentos.sandbox.docker.shutil.which", return_value="/usr/bin/docker"),
        patch("agentos.sandbox.docker.subprocess.run", side_effect=fake_run),
    ):
        backend = DockerBackend()
        assert backend.is_available() is True

    assert any(c[1] == "pull" for c in calls), "expected a docker pull when the image was missing"


def test_unavailable_when_image_pull_fails():
    version_ok = MagicMock(returncode=0)
    inspect_missing = MagicMock(returncode=1)
    pull_failed = MagicMock(returncode=1)

    def fake_run(args, **kwargs):
        if args[1] == "version":
            return version_ok
        if args[1:3] == ["image", "inspect"]:
            return inspect_missing
        if args[1] == "pull":
            return pull_failed
        raise AssertionError(f"unexpected docker subcommand: {args}")

    with (
        patch("agentos.sandbox.docker.shutil.which", return_value="/usr/bin/docker"),
        patch("agentos.sandbox.docker.subprocess.run", side_effect=fake_run),
    ):
        backend = DockerBackend()
        assert backend.is_available() is False
        assert "could not be pulled" in (backend.unavailable_reason() or "")


@pytest.mark.asyncio
async def test_run_command_builds_expected_argv(tmp_path):
    captured = {}

    async def fake_create_subprocess_exec(*args, **kwargs):
        captured["args"] = args
        proc = AsyncMock()
        proc.communicate = AsyncMock(return_value=(b"hello\n", b""))
        proc.returncode = 0
        return proc

    with patch("asyncio.create_subprocess_exec", side_effect=fake_create_subprocess_exec):
        backend = DockerBackend()
        result = await backend.run_command(str(tmp_path), "echo hello")

    assert result.exit_code == 0
    assert result.stdout == "hello\n"
    args = captured["args"]
    assert args[0:2] == ("docker", "run")
    assert "--rm" in args
    assert "--network" in args and "none" in args
    assert "-v" in args
    mount_arg = args[args.index("-v") + 1]
    assert mount_arg.endswith(":/workspace")
    assert args[-4:] == ("alpine:3.20", "/bin/sh", "-c", "echo hello")


@pytest.mark.asyncio
async def test_run_command_allows_network_when_requested(tmp_path):
    captured = {}

    async def fake_create_subprocess_exec(*args, **kwargs):
        captured["args"] = args
        proc = AsyncMock()
        proc.communicate = AsyncMock(return_value=(b"", b""))
        proc.returncode = 0
        return proc

    with patch("asyncio.create_subprocess_exec", side_effect=fake_create_subprocess_exec):
        backend = DockerBackend()
        await backend.run_command(str(tmp_path), "true", allow_network=True)

    assert "--network" not in captured["args"]


@pytest.mark.asyncio
async def test_timeout_kills_the_container(tmp_path):
    """A timed-out command must stop the container, not just the local
    `docker run` client process."""
    docker_calls = []

    async def fake_create_subprocess_exec(*args, **kwargs):
        docker_calls.append(args)
        proc = AsyncMock()
        if args[0:2] == ("docker", "kill"):
            proc.wait = AsyncMock(return_value=0)
        else:
            # The `docker run` call — never completes before the timeout.
            async def hang():
                import asyncio as _asyncio

                await _asyncio.sleep(10)
                return (b"", b"")

            proc.communicate = hang
            proc.returncode = None
            proc.kill = MagicMock()
            proc.wait = AsyncMock(return_value=0)
        return proc

    with patch("asyncio.create_subprocess_exec", side_effect=fake_create_subprocess_exec):
        backend = DockerBackend()
        result = await backend.run_command(str(tmp_path), "sleep 30", timeout=0.05)

    assert result.exit_code == -1
    assert "timed out" in result.stderr
    kill_calls = [c for c in docker_calls if c[0:2] == ("docker", "kill")]
    assert kill_calls, "expected `docker kill <container>` to be invoked on timeout"
