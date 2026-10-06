"""Test the MXC (Microsoft Execution Containers) sandbox backend.

MXC genuinely executes commands (verified by hand against the real binary),
but its own vendor does not yet call it a security boundary — so every test
here also asserts the "experimental, not available" reporting contract, not
just that commands run.
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agentos.sandbox.mxc import MxcBackend, _build_config, _sandbox_env, _sandbox_path


def _reset_class_state() -> None:
    MxcBackend._probe_cache = None
    MxcBackend._reason = None
    MxcBackend._needs_setup = False


@pytest.fixture(autouse=True)
def _clear_probe_cache():
    _reset_class_state()
    yield
    _reset_class_state()


def test_trusted_is_false():
    """The registry/probe() contract depends on this never being True."""
    assert MxcBackend.trusted is False


def test_unavailable_when_binary_not_found():
    with (
        patch("agentos.sandbox.mxc.shutil.which", return_value=None),
        patch.dict("os.environ", {}, clear=True),
    ):
        backend = MxcBackend()
        assert backend.is_available() is False
        assert "not found" in (backend.unavailable_reason() or "")
        # Missing binary is something to install, not a setup the app can run.
        assert backend.needs_host_setup() is False


def test_env_override_path_used_when_present(tmp_path):
    fake_exe = tmp_path / "wxc-exec.exe"
    fake_exe.write_text("")
    probe_result = MagicMock(returncode=0, stdout=json.dumps({"tier": "base-container"}))
    setup_result = MagicMock(returncode=0)

    with (
        patch.dict("os.environ", {"CABEROS_MXC_EXE_PATH": str(fake_exe)}),
        patch("agentos.sandbox.mxc.subprocess.run", side_effect=[probe_result, setup_result]),
    ):
        backend = MxcBackend()
        assert backend.is_available() is True


def test_unavailable_when_probe_reports_no_tier(tmp_path):
    fake_exe = tmp_path / "wxc-exec.exe"
    fake_exe.write_text("")
    probe_result = MagicMock(returncode=0, stdout=json.dumps({}))

    with (
        patch.dict("os.environ", {"CABEROS_MXC_EXE_PATH": str(fake_exe)}),
        patch("agentos.sandbox.mxc.subprocess.run", return_value=probe_result),
    ):
        backend = MxcBackend()
        assert backend.is_available() is False
        assert "capability probe" in (backend.unavailable_reason() or "")


def test_unavailable_when_one_time_setup_not_done(tmp_path):
    """tier is real, but the trial run fails -- prepare-system-drive hasn't run."""
    fake_exe = tmp_path / "wxc-exec.exe"
    fake_exe.write_text("")
    probe_result = MagicMock(returncode=0, stdout=json.dumps({"tier": "base-container"}))
    trial_run_denied = MagicMock(returncode=1)

    with (
        patch.dict("os.environ", {"CABEROS_MXC_EXE_PATH": str(fake_exe)}),
        patch("agentos.sandbox.mxc.subprocess.run", side_effect=[probe_result, trial_run_denied]),
    ):
        backend = MxcBackend()
        assert backend.is_available() is False
        reason = backend.unavailable_reason() or ""
        assert "prepare-system-drive" in reason
        # The hint must point at the prep tool that sits next to the located exe.
        assert str(tmp_path / "wxc-host-prep.exe") in reason
        assert backend.needs_host_setup() is True


def test_available_when_tier_present_and_setup_done(tmp_path):
    fake_exe = tmp_path / "wxc-exec.exe"
    fake_exe.write_text("")
    probe_result = MagicMock(returncode=0, stdout=json.dumps({"tier": "base-container"}))
    trial_run_ok = MagicMock(returncode=0)

    with (
        patch.dict("os.environ", {"CABEROS_MXC_EXE_PATH": str(fake_exe)}),
        patch("agentos.sandbox.mxc.subprocess.run", side_effect=[probe_result, trial_run_ok]),
    ):
        backend = MxcBackend()
        assert backend.is_available() is True
        assert backend.unavailable_reason() is None


def test_experimental_notice_always_present():
    backend = MxcBackend()
    notice = backend.experimental_notice()
    assert notice
    assert "security boundary" in notice


