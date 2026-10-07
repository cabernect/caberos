"""Scheduler v2 — persistent, policy-driven schedules (W8).

One tick loop materializes occurrences from persisted ``next_fire_at``
instants, so restart/sleep recovery is a DB read, not in-memory guesswork.
Each occurrence pins the schedule revision it was launched with; edits
create new revisions and never mutate active work.

Trigger kinds: once | interval | cron (IANA timezone stored separately —
croniter computes aware instants; DST ambiguous/nonexistent wall times
collapse to one execution each).

Policies:
  missed:  skip | run_once | catch_up   — what a late engine does with a gap
  overlap: skip | queue | cancel_previous | allow_parallel
  failure: no_retry | bounded_retry(max_attempts, backoff_seconds)

The agent heartbeat is a facade over a managed Schedule (managed="heartbeat")
— the existing /api/scheduler/heartbeat endpoints and UI keep working.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from croniter import croniter
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from . import db as _db_module
from .agent_service import get_active_config, get_agent
from .models.schedule import Schedule, ScheduleOccurrence, ScheduleRevision
from .runner import run_agent

log = logging.getLogger("agentos.scheduler")

TICK_SECONDS = 15.0
CATCH_UP_MAX = 25  # cap materialized missed occurrences per sweep
DEFAULT_TZ = "UTC"

_main_task: asyncio.Task | None = None
_running_tasks: dict[str, asyncio.Task] = {}  # occurrence_id -> run task


def _now() -> datetime:
    return datetime.now(UTC)


def _as_utc(dt: datetime) -> datetime:
    """SQLite reads DateTime back naive; instants here are always UTC."""
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)


def canonical_config(cfg: dict) -> str:
    return json.dumps(cfg, sort_keys=True, separators=(",", ":"))


def _content_hash(cfg: dict) -> str:
    return hashlib.sha256(canonical_config(cfg).encode()).hexdigest()


def _rev_config(rev: ScheduleRevision) -> dict:
    return json.loads(rev.config)


def default_policies() -> dict:
    """The spec's safe defaults: run-once after resume, skip overlap, bounded retry."""
    return {
        "missed": "run_once",
        "overlap": "skip",
        "failure": {"mode": "no_retry", "max_attempts": 0, "backoff_seconds": 60},
    }


def validate_config(cfg: dict) -> list[str]:
    """Return validation errors for a revision config; [] means valid."""
    errors: list[str] = []
    trigger = cfg.get("trigger") or {}
    kind = trigger.get("kind")
    if kind == "once":
        try:
            at = datetime.fromisoformat(str(trigger.get("at", "")).replace("Z", "+00:00"))
            _as_utc(at)
        except ValueError:
            errors.append("trigger.at must be an ISO-8601 datetime")
    elif kind == "interval":
        secs = trigger.get("every_seconds")
        if not isinstance(secs, (int, float)) or secs < 60:
            errors.append("trigger.every_seconds must be a number >= 60")
    elif kind == "cron":
        expr = str(trigger.get("cron") or "")
        if not croniter.is_valid(expr):
            errors.append(f"invalid cron expression: {expr!r}")
    else:
        errors.append("trigger.kind must be once|interval|cron")

    tz_name = trigger.get("timezone") or DEFAULT_TZ
    try:
        ZoneInfo(str(tz_name))
    except Exception:
        errors.append(f"unknown timezone: {tz_name!r}")

    policies = cfg.get("policies") or {}
    if policies.get("missed") not in ("skip", "run_once", "catch_up", None):
        errors.append("policies.missed must be skip|run_once|catch_up")
    if policies.get("overlap") not in ("skip", "queue", "cancel_previous", "allow_parallel", None):
        errors.append("policies.overlap must be skip|queue|cancel_previous|allow_parallel")
    failure = policies.get("failure") or {}
    if failure.get("mode") not in ("no_retry", "bounded_retry", None):
        errors.append("policies.failure.mode must be no_retry|bounded_retry")
    if failure.get("mode") == "bounded_retry":
        if int(failure.get("max_attempts") or 0) < 1:
            errors.append("policies.failure.max_attempts must be >= 1 for bounded_retry")

    if not str(cfg.get("task_prompt") or "").strip():
        errors.append("task_prompt is required")
    return errors


