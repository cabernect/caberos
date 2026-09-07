"""Test platform sandbox resolution and the degraded-shell path.

The guarantee under test: shell isolation being unavailable is a *reported
state*, never an exception. A machine with no usable sandbox must still run
agents — it just refuses the shell capability and says why.
"""

import asyncio
import subprocess
import sys
from unittest.mock import patch

import pytest

from agentos.sandbox import get_backend, probe
from agentos.sandbox.base import SandboxBackend
from agentos.sandbox.windows import UnavailableBackend, WslBwrapBackend


@pytest.mark.parametrize(
    "platform",
    ["darwin", "linux", "linux2", "win32", "freebsd", "aix", "emscripten"],
)
def test_get_backend_never_raises(platform):
    """Every platform resolves to a backend — none raise.

    Regression guard: get_backend() used to raise RuntimeError on any platform
    that was not darwin or linux, which surfaced mid-run as a tool crash rather
    than as a platform capability decision.

    The WSL probe is stubbed out because this asserts the *factory* contract,
    not probe behaviour. It also has to be: faking sys.platform makes
    shutil.which() take its Windows branch, which calls into _winapi — and
    that module is None anywhere but Windows.
    """
    with (
        patch.object(sys, "platform", platform),
        patch.object(WslBwrapBackend, "is_available", return_value=False),
    ):
        backend = get_backend()
    assert isinstance(backend, SandboxBackend)
    assert backend.kind


def test_unknown_platform_gets_unavailable_backend():
    """An unrecognised platform degrades rather than failing."""
    with patch.object(sys, "platform", "freebsd"):
        backend = get_backend()
    assert isinstance(backend, UnavailableBackend)
    assert backend.is_available() is False
    assert "freebsd" in (backend.unavailable_reason() or "")


@pytest.mark.asyncio
async def test_unavailable_backend_refuses_without_raising():
    """A refused shell command returns a result the model can read."""
    backend = UnavailableBackend(reason="WSL2 is not installed.")
    result = await backend.run_command("/tmp", "echo hello")

    assert result.exit_code != 0
    assert result.stdout == ""
    assert "WSL2 is not installed." in result.stderr
    # The operator must learn that only shell is affected, not the whole agent.
    assert "unaffected" in result.stderr


@pytest.mark.asyncio
async def test_unmappable_workspace_is_refused_not_passed_to_bwrap():
    """A workspace that cannot be translated into WSL refuses cleanly.

    Handing bwrap an unresolvable bind source would fail with an opaque mount
    error, so the translation failure is caught and explained instead.
    """
    backend = WslBwrapBackend()
    with patch.object(WslBwrapBackend, "_to_wsl_path", return_value=None):
        result = await backend.run_command(r"\\server\share\ws", "echo hello")

    assert result.exit_code != 0
    assert "could not be mapped into WSL2" in result.stderr


def test_probe_reports_state_and_reason():
    """probe() always yields a kind and a valid state."""
    result = probe(refresh=True)
    assert result.kind
    assert result.state in ("available", "degraded", "unavailable")
    # An unhealthy sandbox must always name a cause; a healthy one needs none.
    if result.state == "available":
        assert result.reason is None
    else:
        assert result.reason


def test_probe_is_cached():
    """The probe can spawn a subprocess, so it must not run per tool call."""
    first = probe(refresh=True)
    with patch("agentos.sandbox.base.get_backend") as mocked:
        second = probe()
        mocked.assert_not_called()
    assert first is second


def test_wsl_probe_runs_once_across_backends():
    """get_backend() builds a backend per shell call; the probe must not rerun.

    A per-instance cache is discarded immediately, so every strict command paid
    for another WSL probe — up to 30 seconds of blocking per command.
    """
    from agentos.sandbox import windows

    windows.reset_probe_cache()
    completed = subprocess.CompletedProcess(args=[], returncode=0)
    with (
        patch.object(sys, "platform", "win32"),
        patch.object(windows.shutil, "which", return_value=r"C:\Windows\wsl.exe"),
        patch.object(windows.subprocess, "run", return_value=completed) as run,
    ):
        first = get_backend()
        second = get_backend()

    assert isinstance(first, WslBwrapBackend)
    assert isinstance(second, WslBwrapBackend)
    assert run.call_count == 1
    windows.reset_probe_cache()


def test_refreshing_the_probe_reruns_the_backend_check():
    """The caches outlive backend instances, so refresh has to clear them."""
    from agentos.sandbox import windows

    windows.reset_probe_cache()
    completed = subprocess.CompletedProcess(args=[], returncode=0)
    with (
        patch.object(sys, "platform", "win32"),
        patch.object(windows.shutil, "which", return_value=r"C:\Windows\wsl.exe"),
        patch.object(windows.subprocess, "run", return_value=completed) as run,
    ):
        probe(refresh=True)
        probe(refresh=True)

    assert run.call_count == 2
    windows.reset_probe_cache()
    probe(refresh=True)


def test_every_concrete_backend_names_itself():
    """`kind` reaches the health API, so no backend may report "unknown"."""
    from agentos.sandbox.bwrap import BwrapBackend
    from agentos.sandbox.seatbelt import SeatbeltBackend

    kinds = {
        SeatbeltBackend().kind,
        BwrapBackend().kind,
        WslBwrapBackend().kind,
        UnavailableBackend().kind,
    }
    assert kinds == {"seatbelt", "bwrap", "wsl-bwrap", "none"}


@pytest.mark.skipif(sys.platform == "win32", reason="needs a POSIX shell")
@pytest.mark.asyncio
async def test_timed_out_command_is_killed(tmp_path):
    """A timed-out command must be dead, not merely abandoned.

    Without an explicit kill the process keeps running: it goes on writing to
    the workspace long after CaberOS has reported the command stopped.
    """
    from agentos.sandbox import bwrap

    marker = tmp_path / "written-after-the-timeout"
    spawned = []
    real_exec = asyncio.create_subprocess_exec

    async def record(*args, **kwargs):
        proc = await real_exec(*args, **kwargs)
        spawned.append(proc)
        return proc

    with patch.object(bwrap.asyncio, "create_subprocess_exec", record):
        result = await bwrap.run_sandboxed(
            ["/usr/bin/env"], f"sleep 5; echo late > {marker}", timeout=1, args=[]
        )

    assert result.exit_code == -1
    assert "timed out" in result.stderr
    assert spawned and spawned[0].returncode is not None

    await asyncio.sleep(1.5)
    assert not marker.exists()


def test_bwrap_probe_uses_the_real_profile():
    """The probe must bind the system paths a real command gets.

    bwrap starts from an empty root, so probing with `--unshare-all` alone and
    no bind mounts fails with "execvp /bin/sh: No such file or directory" even
    on a machine where the sandbox works perfectly — reporting every healthy
    host as unavailable.
    """
    from agentos.sandbox.bwrap import build_probe_args

    args = build_probe_args()
    assert "--ro-bind" in args
    assert "/usr" in args
    assert "--unshare-all" in args
