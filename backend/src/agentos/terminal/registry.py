"""TerminalRegistry — owns background terminal processes for the gateway.

Design (v0.2 workstream 01):
- Every terminal runs in its own process group (start_new_session) so
  killpg() terminates the whole tree, including grandchildren.
- stdout/stderr are spooled to bounded files under data/terminals/ — never
  held in memory wholesale and never auto-injected into model context.
- read_terminal returns incremental output via a byte cursor; callers keep
  the cursor and pass it back for the next read.
- Ownership is scoped to (agent_id, session_id, run_id) — another run cannot
  read or close a terminal it did not start.
- On gateway startup, persisted `running` rows are reconciled to
  `interrupted`: the process never survives a restart, and we never claim
  it did.
"""

from __future__ import annotations

import asyncio
import os
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..models.terminal import TerminalSession
from ..sandbox import get_backend
from ..sandbox.base import kill_process_group

# Output spool cap per stream — beyond this we keep draining (so the child
# never blocks on a full pipe) but stop persisting, and flag truncation.
SPOOL_CAP_BYTES = 4 * 1024 * 1024
# How often the long-poll checks for new output.
POLL_INTERVAL_SECONDS = 0.1


@dataclass
class _ManagedTerminal:
    """In-memory handle for a live (or recently finished) process."""

    id: str
    agent_id: str
    session_id: str | None
    run_id: str
    proc: asyncio.subprocess.Process
    pgid: int
    stdout_path: Path
    stderr_path: Path
    stdout_bytes: int = 0
    stderr_bytes: int = 0
    truncated: bool = False
    status: str = "running"
    exit_code: int | None = None
    pump_tasks: list[asyncio.Task] = field(default_factory=list)
    monitor_task: asyncio.Task | None = None


def _terminals_dir() -> Path:
    d = settings.db_path.parent / "terminals"
    d.mkdir(parents=True, exist_ok=True)
    return d


