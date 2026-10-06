"""Test the sandbox backend registry — priority resolution and degradation.

The guarantee under test: get_backend() never raises. Every platform tries
an ordered list of candidates and degrades to a reported, explained refusal
when none work — it never crashes mid-run the way `main` used to
(`raise RuntimeError("Sandbox not supported on win32...")`).
"""

import sys
from unittest.mock import patch

import pytest

import agentos.sandbox.base as sandbox_base
from agentos.sandbox import get_backend, probe
from agentos.sandbox.base import SandboxBackend, UnavailableBackend, _backend_cache
from agentos.sandbox.bwrap import BwrapBackend
from agentos.sandbox.docker import DockerBackend
from agentos.sandbox.mxc import MxcBackend


def _clear_caches() -> None:
    _backend_cache.clear()
    sandbox_base._probe_cache = None


@pytest.fixture(autouse=True)
def _clear_backend_cache():
    """Every test gets clean registry + probe caches — resolution order isn't
    stable across tests otherwise, since both are keyed by (or scoped to) the
    real sys.platform, which doesn't change between tests."""
    _clear_caches()
    yield
    _clear_caches()


@pytest.mark.parametrize("platform", ["darwin", "linux", "linux2", "win32", "freebsd", "aix"])
def test_get_backend_never_raises(platform):
    """Every platform resolves to a backend — none raise.

    Regression guard: get_backend() on `main` raised RuntimeError on any
    platform that wasn't darwin/linux, which surfaced mid-run as a tool crash
    rather than a platform capability decision.
    """
    with (
        patch.object(sys, "platform", platform),
        patch.object(DockerBackend, "is_available", return_value=False),
        patch.object(MxcBackend, "is_available", return_value=False),
    ):
        backend = get_backend()
    assert isinstance(backend, SandboxBackend)
    assert backend.kind


def test_unknown_platform_gets_unavailable_backend_naming_every_candidate():
    """An unrecognised platform degrades rather than failing, and the reason
    names every backend that was tried (not just the last one)."""
    with (
        patch.object(sys, "platform", "freebsd"),
        patch.object(DockerBackend, "is_available", return_value=False),
        patch.object(DockerBackend, "unavailable_reason", return_value="Docker is not installed."),
    ):
        backend = get_backend()
    assert isinstance(backend, UnavailableBackend)
    assert "docker" in (backend.unavailable_reason() or "")


def test_unavailable_reason_names_every_tried_candidate_not_just_the_last():
    """With two failing candidates (native + Docker), the reason must mention
    both — not just whichever one happened to be tried last."""
    with (
        patch.object(sys, "platform", "linux"),
        patch.object(BwrapBackend, "is_available", return_value=False),
        patch.object(
            BwrapBackend, "unavailable_reason", return_value="bubblewrap is not installed."
        ),
        patch.object(DockerBackend, "is_available", return_value=False),
        patch.object(DockerBackend, "unavailable_reason", return_value="Docker is not installed."),
    ):
        backend = get_backend()

    reason = backend.unavailable_reason() or ""
    assert "bwrap" in reason
    assert "docker" in reason


def test_native_backend_preferred_over_docker_when_both_available():
    """On a platform with a native sandbox, it wins over Docker even if Docker
    also works — native isolation is stronger and doesn't need a daemon."""
    with (
        patch.object(sys, "platform", "linux"),
        patch("agentos.sandbox.bwrap.BwrapBackend.is_available", return_value=True),
        patch.object(DockerBackend, "is_available", return_value=True),
    ):
        backend = get_backend()
    assert backend.kind == "bwrap"


def test_docker_used_as_fallback_when_native_unavailable():
    """When the native backend isn't usable, Docker is tried next instead of
    immediately giving up."""
    with (
        patch.object(sys, "platform", "linux"),
        patch("agentos.sandbox.bwrap.BwrapBackend.is_available", return_value=False),
        patch.object(DockerBackend, "is_available", return_value=True),
    ):
        backend = get_backend()
    assert backend.kind == "docker"


def test_get_backend_is_cached_across_calls():
    """Repeated calls must not re-probe every candidate each time."""
    probe_calls = 0

    def counting_is_available(self):
        nonlocal probe_calls
        probe_calls += 1
        return True

    with (
        patch.object(sys, "platform", "linux"),
        patch.object(BwrapBackend, "is_available", counting_is_available),
    ):
        first = get_backend()
        second = get_backend()

    assert first is second
    assert probe_calls == 1


def test_get_backend_refresh_forces_a_new_probe():
    """refresh=True must bypass the registry cache — e.g. after installing
    Docker. Mocks at the subprocess boundary (not is_available itself) so
    DockerBackend's own instance-level probe cache behaves as it would in
    production instead of being bypassed by the mock."""
    with (
        patch.object(sys, "platform", "freebsd"),
        patch("agentos.sandbox.docker.shutil.which", return_value=None),
    ):
        first = get_backend()
        second = get_backend(refresh=True)

    # Different DockerBackend instances prove get_backend() actually
    # re-resolved instead of returning the cached UnavailableBackend.
    assert first is not second