# -- trigger math -------------------------------------------------------------


def next_fire(trigger: dict, after: datetime) -> datetime | None:
    """Next UTC instant strictly after ``after`` for the given trigger."""
    after = _as_utc(after)
    kind = trigger.get("kind")
    if kind == "once":
        at = _as_utc(datetime.fromisoformat(str(trigger["at"]).replace("Z", "+00:00")))
        return at if at > after else None
    if kind == "interval":
        return after + _interval_delta(trigger)
    if kind == "cron":
        tz = ZoneInfo(str(trigger.get("timezone") or DEFAULT_TZ))
        itr = croniter(str(trigger["cron"]), after.astimezone(tz))
        nxt = itr.get_next(datetime)
        # DST semantics: a nonexistent wall time fires once at the first valid
        # instant after the gap (croniter shifts forward). An ambiguous wall
        # time must also execute only once — croniter yields both fold instants,
        # so if the candidate has the same local wall-clock time as the anchor
        # we are on the fold's second pass: skip to the following instant.
        if nxt.astimezone(tz).replace(tzinfo=None) == after.astimezone(tz).replace(tzinfo=None):
            nxt = itr.get_next(datetime)
        return _as_utc(nxt)
    return None


def _interval_delta(trigger: dict):
    return timedelta(seconds=float(trigger["every_seconds"]))


def preview_occurrences(trigger: dict, count: int = 5, after: datetime | None = None) -> list[str]:
    """Compute upcoming UTC instants for the preview/DST-check API."""
    out: list[str] = []
    cursor = _as_utc(after) if after else _now()
    for _ in range(count):
        nxt = next_fire(trigger, cursor)
        if nxt is None:
            break
        out.append(nxt.isoformat())
        cursor = nxt
    return out


# -- revision helpers ---------------------------------------------------------


async def write_revision(
    db: AsyncSession, schedule: Schedule, cfg: dict, change_summary: str | None = None
) -> ScheduleRevision:
    """Append a new immutable revision and point the schedule at it."""
    result = await db.execute(
        select(func.max(ScheduleRevision.revision_number)).where(
            ScheduleRevision.schedule_id == schedule.id
        )
    )
    number = (result.scalar() or 0) + 1
    rev = ScheduleRevision(
        schedule_id=schedule.id,
        revision_number=number,
        content_hash=_content_hash(cfg),
        change_summary=change_summary,
        config=canonical_config(cfg),
    )
    db.add(rev)
    await db.flush()
    schedule.current_revision_id = rev.id
    await db.flush()
    return rev


async def current_revision(db: AsyncSession, schedule: Schedule) -> ScheduleRevision | None:
    if not schedule.current_revision_id:
        return None
    result = await db.execute(
        select(ScheduleRevision).where(ScheduleRevision.id == schedule.current_revision_id)
    )
    return result.scalar_one_or_none()


async def get_managed_heartbeat(db: AsyncSession, agent_id: str) -> Schedule | None:
    result = await db.execute(
        select(Schedule).where(Schedule.agent_id == agent_id, Schedule.managed == "heartbeat")
    )
    return result.scalar_one_or_none()


