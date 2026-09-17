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

# "unavailable" means shell is refused but the rest of the product works —
# get_backend() only ever returns a fully-working backend or UnavailableBackend,
# so there is no distinct "installed but degraded" middle state to report.
SandboxState = Literal["available", "unavailable"]


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


class SandboxBackend(ABC):
    """Abstract sandbox backend.

    Implementations: Seatbelt (macOS), bwrap (Linux), Docker (any platform,
    fallback), and Unavailable (no candidate on this machine works).
    """

    # Short identifier surfaced through the health endpoint.
    kind: str = "unknown"

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


class UnavailableBackend(SandboxBackend):
    """No isolation is possible — refuse shell execution, explain why.

    Deliberately not an exception. Shell being disabled is a supported
    configuration the operator and the model can both read, not a crash in
    the middle of a run.
    """

    kind = "none"

    def __init__(self, reason: str | None = None) -> None:
        self._reason = reason or "No sandbox is available on this platform."

    def is_available(self) -> bool:
        return False

    def unavailable_reason(self) -> str | None:
        return self._reason

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
    from .docker import DockerBackend

    native: Callable[[], SandboxBackend] | None = None
    if platform == "darwin":
        from .seatbelt import SeatbeltBackend

        native = SeatbeltBackend
    elif platform.startswith("linux"):
        from .bwrap import BwrapBackend

        native = BwrapBackend

    candidates: list[Callable[[], SandboxBackend]] = []
    if native is not None:
        candidates.append(native)
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
    backend: SandboxBackend | None = None
    for make_backend in _candidates_for(platform):
        candidate = make_backend()
        if candidate.is_available():
            backend = candidate
            break
        reason = candidate.unavailable_reason()
        if reason:
            tried_reasons.append(f"{candidate.kind}: {reason}")

    if backend is None:
        if tried_reasons:
            reason = "No sandbox available. " + " / ".join(tried_reasons)
        else:
            reason = f"No sandbox implementation for platform {platform!r}."
        backend = UnavailableBackend(reason=reason)

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
        _probe_cache = SandboxProbe(kind=backend.kind, state="available")
    else:
        _probe_cache = SandboxProbe(
            kind=backend.kind,
            state="unavailable",
            reason=backend.unavailable_reason(),
        )
    return _probe_cache
