"""Seatbelt policy construction and opt-in native confinement checks.

Native checks use synthetic sibling files only. Run them only inside the
isolated security-test environment described in the W7 plan.
"""

import os
import shlex
import shutil
import sys
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from agentos.sandbox.seatbelt import SeatbeltBackend, _build_profile
from tests.process_fakes import FakeProcess

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="Seatbelt profiles use POSIX paths")


def test_profile_denies_private_trees_and_confines_writes(tmp_path):
    profile = _build_profile(str(tmp_path), False)
    assert "(deny default)" in profile
    # Runtime needs broad read/exec; confinement is layered denies.
    assert "(allow file-read*)" in profile
    assert "(allow process-exec*)" in profile
    assert "(deny file-write*)" in profile
    for denied in ("/Users", "/private/var/folders", "/private/tmp"):
        assert f'(deny file-read* (subpath "{denied}"))' in profile
    resolved = str(tmp_path.resolve())
    assert f'(allow file-read* (subpath "{resolved}"))' in profile
    assert f'(allow file-write* (subpath "{resolved}"))' in profile
    assert '(allow file-write* (literal "/dev/null"))' in profile
    assert "(allow network*)" not in profile
    # The workspace re-allow must come after the private denies.
    assert profile.index("(deny file-read*") < profile.index(
        '(allow file-read* (subpath "' + resolved
    )


def test_network_opt_in_does_not_widen_file_access(tmp_path):
    denied = _build_profile(str(tmp_path), False)
    allowed = _build_profile(str(tmp_path), True)
    assert allowed == denied + "\n(allow network*)"


def test_workspace_quotes_and_backslashes_are_escaped(tmp_path):
    workspace = tmp_path / 'a "quote" and \\slash'
    escaped = str(workspace.resolve()).replace("\\", "\\\\").replace('"', '\\"')
    profile = _build_profile(str(workspace), False)
    assert f'(allow file-read* (subpath "{escaped}"))' in profile
    assert f'(allow file-write* (subpath "{escaped}"))' in profile


@pytest.mark.parametrize("suffix", ["\n", "\r", "\t", "\x7f"])
def test_workspace_control_characters_are_rejected(tmp_path, suffix):
    with pytest.raises(ValueError, match="control characters"):
        _build_profile(str(tmp_path / ("workspace" + suffix)), False)


def test_machine_root_and_home_ancestors_are_rejected(tmp_path):
    home = tmp_path / "operator"
    with patch("agentos.sandbox.seatbelt.Path.home", return_value=home):
        for workspace in (Path("/"), tmp_path, home):
            with pytest.raises(ValueError, match="narrower than the home"):
                _build_profile(str(workspace), False)


@pytest.mark.parametrize("workspace", ["/private/var/folders", "/private/var", "/private"])
def test_private_deny_root_ancestors_are_rejected(workspace):
    with pytest.raises(ValueError, match="private deny root"):
        _build_profile(workspace, False)


def test_environment_has_workspace_home_and_temp_without_host_secrets(tmp_path, monkeypatch):
    monkeypatch.setenv("CABEROS_TEST_SECRET", "dummy-not-for-child")
    monkeypatch.setenv("SSH_AUTH_SOCK", "/dummy/operator-agent")
    monkeypatch.setenv("TMPDIR", "/dummy/shared-temp")
    env = SeatbeltBackend().spawn_env(str(tmp_path))
    root = str(tmp_path.resolve())
    assert env == {
        "PATH": "/usr/bin:/bin",
        "HOME": root,
        "TMPDIR": root,
        "TMP": root,
        "TEMP": root,
    }


def test_readiness_requires_successful_confinement_and_is_cached():
    def confined_result(*args, **kwargs):
        workspace = Path(kwargs["cwd"])
        (workspace / "inside").write_text("ok")
        assert kwargs["env"] == SeatbeltBackend().spawn_env(str(workspace))
        assert kwargs["timeout"] == 5
        return Mock(returncode=0, stdout=b"seatbelt-ready")

    with (
        patch("agentos.sandbox.seatbelt.shutil.which", return_value="/usr/bin/sandbox-exec"),
        patch("agentos.sandbox.seatbelt.subprocess.run", side_effect=confined_result) as run,
    ):
        backend = SeatbeltBackend()
        assert backend.is_available() is True
        assert backend.is_available() is True
        assert backend.unavailable_reason() is None
    assert run.call_count == 1