async def sync_heartbeat_schedule(db: AsyncSession, agent_id: str) -> Schedule:
    """Materialize/maintain the managed schedule backing an agent's heartbeat.

    The heartbeat config on AgentConfig stays the authoring surface; this
    projects it onto the schedule engine so one engine owns all timing.
    """
    config = await get_active_config(db, agent_id)
    if config is None:
        raise ValueError(f"Agent not found: {agent_id}")
    hb = config.heartbeat

    cfg = {
        "trigger": {"kind": "interval", "every_seconds": max(60, hb.interval_minutes * 60)},
        "task_prompt": hb.task_prompt,
        "policies": default_policies(),
        "auto_approve": [],
        "limits": {"max_cost": hb.max_cost_per_heartbeat},
    }

    sched = await get_managed_heartbeat(db, agent_id)
    is_new = sched is None
    trigger_changed = is_new
    if is_new:
        sched = Schedule(
            agent_id=agent_id, name="Heartbeat", enabled=hb.enabled, managed="heartbeat"
        )
        db.add(sched)
        await db.flush()
        await write_revision(db, sched, cfg, change_summary="heartbeat config")
    else:
        rev = await current_revision(db, sched)
        if rev is None or _content_hash(_rev_config(rev)) != _content_hash(cfg):
            trigger_changed = rev is not None and _rev_config(rev).get("trigger") != cfg["trigger"]
            await write_revision(db, sched, cfg, change_summary="heartbeat config")
        sched.enabled = hb.enabled

    if sched.enabled:
        # Re-anchor only on create, trigger change, or a lost instant — a
        # restart must keep the persisted fire time so the missed-run sweep
        # sees the true gap.
        if trigger_changed or sched.next_fire_at is None:
            sched.next_fire_at = next_fire(cfg["trigger"], _now())
    else:
        sched.next_fire_at = None
    await db.flush()
    return sched


# -- engine -------------------------------------------------------------------


async def start_scheduler() -> None:
    global _main_task
    for step in (_migrate_heartbeats, _reconcile_stale_occurrences, _sweep_missed):
        try:
            await step()
        except Exception:
            log.exception("scheduler startup step %s failed", step.__name__)
    _main_task = asyncio.create_task(_loop())
    log.info("Scheduler started")


async def stop_scheduler() -> None:
    global _main_task
    for task in _running_tasks.values():
        if not task.done():
            task.cancel()
    if _main_task and not _main_task.done():
        _main_task.cancel()
        try:
            await _main_task
        except asyncio.CancelledError:
            pass
    _running_tasks.clear()
    log.info("Scheduler stopped")


async def _migrate_heartbeats() -> None:
    """Project enabled heartbeat configs onto managed schedules at startup."""
    from .models.agent import Agent

    async with _db_module.async_session_factory() as db:
        result = await db.execute(select(Agent).where(Agent.enabled))
        for agent in result.scalars().all():
            config = await get_active_config(db, agent.id)
            if config is None:
                continue
            # Every agent gets a managed heartbeat projection (disabled rows
            # included) — the Schedules surface lists all agents, matching the
            # heartbeat tab's mental model. Sync is content-hash-gated: a no-op
            # when unchanged, so the persisted next_fire_at survives for the
            # missed-run sweep.
            await sync_heartbeat_schedule(db, agent.id)
        await db.commit()


async def _reconcile_stale_occurrences() -> None:
    """A dead process leaves running occurrences orphaned — close them honestly."""
    async with _db_module.async_session_factory() as db:
        result = await db.execute(
            select(ScheduleOccurrence).where(ScheduleOccurrence.status == "running")
        )
        stale = result.scalars().all()
        for occ in stale:
            occ.status = "cancelled"
            occ.finished_at = _now()
            occ.error = "Gateway restarted during execution"
        if stale:
            await db.commit()
            log.info("Reconciled %d stale running occurrence(s)", len(stale))


async def _loop() -> None:
    while True:
        try:
            await _tick(_now())
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("Scheduler tick failed")
        await asyncio.sleep(TICK_SECONDS)


async def _tick(now: datetime) -> None:
    # Two-phase: mutate + commit first, then spawn run tasks — _execute reads
    # its occurrence in a fresh session, so the rows must be committed first.
    launch_ids: list[str] = []
    async with _db_module.async_session_factory() as db:
        # 1. Drain due queued occurrences whose schedule has no running work.
        #    Retries queue with a future scheduled_for (backoff) — the time
        #    filter keeps them parked until their instant arrives.
        result = await db.execute(
            select(ScheduleOccurrence)
            .where(
                ScheduleOccurrence.status == "queued",
                ScheduleOccurrence.scheduled_for <= now,
            )
            .order_by(ScheduleOccurrence.scheduled_for)
        )
        for occ in result.scalars().all():
            if await _running_occurrence(db, occ.schedule_id) is not None:
                continue
            occ.status = "running"
            occ.started_at = now
            launch_ids.append(occ.id)

        # 2. Fire due schedules
        result = await db.execute(
            select(Schedule).where(
                Schedule.enabled.is_(True),
                Schedule.next_fire_at.is_not(None),
                Schedule.next_fire_at <= now,
            )
        )
        for sched in result.scalars().all():
            occ = await _fire_due(db, sched, now)
            if occ is not None:
                launch_ids.append(occ.id)
        await db.commit()

    for occ_id in launch_ids:
        _launch(occ_id)


