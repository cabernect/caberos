"""bubblewrap readiness and launch contracts with synthetic subprocesses only."""

from pathlib import Path
from unittest.mock import AsyncMock, Mock

import pytest

from agentos.sandbox.bwrap import BwrapBackend
from tests.process_fakes import FakeProcess


def test_readiness_uses_real_mounts_and_checks_its_workspace(monkeypatch):
    calls = []
    monkeypatch.setattr("agentos.sandbox.bwrap.shutil.which", lambda name: "/synthetic/bwrap")

    def confined(args, **kwargs):
        calls.append(args)
        workspace = Path(kwargs["env"]["HOME"])
        (workspace / "inside").write_text("ok")
        assert args == BwrapBackend().spawn_argv(str(workspace), args[-1])
        assert "--ro-bind" in args and "/usr" in args
        assert "--unshare-all" in args and "--share-net" not in args
        assert kwargs["timeout"] == 5
        return Mock(returncode=0, stdout=b"bwrap-ready")

    monkeypatch.setattr("agentos.sandbox.bwrap.subprocess.run", confined)
    backend = BwrapBackend()
    assert backend.is_available()
    assert backend.is_available()
    assert backend.unavailable_reason() is None
    assert len(calls) == 1


@pytest.mark.parametrize(
    "failure", ["status", "missing-write", "outside-write", "launch", "marker"]
)
def test_readiness_fails_closed_without_an_unconfined_retry(monkeypatch, failure):
    monkeypatch.setattr("agentos.sandbox.bwrap.shutil.which", lambda name: "/synthetic/bwrap")

    def rejected(args, **kwargs):
        if failure == "launch":
            raise OSError("synthetic launch failure")
        workspace = Path(kwargs["env"]["HOME"])
        if failure != "missing-write":
            (workspace / "inside").write_text("ok")
        if failure == "outside-write":
            (workspace.parent / "synthetic-sibling").write_text("changed")
        return Mock(
            returncode=7 if failure == "status" else 0,
            stdout=b"wrong" if failure == "marker" else b"bwrap-ready",
        )

    run = Mock(side_effect=rejected)
    monkeypatch.setattr("agentos.sandbox.bwrap.subprocess.run", run)
    backend = BwrapBackend()
    assert backend.is_available() is False
    assert "self-check failed" in backend.unavailable_reason()
    assert run.call_count == 1


def test_missing_binary_does_not_launch_any_probe(monkeypatch):
    monkeypatch.setattr("agentos.sandbox.bwrap.shutil.which", lambda name: None)
    run = Mock()
    monkeypatch.setattr("agentos.sandbox.bwrap.subprocess.run", run)
    backend = BwrapBackend()
    assert backend.is_available() is False
    assert "not installed" in backend.unavailable_reason()
    run.assert_not_called()


def test_optional_library_mounts_do_not_require_x86_lib64(tmp_path):
    args = BwrapBackend().spawn_argv(str(tmp_path), "true")
    assert args[args.index("/lib64") - 1] == "--ro-bind-try"
    assert args[args.index("/lib") - 1] == "--ro-bind-try"


async def test_sync_and_background_launch_share_an_allowlisted_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("CABEROS_SYNTHETIC_SECRET", "dummy-not-a-real-secret")
    backend = BwrapBackend()
    spawn = AsyncMock(return_value=FakeProcess(b"ok"))
    monkeypatch.setattr("agentos.sandbox.bwrap.asyncio.create_subprocess_exec", spawn)
    result = await backend.run_command(str(tmp_path), "echo ok")
    assert result.stdout == "ok"
    assert spawn.call_args.kwargs["env"] == backend.spawn_env(str(tmp_path))
    assert "CABEROS_SYNTHETIC_SECRET" not in spawn.call_args.kwargs["env"]
    assert spawn.call_args.kwargs["start_new_session"] is True