@pytest.mark.parametrize("failure", ["launch", "status", "missing-write", "outside-write"])
def test_readiness_fails_closed_without_a_permissive_retry(failure):
    def failed_result(*args, **kwargs):
        if failure == "launch":
            raise OSError("synthetic launch failure")
        workspace = Path(kwargs["cwd"])
        if failure == "outside-write":
            (workspace / "inside").write_text("ok")
            (workspace.parent / "synthetic-sibling").write_text("changed")
        return Mock(returncode=1 if failure == "status" else 0, stdout=b"seatbelt-ready")

    with (
        patch("agentos.sandbox.seatbelt.shutil.which", return_value="/usr/bin/sandbox-exec"),
        patch("agentos.sandbox.seatbelt.subprocess.run", side_effect=failed_result) as run,
    ):
        backend = SeatbeltBackend()
        assert backend.is_available() is False
        assert "confinement self-check failed" in backend.unavailable_reason()
    assert run.call_count == 1


def test_missing_seatbelt_does_not_launch_a_probe():
    with (
        patch("agentos.sandbox.seatbelt.shutil.which", return_value=None),
        patch("agentos.sandbox.seatbelt.subprocess.run") as run,
    ):
        backend = SeatbeltBackend()
        assert backend.is_available() is False
        assert "not on PATH" in backend.unavailable_reason()
    run.assert_not_called()


async def test_sync_and_background_use_the_same_profile_and_environment(tmp_path):
    backend = SeatbeltBackend()
    process = FakeProcess(b"ok")
    with patch(
        "agentos.sandbox.seatbelt.asyncio.create_subprocess_exec", return_value=process
    ) as spawn:
        result = await backend.run_command(str(tmp_path), "echo ok")
    assert result.exit_code == 0
    assert result.stdout == "ok"
    assert spawn.call_args.args == tuple(backend.spawn_argv(str(tmp_path), "echo ok"))
    assert spawn.call_args.kwargs["env"] == backend.spawn_env(str(tmp_path))
    assert spawn.call_args.kwargs["cwd"] == str(tmp_path.resolve())
    assert spawn.call_args.kwargs["start_new_session"] is True


native = pytest.mark.skipif(
    sys.platform != "darwin"
    or shutil.which("sandbox-exec") is None
    or os.environ.get("CABEROS_TEST_SEATBELT_LIVE") != "1",
    reason="requires opt-in isolated macOS security-test runner",
)


@native
async def test_native_workspace_read_write_and_workspace_temp(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    result = await SeatbeltBackend().run_command(
        str(workspace),
        'printf ok > allowed && /bin/cat allowed && /usr/bin/mktemp "$TMPDIR/seatbelt.XXXXXX"',
        timeout=5,
    )
    assert result.exit_code == 0, result.stderr
    assert result.stdout.startswith("ok")
    assert all(p.is_relative_to(workspace) for p in workspace.iterdir())
    assert len(list(workspace.glob("seatbelt.*"))) == 1


@native
@pytest.mark.parametrize("via_symlink", [False, True])
async def test_native_cannot_read_sibling_secret(tmp_path, via_symlink):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    secret = tmp_path / "dummy-secret"
    secret.write_text("synthetic-private-content")
    target = secret
    if via_symlink:
        target = workspace / "escape"
        target.symlink_to(secret)
    result = await SeatbeltBackend().run_command(
        str(workspace), f"/bin/cat {shlex.quote(str(target))}", timeout=5
    )
    assert result.exit_code != 0
    assert "synthetic-private-content" not in result.stdout


@native
async def test_native_cannot_write_shared_sibling_temp(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside-temp"
    outside.write_text("unchanged")
    result = await SeatbeltBackend().run_command(
        str(workspace), f"printf changed > {shlex.quote(str(outside))}", timeout=5
    )
    assert result.exit_code != 0
    assert outside.read_text() == "unchanged"
