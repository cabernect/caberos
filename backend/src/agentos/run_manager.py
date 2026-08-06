"""Run manager — first-class run lifecycle, decoupled from HTTP connections.

A run is created via POST /message, executes independently, and can be:
  - Streamed via GET /runs/{id}/events (reconnectable SSE)
  - Polled via GET /runs/{id} (works even when detached)
  - Stopped via POST /runs/{id}/stop
  - Resumed via POST /api/approvals/{id}/approve (HITL)

The run executes in a managed asyncio.Task tracked by run_id. Events are
buffered per-run so reconnects don't lose data. When the run finishes,
the RunContext stays registered for late reconnects and status polling.

This is the transport-agnostic core: CLI, scheduler, and connectors
can call run_agent() directly without this module. The run manager is
only needed for the HTTP/SSE transport (reconnectable streams).
"""

import asyncio
from dataclasses import dataclass, field

from .pipeline import Attachment
from .runner import run_agent


@dataclass
class RunContext:
    """Per-run context: the executing task + event buffer for reconnectable SSE.

    Events are stored as (seq, event_type, payload) tuples. The seq number
    lets reconnecting clients resume from where they left off.
    """

    run_id: str
    session_id: str
    agent_id: str
    task: asyncio.Task
    status: str = "running"  # running, awaiting_approval, completed, failed, stopped
    events: list[tuple[int, str, dict]] = field(default_factory=list)
    _seq: int = 0
    _waiters: list[asyncio.Future] = field(default_factory=list)

    def append_event(self, event_type: str, payload: dict) -> int:
        """Buffer an event and notify any SSE readers waiting for new events."""
        self._seq += 1
        seq = self._seq
        self.events.append((seq, event_type, payload))
        # Wake up any SSE readers waiting for the next event
        for waiter in self._waiters:
            if not waiter.done():
                waiter.set_result(seq)
        self._waiters.clear()
        return seq

    async def wait_for_event(self, after_seq: int, timeout: float = 1.0) -> int | None:
        """Wait for an event with seq > after_seq. Returns the new seq, or None on timeout."""
        # Check if there's already a newer event buffered
        for seq, _, _ in reversed(self.events):
            if seq > after_seq:
                return seq
        # No newer event — wait for one to arrive
        future: asyncio.Future = asyncio.get_event_loop().create_future()
        self._waiters.append(future)
        try:
            return await asyncio.wait_for(future, timeout=timeout)
        except TimeoutError:
            if not future.done():
                self._waiters.remove(future)
            return None


# Process-global registry of active runs
_active_runs: dict[str, RunContext] = {}


def get_run(run_id: str) -> RunContext | None:
    """Get an active run context by run_id."""
    return _active_runs.get(run_id)


def list_active_runs() -> list[RunContext]:
    """List all active runs."""
    return list(_active_runs.values())


async def start_run(
    agent_id: str,
    text: str,
    user_id: str,
    *,
    is_test: bool = False,
    model_override: dict[str, str] | None = None,
    session_id: str | None = None,
    new_session: bool = False,
    attachments: list[Attachment] | None = None,
    skill: str | None = None,
) -> dict[str, str]:
    """Start a run in a managed task. Returns {run_id, session_id}.

    The run executes independently of this call. Events are buffered in the
    RunContext and can be read via GET /runs/{id}/events.
    """
    # The run_id is captured from the run_started event (fires early in the pipeline)
    run_id_future: asyncio.Future[str] = asyncio.get_event_loop().create_future()
    session_id_future: asyncio.Future[str] = asyncio.get_event_loop().create_future()

    async def event_callback(event_type: str, payload: dict) -> None:
        # Capture run_id and session_id from run_started (fires before other events)
        if event_type == "run_started":
            rid = payload.get("run_id", "")
            sid = payload.get("session_id", "")
            if rid and not run_id_future.done():
                run_id_future.set_result(rid)
            if sid and not session_id_future.done():
                session_id_future.set_result(sid)
        # Buffer events into the RunContext (if registered)
        rid = payload.get("run_id") or (run_id_future.result() if run_id_future.done() else None)
        if rid and rid in _active_runs:
            ctx = _active_runs[rid]
            if event_type == "tool_call" and payload.get("status") == "pending_approval":
                ctx.status = "awaiting_approval"
            elif event_type == "message_complete":
                ctx.status = "completed" if payload.get("status") == "completed" else "failed"
            ctx.append_event(event_type, payload)

    async def _execute() -> None:
        """The run executor — runs in a managed task."""
        try:
            await run_agent(
                agent_id=agent_id,
                text=text,
                user_id=user_id,
                is_test=is_test,
                model_override=model_override,
                session_id=session_id,
                new_session=new_session,
                attachments=attachments,
                event_callback=event_callback,
                skill=skill,
            )
        except asyncio.CancelledError:
            rid = run_id_future.result() if run_id_future.done() else None
            if rid and rid in _active_runs:
                ctx = _active_runs[rid]
                ctx.status = "stopped"
                ctx.append_event(
                    "message_complete",
                    {
                        "run_id": rid,
                        "status": "stopped",
                        "error": "Run was stopped by user",
                    },
                )
            raise
        except Exception as e:
            import traceback

            traceback.print_exc()
            rid = run_id_future.result() if run_id_future.done() else None
            if rid and rid in _active_runs:
                ctx = _active_runs[rid]
                ctx.status = "failed"
                ctx.append_event(
                    "message_complete",
                    {
                        "run_id": rid,
                        "status": "failed",
                        "error": str(e),
                    },
                )
            if not run_id_future.done():
                run_id_future.set_exception(e)

    task = asyncio.create_task(_execute())

    # Wait for the run_id (run_started fires early, before any LLM calls)
    try:
        run_id = await asyncio.wait_for(run_id_future, timeout=30.0)
    except TimeoutError:
        task.cancel()
        raise RuntimeError("Run failed to start — no run_started event received")
    except Exception:
        task.cancel()
        raise

    try:
        session_id = await asyncio.wait_for(session_id_future, timeout=1.0)
    except TimeoutError:
        session_id = ""

    # Register the RunContext
    ctx = RunContext(
        run_id=run_id,
        session_id=session_id,
        agent_id=agent_id,
        task=task,
    )
    _active_runs[run_id] = ctx

    # Auto-cleanup when the task finishes — keep context for 60s for late
    # reconnects and status polling, then remove from memory.
    def _on_done(t: asyncio.Task) -> None:
        if run_id in _active_runs:
            ctx = _active_runs[run_id]
            if ctx.status == "running":
                ctx.status = "completed"

            # Schedule cleanup after 60s (events are in the DB, context is just a cache)
            async def _delayed_cleanup() -> None:
                await asyncio.sleep(60)
                _active_runs.pop(run_id, None)

            asyncio.create_task(_delayed_cleanup())

    task.add_done_callback(_on_done)

    return {"run_id": run_id, "session_id": session_id}


async def stop_run(run_id: str) -> bool:
    """Stop a running run. Returns True if the run was stopped."""
    ctx = _active_runs.get(run_id)
    if ctx is None or ctx.task.done():
        return False
    ctx.task.cancel()
    try:
        await ctx.task
    except asyncio.CancelledError:
        pass
    ctx.status = "stopped"
    return True


def get_run_status(run_id: str) -> dict | None:
    """Get the status of a run. Works even when detached from SSE."""
    ctx = _active_runs.get(run_id)
    if ctx is None:
        return None
    return {
        "run_id": ctx.run_id,
        "session_id": ctx.session_id,
        "agent_id": ctx.agent_id,
        "status": ctx.status,
        "event_count": len(ctx.events),
    }
