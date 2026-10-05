"""Schedules API — versioned scheduled work (v0.2 W8).

Endpoints:
  GET    /api/schedules                    — list (managed heartbeats included, flagged)
  POST   /api/schedules                    — create (writes revision 1)
  GET    /api/schedules/{id}               — detail + current config + preview + history
  PUT    /api/schedules/{id}               — edit → new revision (active runs keep theirs)
  POST   /api/schedules/{id}/pause         — freeze next_fire_at
  POST   /api/schedules/{id}/resume        — re-enable; missed policy decides the gap
  POST   /api/schedules/{id}/duplicate     — copy config to a new disabled schedule
  DELETE /api/schedules/{id}               — archive (tombstone)
  POST   /api/schedules/{id}/run-now       — ad-hoc occurrence, real run
  POST   /api/schedules/{id}/test-run      — ad-hoc occurrence, scripted pipeline
  POST   /api/schedules/preview            — next N instants for a trigger+timezone
  GET    /api/schedules/{id}/occurrences   — paged history
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import scheduler as svc
from ..agent_service import get_active_config
from ..auth import require_operator
from ..db import get_db
from ..models.operator import Operator
from ..models.schedule import Schedule, ScheduleOccurrence, ScheduleRevision

router = APIRouter(prefix="/api/schedules", tags=["schedules"])


def _iso(dt) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.isoformat() + "Z"
    return dt.isoformat()


class TriggerSpec(BaseModel):
    kind: str  # once | interval | cron
    at: str | None = None
    every_seconds: float | None = None
    cron: str | None = None
    timezone: str | None = None


class FailurePolicy(BaseModel):
    mode: str = "no_retry"  # no_retry | bounded_retry
    max_attempts: int = 0
    backoff_seconds: int = 60


class PoliciesSpec(BaseModel):
    missed: str = "run_once"  # skip | run_once | catch_up
    overlap: str = "skip"  # skip | queue | cancel_previous | allow_parallel
    failure: FailurePolicy = FailurePolicy()


class ScheduleConfigRequest(BaseModel):
    """The revision payload — full replacement on PUT (config is small)."""

    agent_id: str
    name: str = ""
    enabled: bool = True
    trigger: TriggerSpec
    task_prompt: str
    policies: PoliciesSpec = PoliciesSpec()
    auto_approve: list[str] = []
    max_cost: float | None = None
    plan_revision_id: str | None = None
    model_override: dict[str, str] | None = None
    skill: str | None = None


def _cfg_dict(req: ScheduleConfigRequest) -> dict:
    return {
        "trigger": req.trigger.model_dump(exclude_none=True),
        "task_prompt": req.task_prompt,
        "policies": req.policies.model_dump(),
        "auto_approve": req.auto_approve,
        "limits": {"max_cost": req.max_cost},
        "plan_revision_id": req.plan_revision_id,
        "model_override": req.model_override,
        "skill": req.skill,
    }


def _schedule_out(sched: Schedule, rev: ScheduleRevision | None, agent_name: str) -> dict:
    cfg = svc._rev_config(rev) if rev else {}
    return {
        "id": sched.id,
        "agent_id": sched.agent_id,
        "agent_name": agent_name,
        "name": sched.name,
        "enabled": sched.enabled,
        "managed": sched.managed,
        "revision_number": rev.revision_number if rev else 0,
        "trigger": cfg.get("trigger"),
        "task_prompt": cfg.get("task_prompt"),
        "policies": cfg.get("policies"),
        "auto_approve": cfg.get("auto_approve") or [],
        "max_cost": (cfg.get("limits") or {}).get("max_cost"),
        "plan_revision_id": cfg.get("plan_revision_id"),
        "model_override": cfg.get("model_override"),
        "skill": cfg.get("skill"),
        "next_fire_at": _iso(sched.next_fire_at),
        "last_fired_at": _iso(sched.last_fired_at),
        "last_status": sched.last_status,
        "last_error": sched.last_error,
        "consecutive_failures": sched.consecutive_failures,
        "archived": sched.archived_at is not None,
        "created_at": _iso(sched.created_at),
    }


def _occurrence_out(occ: ScheduleOccurrence) -> dict:
    return {
        "id": occ.id,
        "schedule_id": occ.schedule_id,
        "revision_id": occ.revision_id,
        "run_id": occ.run_id,
        "scheduled_for": _iso(occ.scheduled_for),
        "status": occ.status,
        "attempt": occ.attempt,
        "retry_of": occ.retry_of,
        "started_at": _iso(occ.started_at),
        "finished_at": _iso(occ.finished_at),
        "error": occ.error,
    }


async def _get_schedule(db: AsyncSession, schedule_id: str) -> Schedule:
    sched = await db.get(Schedule, schedule_id)
    if sched is None or sched.archived_at is not None:
        raise HTTPException(status_code=404, detail="Schedule not found")
    return sched


def _reject_managed(sched: Schedule) -> None:
    if sched.managed:
        raise HTTPException(
            status_code=400,
            detail="Managed schedule — edit it via the heartbeat config",
        )


async def _agent_name(db: AsyncSession, agent_id: str) -> str:
    config = await get_active_config(db, agent_id)
    return config.name if config else agent_id


@router.get("")
async def list_schedules(
    operator: Operator = Depends(require_operator),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    result = await db.execute(
        select(Schedule).where(Schedule.archived_at.is_(None)).order_by(Schedule.created_at.desc())
    )
    out = []
    for sched in result.scalars().all():
        rev = await svc.current_revision(db, sched)
        out.append(_schedule_out(sched, rev, await _agent_name(db, sched.agent_id)))
    return out


@router.post("", status_code=201)
async def create_schedule(
    req: ScheduleConfigRequest,
    operator: Operator = Depends(require_operator),
    db: AsyncSession = Depends(get_db),
) -> dict:
    if await get_active_config(db, req.agent_id) is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    cfg = _cfg_dict(req)
    if errors := svc.validate_config(cfg):
        raise HTTPException(status_code=400, detail=errors)

    sched = Schedule(agent_id=req.agent_id, name=req.name or "Schedule", enabled=req.enabled)
    db.add(sched)
    await db.flush()
    rev = await svc.write_revision(db, sched, cfg, change_summary="created")
    sched.next_fire_at = svc.next_fire(cfg["trigger"], svc._now()) if sched.enabled else None
    await db.commit()
    return _schedule_out(sched, rev, await _agent_name(db, sched.agent_id))


@router.get("/{schedule_id}")
async def get_schedule(
    schedule_id: str,
    operator: Operator = Depends(require_operator),
    db: AsyncSession = Depends(get_db),
) -> dict:
    sched = await _get_schedule(db, schedule_id)
    rev = await svc.current_revision(db, sched)
    out = _schedule_out(sched, rev, await _agent_name(db, sched.agent_id))
    if rev is not None:
        cfg = svc._rev_config(rev)
        out["preview"] = svc.preview_occurrences(cfg["trigger"], 5)
    result = await db.execute(
        select(ScheduleOccurrence)
        .where(ScheduleOccurrence.schedule_id == sched.id)
        .order_by(ScheduleOccurrence.scheduled_for.desc())
        .limit(20)
    )
    out["occurrences"] = [_occurrence_out(o) for o in result.scalars().all()]
    return out


@router.put("/{schedule_id}")
async def update_schedule(
    schedule_id: str,
    req: ScheduleConfigRequest,
    operator: Operator = Depends(require_operator),
    db: AsyncSession = Depends(get_db),
) -> dict:
    sched = await _get_schedule(db, schedule_id)
    _reject_managed(sched)
    cfg = _cfg_dict(req)
    if errors := svc.validate_config(cfg):
        raise HTTPException(status_code=400, detail=errors)

    rev = await svc.current_revision(db, sched)
    trigger_changed = rev is None or svc._rev_config(rev).get("trigger") != cfg["trigger"]
    if rev is None or svc._rev_config(rev) != cfg:
        rev = await svc.write_revision(db, sched, cfg, change_summary="edited")
    sched.name = req.name or sched.name
    was_enabled = sched.enabled
    sched.enabled = req.enabled
    if not req.enabled:
        pass  # next_fire_at stays frozen — resume computes the gap from it
    elif trigger_changed:
        # New trigger → fresh anchor; sweeping old-trigger instants is meaningless
        sched.next_fire_at = svc.next_fire(cfg["trigger"], svc._now())
    elif not was_enabled:
        # Resume under the same trigger — the missed policy decides the gap
        await svc._sweep_schedule(db, sched, svc._now())
    await db.commit()
    return _schedule_out(sched, rev, await _agent_name(db, sched.agent_id))


@router.post("/{schedule_id}/pause")
async def pause_schedule(
    schedule_id: str,
    operator: Operator = Depends(require_operator),
    db: AsyncSession = Depends(get_db),
) -> dict:
    sched = await _get_schedule(db, schedule_id)
    _reject_managed(sched)
    sched.enabled = False
    await db.commit()
    return {"id": sched.id, "enabled": False}


@router.post("/{schedule_id}/resume")
async def resume_schedule(
    schedule_id: str,
    operator: Operator = Depends(require_operator),
    db: AsyncSession = Depends(get_db),
) -> dict:
    sched = await _get_schedule(db, schedule_id)
    _reject_managed(sched)
    sched.enabled = True
    # Frozen next_fire_at + now define the gap — the missed policy applies
    await svc._sweep_schedule(db, sched, svc._now())
    await db.commit()
    rev = await svc.current_revision(db, sched)
    return _schedule_out(sched, rev, await _agent_name(db, sched.agent_id))


@router.post("/{schedule_id}/duplicate")
async def duplicate_schedule(
    schedule_id: str,
    operator: Operator = Depends(require_operator),
    db: AsyncSession = Depends(get_db),
) -> dict:
    sched = await _get_schedule(db, schedule_id)
    rev = await svc.current_revision(db, sched)
    clone = Schedule(
        agent_id=sched.agent_id,
        name=f"{sched.name} copy",
        enabled=False,  # duplicates start off — arming is a deliberate act
    )
    db.add(clone)
    await db.flush()
    clone_rev = None
    if rev is not None:
        await svc.write_revision(
            db, clone, svc._rev_config(rev), change_summary=f"duplicated from {sched.id}"
        )
        clone_rev = await svc.current_revision(db, clone)
    await db.commit()
    return _schedule_out(clone, clone_rev, await _agent_name(db, clone.agent_id))


@router.delete("/{schedule_id}")
async def delete_schedule(
    schedule_id: str,
    operator: Operator = Depends(require_operator),
    db: AsyncSession = Depends(get_db),
) -> dict:
    sched = await _get_schedule(db, schedule_id)
    _reject_managed(sched)
    from datetime import UTC, datetime

    sched.enabled = False
    sched.next_fire_at = None
    sched.archived_at = datetime.now(UTC)
    await db.commit()
    return {"id": sched.id, "archived": True}


@router.post("/{schedule_id}/run-now")
async def run_schedule_now(
    schedule_id: str,
    operator: Operator = Depends(require_operator),
    db: AsyncSession = Depends(get_db),
) -> dict:
    sched = await _get_schedule(db, schedule_id)
    # Release the request session's read snapshot before the (long) run —
    # an open txn pins WAL frames for the run's whole duration.
    await db.commit()
    try:
        return await svc.run_now(sched.id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/{schedule_id}/test-run")
async def test_run_schedule(
    schedule_id: str,
    operator: Operator = Depends(require_operator),
    db: AsyncSession = Depends(get_db),
) -> dict:
    sched = await _get_schedule(db, schedule_id)
    await db.commit()
    try:
        return await svc.run_now(sched.id, is_test=True)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


class PreviewRequest(BaseModel):
    trigger: TriggerSpec
    count: int = 5


@router.post("/preview")
async def preview(
    req: PreviewRequest,
    operator: Operator = Depends(require_operator),
) -> dict:
    cfg = {"trigger": req.trigger.model_dump(exclude_none=True)}
    errors = svc.validate_config(
        {**cfg, "task_prompt": "preview"}  # trigger-only validation
    )
    errors = [e for e in errors if not e.startswith("task_prompt")]
    if errors:
        raise HTTPException(status_code=400, detail=errors)
    return {
        "timezone": req.trigger.timezone or "UTC",
        "occurrences": svc.preview_occurrences(cfg["trigger"], min(max(1, req.count), 50)),
    }


@router.get("/{schedule_id}/occurrences")
async def list_occurrences(
    schedule_id: str,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    operator: Operator = Depends(require_operator),
    db: AsyncSession = Depends(get_db),
) -> dict:
    sched = await _get_schedule(db, schedule_id)
    result = await db.execute(
        select(ScheduleOccurrence)
        .where(ScheduleOccurrence.schedule_id == sched.id)
        .order_by(ScheduleOccurrence.scheduled_for.desc())
        .limit(limit)
        .offset(offset)
    )
    total = await db.scalar(
        select(func.count())
        .select_from(ScheduleOccurrence)
        .where(ScheduleOccurrence.schedule_id == sched.id)
    )
    return {
        "occurrences": [_occurrence_out(o) for o in result.scalars().all()],
        "total": total,
    }
