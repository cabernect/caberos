"""Sandbox backend abstraction (D28 — process-level sandboxing).

get_backend() never raises. Each platform has an ordered list of candidate
backends; the first one whose is_available() returns true wins. Where no
candidate is available, the terminal capability is refused with a reason
naming every candidate that was tried — never a crash mid-run.
"""

import sys
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

# "unavailable" means shell is refused but the rest of the product works.
# "experimental" means the backend genuinely executed the command — this is
# not a fallback-with-a-caveat state — but its own vendor has not yet
# published it as a real security boundary (see MxcBackend.trusted). It is
# reported distinctly from "available" so CaberOS never silently claims
# isolation strength it cannot back up.
SandboxState = Literal["available", "experimental", "unavailable"]


@dataclass
class ShellResult:
    stdout: str
    stderr: str
    exit_code: int
    duration_ms: int


@dataclass
class SandboxProbe:
    """What the operator needs to know about shell isolation on this machine."""

    kind: str
    state: SandboxState
    reason: str | None = None
    # True when the only thing missing is a one-time, operator-approved host
    # setup (e.g. MXC's elevated system-drive grant) that the desktop app can
    # offer to run — as opposed to something the operator must install.
    setup_required: bool = False


class SandboxBackend(ABC):
    """Abstract sandbox backend.

    Implementations: Seatbelt (macOS), bwrap (Linux), Docker (macOS/Linux
    fallback), MXC (Windows, experimental), and Unavailable (no candidate on
    this machine works).
    """

    # Short identifier surfaced through the health endpoint.
    kind: str = "unknown"

    # False means: this backend genuinely runs commands, but its own vendor
    # has not published it as a real security boundary yet. A working
    # backend is not automatically a trusted one — see MxcBackend.
    trusted: bool = True

    @abstractmethod
    async def run_command(
        self, workspace_path: str, command: str, timeout: int = 30, allow_network: bool = False
    ) -> ShellResult:
        """Run a shell command in the sandbox with the workspace mounted."""

    @abstractmethod
    def is_available(self) -> bool:
        """Check if this backend's tool is installed and usable."""

    def unavailable_reason(self) -> str | None:
        """Why this backend cannot isolate, when it cannot. None when it can."""
        return None

    def experimental_notice(self) -> str | None:
        """Caveat to surface for a working but untrusted (trusted=False) backend."""
        return None

    def needs_host_setup(self) -> bool:
        """True when this backend is installed but waiting on a one-time host setup."""
        return False


class UnavailableBackend(SandboxBackend):
    """No isolation is possible — refuse shell execution, explain why.

    Deliberately not an exception. Shell being disabled is a supported
    configuration the operator and the model can both read, not a crash in
    the middle of a run.
    """

    kind = "none"

    def __init__(self, reason: str | None = None, setup_required: bool = False) -> None:
        self._reason = reason or "No sandbox is available on this platform."
        self._setup_required = setup_required

    def is_available(self) -> bool:
        return False

    def unavailable_reason(self) -> str | None:
        return self._reason

    def needs_host_setup(self) -> bool:
        return self._setup_required

    async def run_command(
        self, workspace_path: str, command: str, timeout: int = 30, allow_network: bool = False
    ) -> ShellResult:
        return ShellResult(
            stdout="",
            stderr=(
                f"Shell commands are disabled on this machine. {self._reason} "
                "All other capabilities — files, web, memory, skills, knowledge and "
                "MCP tools — are unaffected."
            ),
            exit_code=-1,
            duration_ms=0,
        )


def _candidates_for(platform: str) -> list[Callable[[], SandboxBackend]]:
    """Ordered constructors to try for this platform, native backend first."""
    if platform == "win32":
        # Windows has no trusted native sandbox, and the desktop app must not
        # ask a user to install Docker Desktop or WSL for shell to work. MXC
        # ships inside the installer; it is reported as "experimental" (never
        # "available") because Microsoft does not yet call it a security boundary.
        from .mxc import MxcBackend

        return [MxcBackend]

    from .docker import DockerBackend

    candidates: list[Callable[[], SandboxBackend]] = []
    if platform == "darwin":
        from .seatbelt import SeatbeltBackend

        candidates.append(SeatbeltBackend)
    elif platform.startswith("linux"):
        from .bwrap import BwrapBackend

        candidates.append(BwrapBackend)
    candidates.append(DockerBackend)
    return candidates


# Keyed by sys.platform rather than a single slot: a real machine's platform
# never changes at runtime, so this caches exactly one entry in production,
# but tests that monkeypatch sys.platform across calls still get a correct,
# independent resolution per platform value instead of a stale one.
_backend_cache: dict[str, SandboxBackend] = {}


def get_backend(refresh: bool = False) -> SandboxBackend:
    """Return the best available backend for the current platform.

    Never raises. Tries each platform candidate in priority order (native
    sandbox first, Docker as a cross-platform fallback) and returns the first
    one whose is_available() is true. Where none work, returns an
    UnavailableBackend whose reason names every candidate that was tried.

    Cached: every strict-mode shell call goes through this function, and
    constructing a fresh backend each time re-runs its availability probe
    every time too — some probes spawn a subprocess. Pass refresh=True to
    force a new probe (e.g. after the operator installs a missing dependency).
    """
    platform = sys.platform
    if not refresh and platform in _backend_cache:
        return _backend_cache[platform]

    tried_reasons: list[str] = []
    setup_required = False
    backend: SandboxBackend | None = None
    for make_backend in _candidates_for(platform):
        candidate = make_backend()
        if candidate.is_available():
            backend = candidate
            break
        reason = candidate.unavailable_reason()
        if reason:
            tried_reasons.append(f"{candidate.kind}: {reason}")
        setup_required = setup_required or candidate.needs_host_setup()

    if backend is None:
        if tried_reasons:
            reason = "No sandbox available. " + " / ".join(tried_reasons)
        else:
            reason = f"No sandbox implementation for platform {platform!r}."
        # Deliberately not cached: the most common fix (e.g. starting Docker
        # Desktop) happens after the gateway is already running, and the
        # operator has no way to force a recheck short of restarting the
        # whole app. Re-probing on every call while broken is cheap next to
        # staying stuck refusing shell commands for the rest of the process.
        return UnavailableBackend(reason=reason, setup_required=setup_required)

    _backend_cache[platform] = backend
    return backend


_probe_cache: SandboxProbe | None = None


def probe(refresh: bool = False) -> SandboxProbe:
    """Describe shell-isolation availability on this machine.

    Cached: probing can spawn a subprocess, so this must not run on every
    tool call. Pass refresh=True after the operator installs a dependency.
    """
    global _probe_cache
    if _probe_cache is not None and not refresh:
        return _probe_cache

    backend = get_backend(refresh=refresh)
    if backend.is_available():
        if backend.trusted:
            _probe_cache = SandboxProbe(kind=backend.kind, state="available")
        else:
            _probe_cache = SandboxProbe(
                kind=backend.kind,
                state="experimental",
                reason=backend.experimental_notice(),
            )
        return _probe_cache

    # Mirrors get_backend(): an unavailable result is never cached, so the
    # health endpoint reflects a dependency (e.g. Docker Desktop) coming up
    # without requiring an app restart.
    return SandboxProbe(
        kind=backend.kind,
        state="unavailable",
        reason=backend.unavailable_reason(),
        setup_required=backend.needs_host_setup(),
    )
