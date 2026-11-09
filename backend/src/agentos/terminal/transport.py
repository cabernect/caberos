"""Execution transport seam — what the registry actually needs from a spawned
command (W11).

The registry owns spooling, cursors, ownership, and status. It does not need
a local subprocess specifically — it needs stdout/stderr readers, a wait(),
a returncode, and something pid-shaped for bookkeeping. A remote driver (SSH
channel, cloud exec) that exposes the same surface slots into the registry
without touching read/close/cursor semantics.

`LocalTransport` preserves today's behavior; remote transports arrive with
their backend drivers, never as a silent fallback.
"""

from __future__ import annotations

import asyncio
import subprocess
from typing import Protocol


class SpawnedProcess(Protocol):
    """The registry's minimal view of a launched command, local or remote."""

    stdout: asyncio.StreamReader | None
    stderr: asyncio.StreamReader | None
    pid: int
    returncode: int | None

    async def wait(self) -> int:
        """Complete and return the exit code."""
        ...

    def send_signal(self, sig: int) -> None:
        """Termination request — local signal or the driver's remote kill."""
        ...

    def kill(self) -> None:
        """Forceful termination — the driver's last resort."""
        ...


class TerminalTransport(Protocol):
    """How a command becomes a SpawnedProcess on this backend."""

    async def spawn(
        self,
        argv: list[str],
        *,
        env: dict[str, str] | None,
        cwd: str | None,
    ) -> SpawnedProcess:
        """Start the command; returns a handle, never a claim that it finished."""
        ...


class LocalTransport:
    """Local subprocess spawn — the pre-W11 registry path, unchanged."""

    async def spawn(
        self,
        argv: list[str],
        *,
        env: dict[str, str] | None,
        cwd: str | None,
    ) -> SpawnedProcess:
        return await asyncio.create_subprocess_exec(
            *argv,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
            env=env,
            start_new_session=True,
            # The packaged gateway has no console (CREATE_NO_WINDOW); without
            # it, console-subsystem children would allocate a visible window.
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )


LOCAL_TRANSPORT = LocalTransport()
