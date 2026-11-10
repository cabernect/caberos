"""W11.1 — execution-transport contract tests.

A remote driver will hand the registry a SpawnedProcess that is not an
asyncio.subprocess.Process (an SSH channel, a cloud exec). These fixtures
prove the registry's guarantees — start, incremental read with cursors,
spool bounds, close — hold for any process shaped like the protocol, so
remote drivers inherit correct behavior rather than re-deriving it.
"""

from __future__ import annotations

import asyncio
import sys
import time

import pytest

from agentos.models.terminal import TerminalSession
from agentos.terminal.registry import TerminalRegistry


class FakeRemoteProcess:
    """A non-subprocess SpawnedProcess — output piped in, wait() driven by
    the fixture, pid deliberately foreign (no such local process)."""

    def __init__(self, stdout: bytes, stderr: bytes = b"", delay: float = 0.0):
        self.stdout = asyncio.StreamReader()
        self.stdout.feed_data(stdout)
        self.stdout.feed_eof()
        self.stderr = asyncio.StreamReader()
        self.stderr.feed_data(stderr)
        self.stderr.feed_eof()
        self.pid = 0x5EED  # foreign pid — os.getpgid must not resolve it
        self.returncode: int | None = None
        self._delay = delay
        self.signals: list[int] = []

    def send_signal(self, sig: int) -> None:
        self.signals.append(sig)
        if self.returncode is None:
            self.returncode = -int(sig)

    def kill(self) -> None:
        self.signals.append(9)
        if self.returncode is None:
            self.returncode = -9

    async def wait(self) -> int:
        remaining = self._delay
        while remaining > 0 and self.returncode is None:
            step = min(0.05, remaining)
            await asyncio.sleep(step)
            remaining -= step
        if self.returncode is None:
            self.returncode = 0
        return self.returncode


class FakeRemoteTransport:
    """Captures spawn args; returns the fixture process."""

    def __init__(self, proc: FakeRemoteProcess):
        self.proc = proc
        self.seen: list[tuple[list[str], dict | None, str | None]] = []

    async def spawn(self, argv, *, env, cwd):
        self.seen.append((argv, env, cwd))
        return self.proc


@pytest.fixture
def terminals(tmp_path, monkeypatch):
    from agentos.config import settings

    monkeypatch.setattr(settings, "db_path", tmp_path / "test.db")
    yield TerminalRegistry()


OWNER = {"agent_id": "a1", "session_id": "s1", "run_id": "r1"}


async def test_remote_process_start_read_close(terminals, db):
    transport = FakeRemoteTransport(FakeRemoteProcess(b"remote hello\n", b"warn\n"))
    result = await terminals.start(
        db,
        command="echo remote hello",
        workspace_path="/remote/work",
        sandbox_mode="open",
        transport=transport,
        **OWNER,
    )
    tid = result["terminal_id"]
    argv, env, cwd = transport.seen[0]
    assert argv == ["/bin/sh", "-c", "echo remote hello"] and cwd == "/remote/work"

    await asyncio.sleep(0.2)  # let the pump + monitor settle
    read = await terminals.read(tid, offset=0, **OWNER)
    assert read["stdout"] == "remote hello\n"
    assert read["stderr"].endswith("warn\n")
    assert read["status"] == "completed" and read["exit_code"] == 0
    assert read["next_offset"] > 0

    closed = await terminals.close(tid, **OWNER)
    assert closed["status"] == "completed" and closed["error"] is None

    row = await db.get(TerminalSession, tid)
    assert row.status == "completed" and row.backend_kind == "open"


async def test_remote_output_spool_is_bounded(terminals, db):
    big = b"x" * (5 * 1024 * 1024)  # past the 4 MiB spool cap
    transport = FakeRemoteTransport(FakeRemoteProcess(big))
    result = await terminals.start(
        db,
        command="cat big",
        workspace_path="/w",
        sandbox_mode="open",
        transport=transport,
        **OWNER,
    )
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        read = await terminals.read(result["terminal_id"], offset=0, **OWNER)
        if read["stdout_bytes"] >= len(big):
            break
        await asyncio.sleep(0.1)
    assert read["truncated"] is True
    assert read["stdout_bytes"] == len(big)  # drained, not all retained


async def test_remote_close_returns_unread_output(terminals, db):
    transport = FakeRemoteTransport(FakeRemoteProcess(b"leftover\n", delay=60))
    result = await terminals.start(
        db,
        command="slow",
        workspace_path="/w",
        sandbox_mode="open",
        transport=transport,
        **OWNER,
    )
    closed = await terminals.close(result["terminal_id"], **OWNER)
    assert "leftover" in closed["stdout_tail"]
    assert transport.proc.signals  # termination reached the remote handle


async def test_local_transport_still_real_subprocess(terminals, db):
    """Regression: the default transport path still runs a real command."""
    if sys.platform == "win32":
        pytest.skip("POSIX echo")
    result = await terminals.start(
        db,
        command="echo local-ok",
        workspace_path="/tmp",
        sandbox_mode="open",
        **OWNER,
    )
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        read = await terminals.read(result["terminal_id"], offset=0, **OWNER)
        if read["status"] != "running":
            break
        await asyncio.sleep(0.1)
    assert read["status"] == "completed"
    assert read["stdout"] == "local-ok\n"