def test_build_config_schema_matches_the_real_validated_shape(tmp_path):
    """Regression guard: the SDK's own published docs example used fields
    (network.allowOutbound, top-level timeoutMs) that the real binary's
    --dry-run validator rejected. This locks in the shape confirmed against
    the actual binary instead."""
    config = _build_config(str(tmp_path), "echo hi", allow_network=False)
    assert config["network"] == {"defaultPolicy": "block"}
    assert "allowOutbound" not in json.dumps(config)
    assert "timeoutMs" not in config
    assert config["filesystem"]["readwritePaths"] == [str(tmp_path)]
    assert "cmd.exe /c cd /d" in config["process"]["commandLine"]
    assert "echo hi" in config["process"]["commandLine"]


def test_build_config_enables_ui_but_keeps_clipboard_and_injection_shut(tmp_path):
    """Regression guard, found live: with the SDK default (UI disabled) ordinary
    console programs such as whoami.exe and PowerShell die with
    STATUS_DLL_INIT_FAILED (0xC0000142) because they initialise win32k. The
    real binary's validator accepts only disable/clipboard/injection here."""
    ui = _build_config(str(tmp_path), "whoami", allow_network=False)["ui"]
    assert ui == {"disable": False, "clipboard": "none", "injection": False}


_HOST_ENV = {
    "SystemRoot": "C:\\Windows",
    "SystemDrive": "C:",
    "ComSpec": "C:\\Windows\\System32\\cmd.exe",
    "ProgramFiles": "C:\\Program Files",
    "ProgramFiles(x86)": "C:\\Program Files (x86)",
    "LOCALAPPDATA": "C:\\Users\\Dev\\AppData\\Local",
    "PATH": ";".join(
        [
            "C:\\Program Files\\Git\\usr\\bin",
            "C:\\Users\\Dev\\AppData\\Local\\Programs\\Python\\Python311",
            "C:\\Program Files\\Git\\cmd",
            "C:\\Windows\\System32",
        ]
    ),
}


def _env_names(entries: list[str]) -> set[str]:
    return {entry.split("=", 1)[0].upper() for entry in entries}


def test_sandbox_env_never_forwards_host_secrets():
    """Regression guard, found live: with no process.env MXC builds the
    container's environment from the user's persistent environment, so a real
    API key set with `setx` was readable from inside the container. The
    environment is an allowlist; nothing outside it may pass through."""
    host = {
        **_HOST_ENV,
        "OPENAI_API_KEY": "sk-should-not-leak",
        "ELEVENLABS_API_KEY": "sk_should-not-leak",
        "AWS_SECRET_ACCESS_KEY": "should-not-leak",
        "GITHUB_TOKEN": "ghp_should-not-leak",
    }
    with patch.dict("os.environ", host, clear=True):
        entries = _sandbox_env("C:\\ws")

    assert not {"OPENAI_API_KEY", "ELEVENLABS_API_KEY", "AWS_SECRET_ACCESS_KEY", "GITHUB_TOKEN"} & (
        _env_names(entries)
    )
    assert "should-not-leak" not in "\n".join(entries)


def test_sandbox_env_supplies_what_mxc_requires_even_when_the_host_lacks_it():
    """MXC refuses to launch unless SYSTEMROOT and LOCALAPPDATA are present."""
    with patch.dict("os.environ", {}, clear=True):
        entries = _sandbox_env("C:\\ws")

    assert {"SYSTEMROOT", "LOCALAPPDATA"} <= _env_names(entries)


def test_sandbox_env_home_is_the_workspace_not_the_real_profile():
    with patch.dict("os.environ", _HOST_ENV, clear=True):
        entries = dict(entry.split("=", 1) for entry in _sandbox_env("C:\\ws"))

    assert entries["HOME"] == "C:\\ws"
    assert entries["USERPROFILE"] == "C:\\ws"
    assert entries["APPDATA"].startswith("C:\\ws")


def test_sandbox_path_leads_with_windows_dirs_and_drops_unreadable_entries():
    """Git's MSYS tools (`usr\\bin`) ahead of System32 made `whoami` resolve to an
    MSYS build that cannot initialise inside the container; entries in the user
    profile are unreadable there, so they are pointless."""
    with patch.dict("os.environ", _HOST_ENV, clear=True):
        entries = _sandbox_path("C:\\Windows").split(";")

    assert entries[0] == "C:\\Windows\\System32"
    assert entries.count("C:\\Windows\\System32") == 1
    assert "C:\\Program Files\\Git\\cmd" in entries
    assert entries.index("C:\\Program Files\\Git\\usr\\bin") > entries.index(
        "C:\\Windows\\System32"
    )
    assert not any("Python311" in entry for entry in entries)