async def _running_occurrence(db: AsyncSession, schedule_id: str) -> ScheduleOccurrence | None:
    result = await db.execute(
        select(ScheduleOccurrence).where(
            ScheduleOccurrence.schedule_id == schedule_id,
            ScheduleOccurrence.status == "running",
        )
    )
    return result.scalars().first()


async def _open_occurrence(db: AsyncSession, schedule_id: str) -> ScheduleOccurrence | None:
    result = await db.execute(
        select(ScheduleOccurrence)
        .where(
            ScheduleOccurrence.schedule_id == schedule_id,
            ScheduleOccurrence.status.in_(("queued", "running")),
        )
        .order_by(ScheduleOccurrence.status.desc())  # running before queued
    )
    return result.scalars().first()


async def _fire_due(db: AsyncSession, sched: Schedule, now: datetime) -> ScheduleOccurrence | None:
    """Handle one schedule whose next_fire_at is due. Returns the occurrence
    to launch, or None when the overlap policy consumed the instant."""
    rev = await current_revision(db, sched)
    if rev is None:
        sched.next_fire_at = None
        return None
    cfg = _rev_config(rev)
    trigger = cfg["trigger"]
    policies = {**default_policies(), **(cfg.get("policies") or {})}
    due_instant = _as_utc(sched.next_fire_at)

    open_occ = await _open_occurrence(db, sched.id)
    if open_occ is not None:
        mode = policies["overlap"]
        if mode == "skip":
            await _record_occurrence(db, sched, rev, due_instant, status="skipped_overlap")
            sched.next_fire_at = next_fire(trigger, due_instant)
            return None
        if mode == "queue":
            await _record_occurrence(db, sched, rev, due_instant, status="queued")
            sched.next_fire_at = next_fire(trigger, due_instant)
            return None
        if mode == "cancel_previous":
            await _cancel_occurrence(db, open_occ)
        # allow_parallel falls through to firing

    occ = await _record_occurrence(db, sched, rev, due_instant, status="running")
    occ.started_at = now
    sched.last_fired_at = now
    sched.next_fire_at = next_fire(trigger, due_instant)
    return occ


async def _record_occurrence(
    db: AsyncSession,
    sched: Schedule,
    rev: ScheduleRevision,
    scheduled_for: datetime,
    *,
    status: str,
    attempt: int = 1,
    retry_of: str | None = None,
    error: str | None = None,
) -> ScheduleOccurrence:
    occ = ScheduleOccurrence(
        schedule_id=sched.id,
        revision_id=rev.id,
        scheduled_for=scheduled_for,
        status=status,
        attempt=attempt,
        retry_of=retry_of,
        error=error,
    )
    db.add(occ)
    await db.flush()
    return occ


async def _cancel_occurrence(db: AsyncSession, occ: ScheduleOccurrence) -> None:
    """cancel_previous overlap — stop the run if it's still ours, then mark."""
    task = _running_tasks.get(occ.id)
    if task is not None and not task.done():
        task.cancel()
    elif occ.run_id:
        from .run_manager import stop_run

        await stop_run(occ.run_id)
    occ.status = "cancelled"
    occ.finished_at = _now()
    occ.error = occ.error or "cancelled by overlap policy"
    await db.flush()


def _launch(occurrence_id: str) -> None:
    """Spawn the run task for a committed running occurrence."""
    _running_tasks[occurrence_id] = asyncio.create_task(_execute(occurrence_id))


