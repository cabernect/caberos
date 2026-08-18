"""Heartbeat scheduler — per-agent periodic runs without a user message.

When enabled, fires a Run with trigger="heartbeat" at the configured interval.
The run goes through the same pipeline as user-triggered runs (same context
assembly, same limits, same memory). The result is stored as a heartbeat-tagged
message in the conversation.

Consecutive failures are tracked; if the threshold is exceeded, an alert is
surfaced via GET /api/scheduler/alerts.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy import select

from .agent_service import get_active_config, get_agent
from .db import async_session_factory
from .runner import run_agent

log = logging.getLogger("agentos.scheduler")


@dataclass
class HeartbeatState:
    """Runtime state for one agent's heartbeat scheduler."""

    agent_id: str
    task: asyncio.Task | None = None
    last_fired: datetime | None = None
    last_status: str | None = None  # "completed", "failed", "stopped"
    last_error: str | None = None
    consecutive_failures: int = 0
    next_fire: datetime | None = None


@dataclass
class SchedulerAlert:
    """Alert surfaced when consecutive failures exceed threshold."""

    agent_id: str
    agent_name: str
    consecutive_failures: int
    threshold: int
    last_error: str | None
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))


# Process-global state
_states: dict[str, HeartbeatState] = {}
_alerts: dict[str, SchedulerAlert] = {}  # keyed by agent_id
_main_task: asyncio.Task | None = None


def _now() -> datetime:
    return datetime.now(UTC)


def get_all_states() -> dict[str, HeartbeatState]:
    """Return all heartbeat states (for the API)."""
    return _states


def get_alerts() -> list[SchedulerAlert]:
    """Return all active alerts."""
    return list(_alerts.values())


def clear_alert(agent_id: str) -> None:
    """Clear an alert for an agent (e.g. after a successful run)."""
    _alerts.pop(agent_id, None)


async def start_scheduler() -> None:
    """Start the heartbeat scheduler. Called once on server startup."""
    global _main_task
    _main_task = asyncio.create_task(_scheduler_loop())
    log.info("Heartbeat scheduler started")


async def stop_scheduler() -> None:
    """Stop the heartbeat scheduler. Called on server shutdown."""
    global _main_task
    # Cancel all per-agent tasks
    for state in _states.values():
        if state.task and not state.task.done():
            state.task.cancel()
    _states.clear()
    # Cancel the main loop
    if _main_task and not _main_task.done():
        _main_task.cancel()
        try:
            await _main_task
        except asyncio.CancelledError:
            pass
    log.info("Heartbeat scheduler stopped")


async def _scheduler_loop() -> None:
    """Main loop — periodically scans all agents and manages per-agent heartbeat tasks."""
    while True:
        try:
            await _sync_agents()
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("Error in scheduler loop")
        # Re-sync every 30 seconds (picks up config changes)
        await asyncio.sleep(30)


async def _sync_agents() -> None:
    """Sync the set of heartbeat tasks with the current agent configs."""
    from .models.agent import Agent

    async with async_session_factory() as db:
        result = await db.execute(select(Agent).where(Agent.enabled))
        agents = result.scalars().all()

        active_ids = set()
        for agent in agents:
            config = await get_active_config(db, agent.id)
            if config is None or not config.heartbeat.enabled:
                continue
            if not config.heartbeat.task_prompt.strip():
                continue

            active_ids.add(agent.id)

            # Create task if not already running
            state = _states.get(agent.id)
            if state is None or state.task is None or state.task.done():
                state = HeartbeatState(agent_id=agent.id)
                _states[agent.id] = state
                state.task = asyncio.create_task(
                    _agent_heartbeat_loop(agent.id, state)
                )
                log.info("Started heartbeat for agent %s", agent.id)

        # Stop tasks for agents that no longer have heartbeat enabled
        for agent_id in list(_states.keys()):
            if agent_id not in active_ids:
                state = _states.pop(agent_id, None)
                if state and state.task and not state.task.done():
                    state.task.cancel()
                    log.info("Stopped heartbeat for agent %s", agent_id)


async def _agent_heartbeat_loop(agent_id: str, state: HeartbeatState) -> None:
    """Per-agent heartbeat loop — fires at the configured interval."""
    while True:
        # Read the current config (may have been updated)
        async with async_session_factory() as db:
            config = await get_active_config(db, agent_id)
            if config is None or not config.heartbeat.enabled:
                return
            hb = config.heartbeat
            interval_sec = max(60, hb.interval_minutes * 60)  # min 1 minute
            task_prompt = hb.task_prompt
            threshold = hb.consecutive_failure_threshold
            agent = await get_agent(db, agent_id)
            agent_name = agent.name if agent else agent_id

        # Wait for the interval
        state.next_fire = datetime.fromtimestamp(
            _now().timestamp() + interval_sec, tz=UTC
        )
        await asyncio.sleep(interval_sec)

        # Fire the heartbeat
        state.last_fired = _now()
        log.info("Firing heartbeat for agent %s", agent_id)
        try:
            result = await run_agent(
                agent_id=agent_id,
                text=task_prompt,
                user_id="system",
                trigger="heartbeat",
                channel="heartbeat",
            )
            status = result.get("status", "failed")
            state.last_status = status
            state.last_error = result.get("error")

            if status == "completed":
                state.consecutive_failures = 0
                clear_alert(agent_id)
            else:
                state.consecutive_failures += 1
                if state.consecutive_failures >= threshold:
                    _alerts[agent_id] = SchedulerAlert(
                        agent_id=agent_id,
                        agent_name=agent_name,
                        consecutive_failures=state.consecutive_failures,
                        threshold=threshold,
                        last_error=state.last_error,
                    )
                    log.warning(
                        "Heartbeat for agent %s failed %d times (threshold=%d)",
                        agent_id,
                        state.consecutive_failures,
                        threshold,
                    )
        except asyncio.CancelledError:
            raise
        except Exception as e:
            state.last_status = "failed"
            state.last_error = str(e)
            state.consecutive_failures += 1
            if state.consecutive_failures >= threshold:
                _alerts[agent_id] = SchedulerAlert(
                    agent_id=agent_id,
                    agent_name=agent_name,
                    consecutive_failures=state.consecutive_failures,
                    threshold=threshold,
                    last_error=str(e),
                )
            log.exception("Heartbeat run failed for agent %s", agent_id)


async def fire_now(agent_id: str) -> dict:
    """Manually trigger a heartbeat run for an agent (without waiting for the interval)."""
    async with async_session_factory() as db:
        config = await get_active_config(db, agent_id)
        if config is None:
            raise ValueError(f"Agent not found: {agent_id}")
        if not config.heartbeat.task_prompt.strip():
            raise ValueError("No task prompt configured for heartbeat")
        task_prompt = config.heartbeat.task_prompt

    state = _states.get(agent_id)
    if state:
        state.last_fired = _now()

    result = await run_agent(
        agent_id=agent_id,
        text=task_prompt,
        user_id="system",
        trigger="heartbeat",
        channel="heartbeat",
    )

    if state:
        state.last_status = result.get("status")
        state.last_error = result.get("error")
        if result.get("status") == "completed":
            state.consecutive_failures = 0
            clear_alert(agent_id)
        else:
            state.consecutive_failures += 1

    return result
