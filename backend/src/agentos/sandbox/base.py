"""Sandbox backend abstraction (D28 — process-level sandboxing)."""

import sys
from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class ShellResult:
    stdout: str
    stderr: str
    exit_code: int
    duration_ms: int


class SandboxBackend(ABC):
    """Abstract sandbox backend. v0.1 implements Seatbelt (macOS) and bwrap (Linux)."""

    @abstractmethod
    async def run_command(
        self, workspace_path: str, command: str, timeout: int = 30, allow_network: bool = False
    ) -> ShellResult:
        """Run a shell command in the sandbox with the workspace mounted."""

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