async def _execute(occurrence_id: str, *, is_test: bool = False) -> None:
    """Run an occurrence, holding a DB connection only for short phases.

    Phase 1 loads the occurrence/schedule/revision and releases its session —
    holding it across run_agent would occupy a pool connection (and a read
    txn pinning WAL frames) for the run's whole duration. Phase 2 writes the
    outcome on a fresh session, so a cancelled or crashed run still marks the
    occurrence instead of orphaning it at "running".
    """
    # Phase 1 — load, validate, release.
    try:
        async with _db_module.async_session_factory() as db:
            occ = await db.get(ScheduleOccurrence, occurrence_id)
            if occ is None or occ.status != "running":
                return
            sched = await db.get(Schedule, occ.schedule_id)
            rev = await db.get(ScheduleRevision, occ.revision_id)
            if sched is None or rev is None:
                return
            cfg = _rev_config(rev)
            schedule_id, agent_id, managed = sched.id, sched.agent_id, sched.managed
            revision_id = rev.id
    except Exception:
        log.exception("Scheduled run preamble failed (occurrence %s)", occurrence_id)
        await _mark_occurrence_failed(occurrence_id, "scheduler internal error")
        _running_tasks.pop(occurrence_id, None)
        return

    trigger = "heartbeat" if managed == "heartbeat" else "schedule"
    run_id: str | None = None
    cancelled = False
    try:
        result = await run_agent(
            agent_id=agent_id,
            text=cfg.get("task_prompt", ""),
            user_id="system",
            is_test=is_test,
            trigger=trigger,
            channel=trigger,
            new_session=True,
            model_override=cfg.get("model_override"),
            skill=cfg.get("skill"),
            schedule_context={
                "schedule_id": schedule_id,
                "revision_id": revision_id,
                "occurrence_id": occurrence_id,
                "auto_approve": cfg.get("auto_approve") or [],
                "max_cost": (cfg.get("limits") or {}).get("max_cost"),
                "plan_revision_id": cfg.get("plan_revision_id"),
            },
        )
        status = result.get("status", "failed")
        run_id = result.get("run_id") or None
        occ_status = "completed" if status == "completed" else "failed"
        occ_error = result.get("error")
    except asyncio.CancelledError:
        occ_status, occ_error, cancelled = "cancelled", "cancelled", True
    except Exception as e:
        log.exception("Scheduled run failed (schedule %s)", schedule_id)
        occ_status, occ_error = "failed", str(e)
    finally:
        _running_tasks.pop(occurrence_id, None)

    # Phase 2 — persist outcome, counters, retry/notification on a fresh session.
    try:
        async with _db_module.async_session_factory() as db:
            occ = await db.get(ScheduleOccurrence, occurrence_id)
            sched = await db.get(Schedule, schedule_id)
            if occ is not None:
                occ.run_id = run_id
                occ.status = occ_status
                # Preserve a materialization note (e.g. "N earlier occurrence(s)
                # skipped" from run_once) when the run itself has no error.
                occ.error = occ_error or occ.error
                occ.finished_at = _now()
            if sched is not None:
                sched.last_status = occ_status
                sched.last_error = occ_error or (occ.error if occ else None)
                if occ_status == "completed":
                    sched.consecutive_failures = 0
                else:
                    sched.consecutive_failures += 1
                    if occ is not None:
                        await _maybe_retry(db, sched, occ, cfg)
                    await _notify_failure(db, sched)
            await db.commit()
    except Exception:
        log.exception("Failed to persist occurrence outcome (%s)", occurrence_id)

    if cancelled:
        raise asyncio.CancelledError()


async def _mark_occurrence_failed(occurrence_id: str, error: str) -> None:
    """Best-effort failure mark when _execute dies before its run starts."""
    try:
        async with _db_module.async_session_factory() as db:
            occ = await db.get(ScheduleOccurrence, occurrence_id)
            if occ is not None and occ.status == "running":
                occ.status = "failed"
                occ.error = error
                occ.finished_at = _now()
                await db.commit()
    except Exception:
        log.exception("Failed to mark occurrence %s as failed", occurrence_id)