class TerminalRegistry:
    """Process-wide registry — one per gateway."""

    def __init__(self) -> None:
        self._terminals: dict[str, _ManagedTerminal] = {}

    async def start(
        self,
        db: AsyncSession,
        *,
        command: str,
        workspace_path: str,
        sandbox_mode: str,
        agent_id: str,
        session_id: str | None,
        run_id: str,
        db_lock: asyncio.Lock | None = None,
    ) -> dict[str, Any]:
        """Spawn a background process and return its terminal handle."""
        terminal_id = uuid.uuid4().hex
        tdir = _terminals_dir()
        stdout_path = tdir / f"{terminal_id}.stdout"
        stderr_path = tdir / f"{terminal_id}.stderr"
        stdout_path.touch()
        stderr_path.touch()

        if sandbox_mode == "open":
            argv = ["/bin/sh", "-c", command]
            env = None
        else:
            backend = get_backend()
            argv = backend.spawn_argv(workspace_path=workspace_path, command=command)
            env = backend.spawn_env(workspace_path)

        # Host-side cwd matters for seatbelt; bwrap overrides with --chdir.
        proc = await asyncio.create_subprocess_exec(
            *argv,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=workspace_path,
            env=env,
            start_new_session=True,
        )
        try:
            pgid = os.getpgid(proc.pid)
        except (ProcessLookupError, PermissionError):
            pgid = proc.pid

        t = _ManagedTerminal(
            id=terminal_id,
            agent_id=agent_id,
            session_id=session_id,
            run_id=run_id,
            proc=proc,
            pgid=pgid,
            stdout_path=stdout_path,
            stderr_path=stderr_path,
        )
        t.pump_tasks = [
            asyncio.create_task(self._pump(t, proc.stdout, stdout_path, "stdout")),
            asyncio.create_task(self._pump(t, proc.stderr, stderr_path, "stderr")),
        ]
        t.monitor_task = asyncio.create_task(self._monitor(t))
        self._terminals[terminal_id] = t

        row = TerminalSession(
            id=terminal_id,
            agent_id=agent_id,
            session_id=session_id,
            run_id=run_id,
            workspace_path=workspace_path,
            process_group_id=pgid,
            status="running",
            command=command[:2048],
            stdout_path=str(stdout_path),
            stderr_path=str(stderr_path),
        )
        if db_lock is not None:
            async with db_lock:
                db.add(row)
                await db.flush()
        else:
            db.add(row)
            await db.flush()

        return {"terminal_id": terminal_id, "status": "running", "pid": proc.pid}

    async def read(
        self,
        terminal_id: str,
        *,
        agent_id: str,
        session_id: str | None,
        run_id: str,
        offset: int = 0,
        max_chars: int = 8192,
        wait_ms: int = 0,
    ) -> dict[str, Any]:
        """Incremental read: returns stdout bytes since `offset` + stderr tail.

        With wait_ms>0, long-polls until output grows or the process exits.
        """
        t = self._get_owned(terminal_id, agent_id, session_id, run_id)
        deadline = time.monotonic() + wait_ms / 1000

        while True:
            stdout_size = t.stdout_path.stat().st_size if t.stdout_path.exists() else 0
            if stdout_size > offset or t.status != "running" or time.monotonic() >= deadline:
                break
            await asyncio.sleep(POLL_INTERVAL_SECONDS)

        chunk, next_offset = self._read_spool(t.stdout_path, offset, max_chars)
        stderr_tail, _ = self._tail(t.stderr_path, 4096)
        return {
            "terminal_id": terminal_id,
            "status": t.status,
            "exit_code": t.exit_code,
            "stdout": chunk,
            "stderr": stderr_tail,
            "next_offset": next_offset,
            "stdout_bytes": t.stdout_bytes,
            "truncated": t.truncated,
        }

    async def close(
        self,
        terminal_id: str,
        *,
        agent_id: str,
        session_id: str | None,
        run_id: str,
    ) -> dict[str, Any]:
        """Terminate the process group if running; idempotent."""
        t = self._get_owned(terminal_id, agent_id, session_id, run_id)
        if t.status == "running":
            await kill_process_group(t.proc)
            t.status = "closed"
            t.exit_code = t.proc.returncode if t.proc.returncode is not None else -15
            await self._finalize(t)
            await self._persist(t)
        # Always return whatever output remains unread — bounded tail.
        stdout, _ = self._tail(t.stdout_path, 8192)
        stderr, _ = self._tail(t.stderr_path, 4096)
        return {
            "terminal_id": terminal_id,
            "status": t.status,
            "exit_code": t.exit_code,
            "stdout_tail": stdout,
            "stderr_tail": stderr,
            "truncated": t.truncated,
        }

    async def active_for_run(self, run_id: str) -> list[str]:
        """Terminal IDs still running for a run — used by the run-end guard."""
        return [
            tid
            for tid, t in self._terminals.items()
            if t.run_id == run_id and t.status == "running"
        ]

    async def close_for_run(self, run_id: str) -> int:
        """Terminate every terminal a run owns — used when the run is
        cancelled so it never orphans process groups."""
        closed = 0
        for t in list(self._terminals.values()):
            if t.run_id == run_id and t.status == "running":
                await kill_process_group(t.proc)
                t.status = "closed"
                t.exit_code = t.proc.returncode if t.proc.returncode is not None else -15
                await self._finalize(t)
                await self._persist(t)
                closed += 1
        return closed

    async def reconcile_startup(self, db: AsyncSession) -> int:
        """Mark persisted `running` rows as interrupted — processes never
        survive a gateway restart."""
        result = await db.execute(
            update(TerminalSession)
            .where(TerminalSession.status == "running")
            .values(status="interrupted", completed_at=datetime.now(UTC))
        )
        return result.rowcount or 0

    async def shutdown_all(self) -> None:
        """Kill every running process group — called on gateway shutdown."""
        for t in self._terminals.values():
            if t.status == "running":
                await kill_process_group(t.proc, grace=1.0)
                t.status = "closed"
                await self._persist(t)

    # --- internals -------------------------------------------------------

    def _get_owned(
        self, terminal_id: str, agent_id: str, session_id: str | None, run_id: str
    ) -> _ManagedTerminal:
        t = self._terminals.get(terminal_id)
        if t is None or t.agent_id != agent_id or t.session_id != session_id or t.run_id != run_id:
            raise ValueError("terminal not found")
        return t

    async def _pump(
        self, t: _ManagedTerminal, stream: asyncio.StreamReader | None, path: Path, which: str
    ) -> None:
        """Drain the pipe to the spool file; keep draining past the cap so
        the child never blocks, but stop persisting."""
        if stream is None:
            return
        written = 0
        try:
            with open(path, "ab") as f:
                while True:
                    chunk = await stream.read(65536)
                    if not chunk:
                        return
                    if which == "stdout":
                        t.stdout_bytes += len(chunk)
                    else:
                        t.stderr_bytes += len(chunk)
                    if written < SPOOL_CAP_BYTES:
                        keep = chunk[: SPOOL_CAP_BYTES - written]
                        f.write(keep)
                        f.flush()
                        written += len(keep)
                        if written >= SPOOL_CAP_BYTES:
                            t.truncated = True
                    else:
                        t.truncated = True
        except (OSError, ValueError):
            pass

    async def _monitor(self, t: _ManagedTerminal) -> None:
        try:
            code = await t.proc.wait()
            t.exit_code = code
            if t.status == "running":
                t.status = "completed" if code == 0 else "failed"
            await self._finalize(t)
            await self._persist(t)
        except asyncio.CancelledError:
            pass
        except Exception:
            if t.status == "running":
                t.status = "failed"
                await self._persist(t)

    async def _finalize(self, t: _ManagedTerminal) -> None:
        """Let pumps flush remaining output to the spool files."""
        for task in t.pump_tasks:
            task.cancel()
        if t.pump_tasks:
            await asyncio.gather(*t.pump_tasks, return_exceptions=True)

    @staticmethod
    async def _persist(t: _ManagedTerminal) -> None:
        """Best-effort persist on a fresh session — the request-scoped
        session that created the terminal is long gone by this point."""
        try:
            from ..db import async_session_factory

            async with async_session_factory() as db:
                await db.execute(
                    update(TerminalSession)
                    .where(TerminalSession.id == t.id)
                    .values(
                        status=t.status,
                        exit_code=t.exit_code,
                        stdout_bytes=t.stdout_bytes,
                        stderr_bytes=t.stderr_bytes,
                        truncated=t.truncated,
                        completed_at=datetime.now(UTC),
                    )
                )
                await db.commit()
        except Exception:
            # Persistence is observability, not correctness — never crash the
            # monitor task on a DB hiccup.
            import logging

            logging.getLogger(__name__).warning("terminal %s: failed to persist final state", t.id)

    @staticmethod
    def _read_spool(path: Path, offset: int, max_chars: int) -> tuple[str, int]:
        if not path.exists():
            return "", offset
        size = path.stat().st_size
        if offset >= size:
            return "", offset
        with open(path, "rb") as f:
            f.seek(offset)
            data = f.read(max_chars)
        return data.decode("utf-8", errors="replace"), offset + len(data)

    @staticmethod
    def _tail(path: Path, max_chars: int) -> tuple[str, int]:
        if not path.exists():
            return "", 0
        size = path.stat().st_size
        with open(path, "rb") as f:
            f.seek(max(0, size - max_chars))
            data = f.read(max_chars)
        return data.decode("utf-8", errors="replace"), size


# Process-wide singleton — like approval_registry.
terminal_registry = TerminalRegistry()