def test_get_backend_does_not_cache_unavailable_result():
    """An 'unavailable' resolution must not stick — the operator fixes this
    kind of thing (e.g. starting Docker Desktop) while the app keeps running,
    and has no way to force a recheck short of restarting it. Regression
    guard for a real bug: get_backend() used to cache UnavailableBackend just
    like any other result, so a dependency that came up after the first
    probe was never noticed again for the life of the process."""
    # A mutable flag rather than a call counter: BwrapBackend.unavailable_reason()
    # itself calls is_available() again to build its message, so counting
    # invocations is brittle — what matters is that get_backend() re-resolves
    # on the second call instead of returning a cached UnavailableBackend.
    bwrap_available = False

    def flaky_is_available(self):
        return bwrap_available

    with (
        patch.object(sys, "platform", "linux"),
        patch.object(BwrapBackend, "is_available", flaky_is_available),
        patch.object(DockerBackend, "is_available", return_value=False),
    ):
        first = get_backend()
        bwrap_available = True
        second = get_backend()  # no refresh=True — must still re-probe

    assert isinstance(first, UnavailableBackend)
    assert second.kind == "bwrap"


def test_probe_does_not_cache_unavailable_result():
    """Mirrors test_get_backend_does_not_cache_unavailable_result() at the
    probe() layer, which is what the /api/health endpoint actually calls."""
    bwrap_available = False

    def flaky_is_available(self):
        return bwrap_available

    with (
        patch.object(sys, "platform", "linux"),
        patch.object(BwrapBackend, "is_available", flaky_is_available),
        patch.object(DockerBackend, "is_available", return_value=False),
    ):
        first = probe()
        bwrap_available = True
        second = probe()  # no refresh=True — must still reflect recovery

    assert first.state == "unavailable"
    assert second.state == "available"


def test_windows_uses_mxc_and_never_constructs_docker():
    """The Windows desktop app must not need Docker Desktop (or WSL) for shell."""
    with (
        patch.object(sys, "platform", "win32"),
        patch.object(MxcBackend, "is_available", return_value=True),
        patch("agentos.sandbox.docker.DockerBackend") as docker_ctor,
    ):
        backend = get_backend()

    assert backend.kind == "mxc"
    docker_ctor.assert_not_called()


def test_windows_does_not_fall_back_to_docker_even_when_docker_is_running():
    with (
        patch.object(sys, "platform", "win32"),
        patch.object(MxcBackend, "is_available", return_value=False),
        patch.object(MxcBackend, "unavailable_reason", return_value="not set up"),
        patch.object(DockerBackend, "is_available", return_value=True),
    ):
        backend = get_backend()

    assert isinstance(backend, UnavailableBackend)
    assert "docker" not in (backend.unavailable_reason() or "")


def test_setup_required_survives_into_the_unavailable_backend_and_probe():
    """The dashboard offers a one-click setup only when MXC is installed but
    waiting on its one-time host grant — that fact has to reach probe()."""
    with (
        patch.object(sys, "platform", "win32"),
        patch.object(MxcBackend, "is_available", return_value=False),
        patch.object(MxcBackend, "unavailable_reason", return_value="needs setup"),
        patch.object(MxcBackend, "needs_host_setup", return_value=True),
    ):
        backend = get_backend()
        result = probe()

    assert backend.needs_host_setup() is True
    assert result.state == "unavailable"
    assert result.setup_required is True


def test_setup_not_required_when_a_dependency_is_simply_missing():
    with (
        patch.object(sys, "platform", "win32"),
        patch.object(MxcBackend, "is_available", return_value=False),
        patch.object(MxcBackend, "unavailable_reason", return_value="wxc-exec.exe not found"),
        patch.object(MxcBackend, "needs_host_setup", return_value=False),
    ):
        result = probe()

    assert result.setup_required is False


def test_probe_reports_experimental_for_an_untrusted_working_backend():
    """A backend that works but isn't vendor-trusted must never be reported
    as plain 'available' — that would overclaim isolation strength."""
    with (
        patch.object(sys, "platform", "win32"),
        patch.object(MxcBackend, "is_available", return_value=True),
        patch.object(MxcBackend, "experimental_notice", return_value="not a real boundary yet"),
    ):
        result = probe(refresh=True)

    assert result.kind == "mxc"
    assert result.state == "experimental"
    assert result.reason == "not a real boundary yet"


def test_probe_reports_state_and_reason():
    """probe() always yields a kind and a valid state."""
    result = probe(refresh=True)
    assert result.kind
    assert result.state in ("available", "experimental", "unavailable")
    if result.state == "available":
        assert result.reason is None
    elif result.state == "unavailable":
        assert result.reason