async def _maybe_retry(
    db: AsyncSession, sched: Schedule, occ: ScheduleOccurrence, cfg: dict
) -> None:
    failure = (cfg.get("policies") or {}).get("failure") or {}
    if failure.get("mode") != "bounded_retry":
        return
    max_attempts = int(failure.get("max_attempts") or 0)
    if occ.attempt >= max_attempts:
        return
    backoff = float(failure.get("backoff_seconds") or 60) * occ.attempt
    rev = await db.get(ScheduleRevision, occ.revision_id)
    await _record_occurrence(
        db,
        sched,
        rev,
        _now() + timedelta(seconds=backoff),
        status="queued",
        attempt=occ.attempt + 1,
        retry_of=occ.id,
    )


async def _notify_failure(db: AsyncSession, sched: Schedule) -> None:
    threshold = await _failure_threshold(db, sched)
    if sched.consecutive_failures != threshold:
        return
    from .notifications import create_notification

    agent = await get_agent(db, sched.agent_id)
    await create_notification(
        db,
        notification_type="schedule_failed",
        severity="warning",
        title=f"Schedule failed {threshold}× — {sched.name}",
        message=sched.last_error or "scheduled run failed",
        action_path="/scheduler",
        entity_id=sched.id,
        entity_type="schedule",
        agent_id=sched.agent_id,
        # Deterministic daily key — an identical error on a NEW streak still
        # notifies (the content-hash fallback would dedup it away).
        event_id=f"schedule_failed:{sched.id}:{_now().date().isoformat()}",
    )
    log.warning(
        "Schedule %s (%s) failed %d times (threshold=%d) — %s",
        sched.id,
        agent.name if agent else sched.agent_id,
        sched.consecutive_failures,
        threshold,
        sched.last_error,
    )


async def _failure_threshold(db: AsyncSession, sched: Schedule) -> int:
    if sched.managed == "heartbeat":
        config = await get_active_config(db, sched.agent_id)
        if config is not None:
            return config.heartbeat.consecutive_failure_threshold
    return 3


# -- missed-run sweep (startup / resume) ---------------------------------------


async def _sweep_missed(now: datetime | None = None) -> None:
    """Apply the missed-run policy to instants that passed while we couldn't fire.

    next_fire_at < now means the engine never observed the instant — gateway
    down, machine asleep, or the schedule was paused. Queued retries are
    excluded (their scheduled_for is a retry time, not a missed fire).
    """
    now = now or _now()
    async with _db_module.async_session_factory() as db:
        result = await db.execute(
            select(Schedule).where(
                Schedule.enabled.is_(True),
                Schedule.next_fire_at.is_not(None),
                Schedule.next_fire_at < now,
            )
        )
        for sched in result.scalars().all():
            await _sweep_schedule(db, sched, now)
        await db.commit()


async def _sweep_schedule(db: AsyncSession, sched: Schedule, now: datetime) -> None:
    rev = await current_revision(db, sched)
    if rev is None:
        return
    cfg = _rev_config(rev)
    trigger = cfg["trigger"]
    if sched.next_fire_at is None:
        # No anchor (created disabled / trigger exhausted) — nothing to sweep,
        # resume just starts from the next fresh instant.
        sched.next_fire_at = next_fire(trigger, now)
        await db.flush()
        return
    policies = {**default_policies(), **(cfg.get("policies") or {})}
    missed = policies["missed"]

    # Collect missed instants (bounded)
    instants: list[datetime] = []
    cursor = _as_utc(sched.next_fire_at)
    while cursor < now and len(instants) < CATCH_UP_MAX:
        instants.append(cursor)
        cursor = next_fire(trigger, cursor) or now
    if trigger.get("kind") == "once" and instants:
        instants = instants[:1]

    if not instants:
        return

    if missed == "skip":
        await _record_occurrence(
            db,
            sched,
            rev,
            instants[-1],
            status="skipped_missed",
            error=f"{len(instants)} occurrence(s) missed while inactive",
        )
    elif missed == "run_once":
        occ = await _record_occurrence(
            db,
            sched,
            rev,
            instants[-1],
            status="queued",
        )
        if len(instants) > 1:
            occ.error = f"{len(instants) - 1} earlier occurrence(s) skipped"
    elif missed == "catch_up":
        for instant in instants:
            await _record_occurrence(db, sched, rev, instant, status="queued")

    # cursor is the first instant >= now (keeps interval phase); if the
    # trigger is exhausted (once already fired), there is no next.
    sched.next_fire_at = cursor if cursor > now else next_fire(trigger, now)
    await db.flush()


