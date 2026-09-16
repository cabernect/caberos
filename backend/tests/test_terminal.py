"""Tests for background terminal lifecycle (terminal/registry.py)."""

import asyncio
import os
import time

import pytest
from sqlalchemy import select

from agentos.capabilities.builtin import register_builtin_capabilities
from agentos.capabilities.registry import registry
from agentos.config_schema import AgentConfig, CapabilityGrant, ModelConfig
from agentos.models.terminal import TerminalSession
from agentos.sandbox import get_backend
from agentos.syscall.mediator import SyscallHandler
from agentos.syscall.protocol import ToolCall
from agentos.terminal.registry import TerminalRegistry


@pytest.fixture(autouse=True)
def _caps():
    registry._caps.clear()
    register_builtin_capabilities()
    yield
    registry._caps.clear()


@pytest.fixture
def terminals(tmp_path, monkeypatch):
    """Fresh registry with spool files under tmp_path."""
    from agentos.config import settings

    monkeypatch.setattr(settings, "db_path", tmp_path / "test.db")
    r = TerminalRegistry()
    yield r
    # Best-effort cleanup so tests never leave processes behind.
    for t in list(r._terminals.values()):
        if t.status == "running":
            t.proc.kill()


def _config(caps: list[str], **kw) -> AgentConfig:
    return AgentConfig(
        id="term-agent",
        name="Terminal Agent",
        model=ModelConfig(provider_id="test-provider", name="test-model"),
        capabilities=[CapabilityGrant(name=c, **kw) for c in caps],
    )


def _session():
    from types import SimpleNamespace

    return SimpleNamespace(contact_id="contact-1", id="sess-1", channel=None)


OWNER = {"agent_id": "term-agent", "session_id": "sess-1", "run_id": "run-1"}


