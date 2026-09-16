"""Sandbox backend abstraction (D28 — process-level sandboxing)."""

import asyncio
import contextlib
import os
import signal
import sys
from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class ShellResult:
    stdout: str
    stderr: str
    exit_code: int
    duration_ms: int


async def kill_process_group(proc: asyncio.subprocess.Process, grace: float = 3.0) -> None:
    """SIGTERM the process's group, SIGKILL after `grace` seconds.

    Requires the process to have been spawned with start_new_session=True so
    the group contains the whole tree. Safe on an already-exited process.
    """
    if proc.returncode is not None:
        return
    try:
        pgid = os.getpgid(proc.pid)
    except (ProcessLookupError, PermissionError):
        pgid = None

    def _kill(sig: int) -> None:
        try:
            if pgid is not None:
                os.killpg(pgid, sig)
            else:
                proc.send_signal(sig)
        except (ProcessLookupError, PermissionError):
            pass

    _kill(signal.SIGTERM)
    try:
        await asyncio.wait_for(asyncio.shield(proc.wait()), timeout=grace)
        return
    except TimeoutError:
        pass
    _kill(signal.SIGKILL)
    with contextlib.suppress(Exception):
        await proc.wait()


class SandboxBackend(ABC):
    """Abstract sandbox backend. v0.1 implements Seatbelt (macOS) and bwrap (Linux)."""

    @abstractmethod
    async def run_command(
        self, workspace_path: str, command: str, timeout: int = 30, allow_network: bool = False
    ) -> ShellResult:
        """Run a shell command in the sandbox with the workspace mounted."""

    @abstractmethod
    def spawn_argv(
        self, workspace_path: str, command: str, allow_network: bool = False
    ) -> list[str]:
        """Argv to launch `command` under this sandbox.

        Used by the terminal registry to spawn long-running processes whose
        lifecycle it manages itself (process group, spooled output, kill).
        """

    def spawn_env(self, workspace_path: str) -> dict[str, str] | None:
        """Env for a spawned sandbox process; None = inherit parent env."""
        return None

    @abstractmethod
    def is_available(self) -> bool:
        """Check if this backend's tool is installed."""


def get_backend() -> SandboxBackend:
    """Return the appropriate backend for the current platform."""
    if sys.platform == "darwin":
        from .seatbelt import SeatbeltBackend

        return SeatbeltBackend()
    elif sys.platform.startswith("linux"):
        from .bwrap import BwrapBackend

        return BwrapBackend()
    else:
        raise RuntimeError(f"Sandbox not supported on {sys.platform}. Use WSL2 on Windows.")