# -- manual actions ------------------------------------------------------------


async def run_now(schedule_id: str, *, is_test: bool = False) -> dict:
    """Materialize an ad-hoc occurrence and run it immediately."""
    async with _db_module.async_session_factory() as db:
        sched = await db.get(Schedule, schedule_id)
        if sched is None or sched.archived_at is not None:
            raise ValueError("Schedule not found")
        rev = await current_revision(db, sched)
        if rev is None:
            raise ValueError("Schedule has no revision")
        if not str(_rev_config(rev).get("task_prompt") or "").strip():
            raise ValueError("Schedule has no task prompt")
        occ = await _record_occurrence(
            db,
            sched,
            rev,
            _now(),
            status="running",
        )
        occ.started_at = _now()
        await db.commit()
        occ_id = occ.id

    await _execute(occ_id, is_test=is_test)
    async with _db_module.async_session_factory() as db:
        occ = await db.get(ScheduleOccurrence, occ_id)
        return {
            "run_id": occ.run_id,
            "status": occ.status,
            "error": occ.error,
        }


# -- heartbeat facade (keeps /api/scheduler/heartbeat working) ------------------


@dataclass
class HeartbeatState:
    agent_id: str
    last_fired: datetime | None = None
    last_status: str | None = None
    last_error: str | None = None
    consecutive_failures: int = 0
    next_fire: datetime | None = None


@dataclass
class SchedulerAlert:
    agent_id: str
    agent_name: str
    consecutive_failures: int
    threshold: int
    last_error: str | None
    timestamp: datetime = field(default_factory=_now)


async def heartbeat_states(db: AsyncSession, agent_ids: list[str]) -> dict[str, HeartbeatState]:
    """View of managed schedules in the old HeartbeatState shape."""
    if not agent_ids:
        return {}
    result = await db.execute(
        select(Schedule).where(Schedule.agent_id.in_(agent_ids), Schedule.managed == "heartbeat")
    )
    out: dict[str, HeartbeatState] = {}
    for sched in result.scalars().all():
        out[sched.agent_id] = HeartbeatState(
            agent_id=sched.agent_id,
            last_fired=sched.last_fired_at,
            last_status=sched.last_status,
            last_error=sched.last_error,
            consecutive_failures=sched.consecutive_failures,
            next_fire=sched.next_fire_at,
        )
    return out


async def get_alerts(db: AsyncSession) -> list[SchedulerAlert]:
    result = await db.execute(select(Schedule).where(Schedule.consecutive_failures > 0))
    alerts: list[SchedulerAlert] = []
    for sched in result.scalars().all():
        threshold = await _failure_threshold(db, sched)
        if sched.consecutive_failures < threshold:
            continue
        agent = await get_agent(db, sched.agent_id)
        alerts.append(
            SchedulerAlert(
                agent_id=sched.agent_id,
                agent_name=(agent.name if agent else sched.agent_id)
                + ("" if sched.managed == "heartbeat" else f" · {sched.name}"),
                consecutive_failures=sched.consecutive_failures,
                threshold=threshold,
                last_error=sched.last_error,
            )
        )
    return alerts


async def clear_alert(db: AsyncSession, agent_id: str) -> None:
    await db.execute(
        update(Schedule).where(Schedule.agent_id == agent_id).values(consecutive_failures=0)
    )
    await db.commit()


async def fire_now(agent_id: str) -> dict:
    """Heartbeat facade — run the managed schedule immediately."""
    async with _db_module.async_session_factory() as db:
        config = await get_active_config(db, agent_id)
        if config is None:
            raise ValueError(f"Agent not found: {agent_id}")
        if not config.heartbeat.task_prompt.strip():
            raise ValueError("No task prompt configured for heartbeat")
        sched = await sync_heartbeat_schedule(db, agent_id)
        await db.commit()
    return await run_now(sched.id)
