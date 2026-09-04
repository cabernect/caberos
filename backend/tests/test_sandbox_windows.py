"""Test platform sandbox resolution and the degraded-shell path.

The guarantee under test: shell isolation being unavailable is a *reported
state*, never an exception. A machine with no usable sandbox must still run
agents — it just refuses the shell capability and says why.
"""

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
