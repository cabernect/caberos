"""Sandbox backend abstraction (D28 — process-level sandboxing)."""

import sys
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Literal

# Reported to the operator so a missing sandbox is a visible state rather than
# a crash. "degraded" means shell is refused but the rest of the product works.
SandboxState = Literal["available", "degraded", "unavailable"]


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

    Implementations: Seatbelt (macOS), bwrap (Linux), bwrap-via-WSL2 (Windows),
    and Unavailable (any platform with no usable isolation).
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
        """Check if this backend's tool is installed."""

    def unavailable_reason(self) -> str | None:
        """Why this backend cannot isolate, when it cannot. None when it can."""
        return None


def get_backend() -> SandboxBackend:
    """Return the appropriate backend for the current platform.

    Never raises. A platform with no usable sandbox gets a backend that refuses
    shell execution with an explanation, because the shell capability being
    disabled is a supported configuration — not an error condition. Every other
    capability is unaffected.
    """
    if sys.platform == "darwin":
        from .seatbelt import SeatbeltBackend

        return SeatbeltBackend()
    elif sys.platform.startswith("linux"):
        from .bwrap import BwrapBackend

        return BwrapBackend()
    elif sys.platform == "win32":
        from .windows import UnavailableBackend, WslBwrapBackend

        wsl = WslBwrapBackend()
        if wsl.is_available():
            return wsl
        return UnavailableBackend(reason=wsl.unavailable_reason())
    else:
        from .windows import UnavailableBackend

        return UnavailableBackend(
            reason=f"No sandbox implementation for platform {sys.platform!r}."
        )


_probe_cache: SandboxProbe | None = None


def probe(refresh: bool = False) -> SandboxProbe:
    """Describe shell-isolation availability on this machine.

    Cached: probing can spawn a subprocess (WSL2), so this must not run on
    every tool call. Pass refresh=True after the operator installs a dependency.
    """
    global _probe_cache
    if _probe_cache is not None and not refresh:
        return _probe_cache

    backend = get_backend()
    if backend.is_available():
        _probe_cache = SandboxProbe(kind=backend.kind, state="available")
    else:
        # The backend exists but its tool is missing (for example bwrap not
        # installed on Linux). Shell is refused; everything else still works.
        _probe_cache = SandboxProbe(
            kind=backend.kind,
            state="degraded" if backend.kind != "none" else "unavailable",
            reason=backend.unavailable_reason(),
        )
    return _probe_cache