def test_build_config_supplies_the_environment_as_key_value_strings(tmp_path):
    env = _build_config(str(tmp_path), "echo hi", allow_network=False)["process"]["env"]
    assert env
    assert all(isinstance(entry, str) and "=" in entry for entry in env)


def test_build_config_allow_network():
    config = _build_config("C:\\ws", "echo hi", allow_network=True)
    assert config["network"] == {"defaultPolicy": "allow"}


@pytest.mark.asyncio
async def test_workspace_on_a_different_drive_fails_fast_with_a_clear_reason(tmp_path):
    """Regression guard: prepare-system-drive only grants rights to the
    Windows system drive. A workspace on another drive used to fail with a
    bare 'Access is denied' from the OS — verified by hand against the real
    binary. This must fail fast with an actionable message instead, and must
    never even invoke wxc-exec.exe for a doomed call."""
    fake_exe = tmp_path / "wxc-exec.exe"
    fake_exe.write_text("")
    with (
        patch.dict("os.environ", {"CABEROS_MXC_EXE_PATH": str(fake_exe), "SystemDrive": "C:"}),
        patch("asyncio.create_subprocess_exec") as mocked,
    ):
        backend = MxcBackend()
        result = await backend.run_command("D:\\some\\workspace", "echo hi")

    mocked.assert_not_called()
    assert result.exit_code == -1
    assert "system drive" in result.stderr
    assert "D:" in result.stderr


@pytest.mark.asyncio
async def test_run_command_invokes_binary_with_config_file(tmp_path):
    fake_exe = tmp_path / "wxc-exec.exe"
    fake_exe.write_text("")
    captured = {}

    async def fake_create_subprocess_exec(*args, **kwargs):
        captured["args"] = args
        # Read back what was written so we can assert on real JSON content.
        with open(args[1]) as f:
            captured["config"] = json.load(f)
        proc = AsyncMock()
        proc.communicate = AsyncMock(return_value=(b"hello\n", b""))
        proc.returncode = 0
        return proc

    with (
        patch.dict("os.environ", {"CABEROS_MXC_EXE_PATH": str(fake_exe)}),
        patch("asyncio.create_subprocess_exec", side_effect=fake_create_subprocess_exec),
    ):
        backend = MxcBackend()
        result = await backend.run_command(str(tmp_path), "echo hello")

    assert result.exit_code == 0
    assert result.stdout == "hello\n"
    assert str(captured["args"][0]) == str(fake_exe)
    assert captured["config"]["process"]["commandLine"].endswith("echo hello")


@pytest.mark.asyncio
async def test_run_command_cleans_up_temp_config_file(tmp_path):
    fake_exe = tmp_path / "wxc-exec.exe"
    fake_exe.write_text("")
    written_paths = []

    async def fake_create_subprocess_exec(*args, **kwargs):
        written_paths.append(args[1])
        proc = AsyncMock()
        proc.communicate = AsyncMock(return_value=(b"", b""))
        proc.returncode = 0
        return proc

    with (
        patch.dict("os.environ", {"CABEROS_MXC_EXE_PATH": str(fake_exe)}),
        patch("asyncio.create_subprocess_exec", side_effect=fake_create_subprocess_exec),
    ):
        backend = MxcBackend()
        await backend.run_command(str(tmp_path), "echo hi")

    from pathlib import Path as _P

    assert not _P(written_paths[0]).exists(), "temp config file should be deleted after the run"


@pytest.mark.asyncio
async def test_timeout_kills_the_process(tmp_path):
    fake_exe = tmp_path / "wxc-exec.exe"
    fake_exe.write_text("")

    async def fake_create_subprocess_exec(*args, **kwargs):
        proc = AsyncMock()

        async def hang():
            import asyncio as _asyncio

            await _asyncio.sleep(10)

        proc.communicate = hang
        proc.returncode = None
        proc.kill = MagicMock()
        proc.wait = AsyncMock(return_value=0)
        return proc

    with (
        patch.dict("os.environ", {"CABEROS_MXC_EXE_PATH": str(fake_exe)}),
        patch("asyncio.create_subprocess_exec", side_effect=fake_create_subprocess_exec),
    ):
        backend = MxcBackend()
        result = await backend.run_command(str(tmp_path), "sleep 30", timeout=0.05)

    assert result.exit_code == -1
    assert "timed out" in result.stderr