async def _wait_status(reg, tid, status, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        t = reg._terminals[tid]
        if t.status == status:
            return t
        await asyncio.sleep(0.05)
    return reg._terminals[tid]


class TestBackgroundStart:
    async def test_async_returns_immediately(self, db, terminals):
        start = time.monotonic()
        result = await terminals.start(
            db,
            command="sleep 5",
            workspace_path="/tmp",
            sandbox_mode="open",
            **OWNER,
        )
        elapsed = time.monotonic() - start
        assert result["status"] == "running"
        assert result["terminal_id"]
        assert elapsed < 2.0  # did not wait for the 5s sleep

        await terminals.close(result["terminal_id"], **OWNER)

    async def test_persists_terminal_session_row(self, db, terminals):
        result = await terminals.start(
            db, command="true", workspace_path="/tmp", sandbox_mode="open", **OWNER
        )
        await db.commit()
        row = await db.scalar(
            select(TerminalSession).where(TerminalSession.id == result["terminal_id"])
        )
        assert row is not None
        assert row.agent_id == "term-agent"
        assert row.run_id == "run-1"
        assert row.process_group_id is not None

    async def test_zero_exit_completes(self, db, terminals):
        result = await terminals.start(
            db, command="echo done", workspace_path="/tmp", sandbox_mode="open", **OWNER
        )
        t = await _wait_status(terminals, result["terminal_id"], "completed")
        assert t.status == "completed"
        assert t.exit_code == 0

    async def test_nonzero_exit_is_failed(self, db, terminals):
        result = await terminals.start(
            db, command="exit 3", workspace_path="/tmp", sandbox_mode="open", **OWNER
        )
        t = await _wait_status(terminals, result["terminal_id"], "failed")
        assert t.status == "failed"
        assert t.exit_code == 3


class TestIncrementalRead:
    async def test_cursor_reads_do_not_duplicate(self, db, terminals):
        result = await terminals.start(
            db,
            command="echo first; sleep 0.3; echo second",
            workspace_path="/tmp",
            sandbox_mode="open",
            **OWNER,
        )
        tid = result["terminal_id"]

        # Wait for first chunk
        r1 = await terminals.read(tid, offset=0, wait_ms=2000, **OWNER)
        assert "first" in r1["stdout"]

        # Second read from cursor — only new output
        r2 = await terminals.read(tid, offset=r1["next_offset"], wait_ms=2000, **OWNER)
        assert "first" not in r2["stdout"]
        assert "second" in r2["stdout"]
        assert r2["next_offset"] > r1["next_offset"]

        await terminals.close(tid, **OWNER)

    async def test_stderr_tail_returned(self, db, terminals):
        result = await terminals.start(
            db,
            command="echo err-line >&2; echo out-line",
            workspace_path="/tmp",
            sandbox_mode="open",
            **OWNER,
        )
        await _wait_status(terminals, result["terminal_id"], "completed")
        r = await terminals.read(result["terminal_id"], offset=0, **OWNER)
        assert "err-line" in r["stderr"]
        assert "out-line" in r["stdout"]

    async def test_long_poll_wakes_on_output(self, db, terminals):
        result = await terminals.start(
            db,
            command="sleep 0.4; echo woke",
            workspace_path="/tmp",
            sandbox_mode="open",
            **OWNER,
        )
        tid = result["terminal_id"]
        start = time.monotonic()
        r = await terminals.read(tid, offset=0, wait_ms=5000, **OWNER)
        elapsed = time.monotonic() - start
        assert "woke" in r["stdout"]
        assert elapsed < 4.0  # woke on output, not the full wait

        await terminals.close(tid, **OWNER)

    async def test_long_poll_wakes_on_completion(self, db, terminals):
        result = await terminals.start(
            db, command="sleep 0.3", workspace_path="/tmp", sandbox_mode="open", **OWNER
        )
        tid = result["terminal_id"]
        r = await terminals.read(tid, offset=0, wait_ms=5000, **OWNER)
        assert r["status"] in ("completed", "failed")
        assert r["exit_code"] == 0

    async def test_max_chars_bounds_output(self, db, terminals):
        result = await terminals.start(
            db,
            command="printf 'x%.0s' $(seq 1 20000)",
            workspace_path="/tmp",
            sandbox_mode="open",
            **OWNER,
        )
        await _wait_status(terminals, result["terminal_id"], "completed")
        r = await terminals.read(result["terminal_id"], offset=0, max_chars=1000, **OWNER)
        assert len(r["stdout"]) <= 1000


class TestCloseAndKill:
    async def test_close_terminates_running(self, db, terminals):
        result = await terminals.start(
            db, command="sleep 60", workspace_path="/tmp", sandbox_mode="open", **OWNER
        )
        tid = result["terminal_id"]
        r = await terminals.close(tid, **OWNER)
        assert r["status"] == "closed"
        t = terminals._terminals[tid]
        assert t.proc.returncode is not None

    async def test_close_kills_process_group(self, db, terminals):
        """A command that forks a child must not leave the child running."""
        result = await terminals.start(
            db,
            command="sleep 60 & sleep 60",  # child + parent both in the group
            workspace_path="/tmp",
            sandbox_mode="open",
            **OWNER,
        )
        tid = result["terminal_id"]
        pgid = terminals._terminals[tid].pgid
        await asyncio.sleep(0.2)  # let the child fork

        await terminals.close(tid, **OWNER)
        await asyncio.sleep(0.2)

        with pytest.raises(ProcessLookupError):
            os.killpg(pgid, 0)  # group must be gone entirely

    async def test_close_is_idempotent(self, db, terminals):
        result = await terminals.start(
            db, command="sleep 60", workspace_path="/tmp", sandbox_mode="open", **OWNER
        )
        tid = result["terminal_id"]
        r1 = await terminals.close(tid, **OWNER)
        r2 = await terminals.close(tid, **OWNER)
        assert r1["status"] == r2["status"] == "closed"

    async def test_close_returns_unread_output(self, db, terminals):
        result = await terminals.start(
            db,
            command="echo partial; sleep 60",
            workspace_path="/tmp",
            sandbox_mode="open",
            **OWNER,
        )
        tid = result["terminal_id"]
        await asyncio.sleep(0.3)
        r = await terminals.close(tid, **OWNER)
        assert "partial" in r["stdout_tail"]

    async def test_close_for_run_kills_only_that_runs_terminals(self, db, terminals):
        mine = await terminals.start(
            db, command="sleep 30", workspace_path="/tmp", sandbox_mode="open", **OWNER
        )
        other = await terminals.start(
            db,
            command="sleep 30",
            workspace_path="/tmp",
            sandbox_mode="open",
            agent_id="term-agent",
            session_id="sess-1",
            run_id="run-2",
        )
        closed = await terminals.close_for_run("run-1")
        assert closed == 1
        t_mine = terminals._terminals[mine["terminal_id"]]
        t_other = terminals._terminals[other["terminal_id"]]
        assert t_mine.status == "closed"
        assert t_mine.proc.returncode is not None
        assert t_other.status == "running"
        await terminals.close(other["terminal_id"], **{**OWNER, "run_id": "run-2"})


class TestOwnership:
    async def test_other_run_cannot_read(self, db, terminals):
        result = await terminals.start(
            db, command="sleep 5", workspace_path="/tmp", sandbox_mode="open", **OWNER
        )
        tid = result["terminal_id"]
        with pytest.raises(ValueError, match="terminal not found"):
            await terminals.read(tid, agent_id="term-agent", session_id="sess-1", run_id="other")
        await terminals.close(tid, **OWNER)

    async def test_other_agent_cannot_close(self, db, terminals):
        result = await terminals.start(
            db, command="sleep 5", workspace_path="/tmp", sandbox_mode="open", **OWNER
        )
        tid = result["terminal_id"]
        with pytest.raises(ValueError, match="terminal not found"):
            await terminals.close(tid, agent_id="other-agent", session_id="sess-1", run_id="run-1")
        await terminals.close(tid, **OWNER)


class TestRunEndGuard:
    async def test_active_for_run_lists_running(self, db, terminals):
        r1 = await terminals.start(
            db, command="sleep 5", workspace_path="/tmp", sandbox_mode="open", **OWNER
        )
        active = await terminals.active_for_run("run-1")
        assert r1["terminal_id"] in active

        await terminals.close(r1["terminal_id"], **OWNER)
        assert await terminals.active_for_run("run-1") == []

    async def test_harness_emits_terminals_active(self, db, workspace, terminals, monkeypatch):
        """A run finishing with live terminals surfaces them in the result."""
        from agentos.harness.loop import Harness
        from agentos.harness.scripted_model import ScriptedModel, ScriptedResponse

        # loop.py resolves the singleton inside the function — patching the
        # module attribute covers both the import site and the registry.
        monkeypatch.setattr("agentos.terminal.registry.terminal_registry", terminals)

        # Start a terminal bound to this run before the harness finishes.
        await terminals.start(
            db,
            command="sleep 30",
            workspace_path=workspace,
            sandbox_mode="open",
            agent_id="term-agent",
            session_id=None,
            run_id="run-guard",
        )

        model = ScriptedModel([ScriptedResponse(content="done")])
        result = await Harness(model=model).run(
            agent_config=_config([]),
            session=None,
            message="hi",
            syscall_handler=SyscallHandler(db=db, workspace_path=workspace),
            run_id="run-guard",
        )
        assert result.terminals_active


class TestReconcileAndShutdown:
    async def test_reconcile_marks_running_interrupted(self, db, terminals):
        result = await terminals.start(
            db, command="sleep 5", workspace_path="/tmp", sandbox_mode="open", **OWNER
        )
        await db.commit()

        count = await terminals.reconcile_startup(db)
        await db.commit()
        assert count == 1
        row = await db.scalar(
            select(TerminalSession).where(TerminalSession.id == result["terminal_id"])
        )
        assert row.status == "interrupted"

        await terminals.close(result["terminal_id"], **OWNER)

    async def test_shutdown_all_kills_everything(self, db, terminals):
        r1 = await terminals.start(
            db, command="sleep 60", workspace_path="/tmp", sandbox_mode="open", **OWNER
        )
        pgid = terminals._terminals[r1["terminal_id"]].pgid
        await terminals.shutdown_all()
        await asyncio.sleep(0.2)
        with pytest.raises(ProcessLookupError):
            os.killpg(pgid, 0)


class TestSyncPath:
    async def test_sync_terminal_unchanged(self, db, workspace):
        handler = SyscallHandler(db=db, workspace_path=workspace)
        result = await handler.mediate(
            call=ToolCall(id="1", name="terminal", args={"command": "echo sync-ok"}),
            session=_session(),
            agent_config=_config(["terminal"], require_approval=False),
            run_id="run-sync",
        )
        assert result.allowed is True
        assert result.output["exit_code"] == 0
        assert "sync-ok" in result.output["stdout"]

    async def test_mediated_async_roundtrip(self, db, workspace, terminals, monkeypatch):
        """terminal(async=true) → read_terminal → close_terminal through the mediator."""
        monkeypatch.setattr("agentos.terminal.registry.terminal_registry", terminals)
        handler = SyscallHandler(db=db, workspace_path=workspace)
        config = _config(
            ["terminal", "read_terminal", "close_terminal"], require_approval=False
        )
        session = _session()

        start = await handler.mediate(
            call=ToolCall(
                id="1",
                name="terminal",
                args={"command": "echo mediated-hi; sleep 0.3", "async": True},
            ),
            session=session,
            agent_config=config,
            run_id="run-async",
        )
        assert start.allowed is True
        tid = start.output["terminal_id"]
        assert start.output["status"] == "running"

        read = await handler.mediate(
            call=ToolCall(
                id="2",
                name="read_terminal",
                args={"terminal_id": tid, "wait_ms": 3000},
            ),
            session=session,
            agent_config=config,
            run_id="run-async",
        )
        assert read.allowed is True
        assert "mediated-hi" in read.output["stdout"]

        close = await handler.mediate(
            call=ToolCall(id="3", name="close_terminal", args={"terminal_id": tid}),
            session=session,
            agent_config=config,
            run_id="run-async",
        )
        assert close.allowed is True
        assert close.output["status"] in ("completed", "closed")

    async def test_sync_timeout_kills_process(self, workspace):
        """Regression: sync timeout must kill the process group, not orphan it."""
        from unittest.mock import patch

        from agentos.capabilities.tools.terminal import terminal_run

        killed_pgid = None
        real_killpg = os.killpg

        def spy_killpg(pgid, sig):
            nonlocal killed_pgid
            killed_pgid = pgid
            return real_killpg(pgid, sig)

        with patch("agentos.sandbox.base.os.killpg", spy_killpg):
            r = await terminal_run(
                {"command": "sleep 60"}, workspace, timeout=1, sandbox_mode="open"
            )
        assert r["exit_code"] == -1
        assert "timed out" in r["stderr"]
        assert killed_pgid is not None  # the group was actually signalled


class TestSandboxModes:
    async def test_strict_mode_via_backend(self, db, terminals):
        backend = get_backend()
        if not backend.is_available():
            pytest.skip("Sandbox backend not available")
        result = await terminals.start(
            db,
            command="echo strict-ok",
            workspace_path="/tmp",
            sandbox_mode="strict",
            **OWNER,
        )
        t = await _wait_status(terminals, result["terminal_id"], "completed")
        assert t.status == "completed"
        r = await terminals.read(result["terminal_id"], offset=0, **OWNER)
        assert "strict-ok" in r["stdout"]
