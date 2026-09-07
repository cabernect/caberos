"""Sandbox backend abstraction (D28 — process-level sandboxing)."""

import asyncio
import sys
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Literal

# Reported to the operator so a missing sandbox is a visible state rather than
# a crash. "degraded" means shell is refused but the rest of the product works.
SandboxState = Literal["available", "degraded", "unavailable"]

# How long a killed process may take to disappear before we stop waiting for it.
_KILL_GRACE = 5


async def terminate_process(proc: asyncio.subprocess.Process) -> None:
    """Kill a spawned sandbox process and wait for it to actually be gone.

    A timed-out command that is merely abandoned keeps running: it goes on
    writing to the workspace and holding resources after CaberOS has reported
    it stopped. Killing the launcher is enough to take the whole tree down.
    Under `--unshare-all` bwrap owns a PID namespace, so its death reaps every
    process inside it; through WSL2 the same chain applies one level up, where
    killing `wsl.exe` tears down the relay that is bwrap's parent and
    `--die-with-parent` propagates from there.
    """
    if proc.returncode is not None:
        return
    try:
        proc.kill()
    except ProcessLookupError:
        return
    try:
        await asyncio.wait_for(proc.wait(), timeout=_KILL_GRACE)
    except TimeoutError:
        pass


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


def _reset_backend_caches() -> None:
    """Clear the per-backend probe caches, which outlive backend instances."""
    from . import bwrap, windows

    bwrap.reset_probe_cache()
    windows.reset_probe_cache()


def probe(refresh: bool = False) -> SandboxProbe:
    """Describe shell-isolation availability on this machine.

    Cached: probing can spawn a subprocess (WSL2), so this must not run on
    every tool call. Pass refresh=True after the operator installs a dependency.
    """
    global _probe_cache
    if _probe_cache is not None and not refresh:
        return _probe_cache

    if refresh:
        _reset_backend_caches()

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
