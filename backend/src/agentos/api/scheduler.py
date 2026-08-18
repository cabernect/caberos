"""Scheduler API — heartbeat configuration and status.

Endpoints:
  GET  /api/scheduler/heartbeat        — list all agents with heartbeat status
  PUT  /api/scheduler/heartbeat/{id}    — update heartbeat config for an agent
  POST /api/scheduler/heartbeat/{id}/fire — manually trigger a heartbeat now
  GET  /api/scheduler/alerts           — list active alerts (consecutive failures)
  POST /api/scheduler/alerts/{id}/clear — clear an alert
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import scheduler as scheduler_service
from ..agent_service import get_active_config, save_agent
from ..auth import require_operator
from ..db import get_db
from ..models.agent import Agent
from ..models.operator import Operator

router = APIRouter(prefix="/api/scheduler", tags=["scheduler"])


class UpdateHeartbeatRequest(BaseModel):
    enabled: bool | None = None
    interval_minutes: int | None = None
    task_prompt: str | None = None
    max_cost_per_heartbeat: float | None = None
    consecutive_failure_threshold: int | None = None


def _iso(dt) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.isoformat() + "Z"
    return dt.isoformat()


@router.get("/heartbeat")
async def list_heartbeat(
    operator: Operator = Depends(require_operator),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """List all agents with their heartbeat configuration and runtime status."""
    result = await db.execute(select(Agent).where(Agent.enabled).order_by(Agent.name))
    agents = result.scalars().all()

    states = scheduler_service.get_all_states()
    out = []
    for agent in agents:
        config = await get_active_config(db, agent.id)
        if config is None:
            continue
        hb = config.heartbeat
        state = states.get(agent.id)
        out.append(
            {
                "agent_id": agent.id,
                "agent_name": config.name,
                "enabled": hb.enabled,
                "interval_minutes": hb.interval_minutes,
                "task_prompt": hb.task_prompt,
                "max_cost_per_heartbeat": hb.max_cost_per_heartbeat,
                "consecutive_failure_threshold": hb.consecutive_failure_threshold,
                "last_fired": _iso(state.last_fired) if state else None,
                "last_status": state.last_status if state else None,
                "last_error": state.last_error if state else None,
                "consecutive_failures": state.consecutive_failures if state else 0,
                "next_fire": _iso(state.next_fire) if state else None,
            }
        )
    return out


@router.put("/heartbeat/{agent_id}")
async def update_heartbeat(
    agent_id: str,
    req: UpdateHeartbeatRequest,
    operator: Operator = Depends(require_operator),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Update heartbeat config for an agent. Only the heartbeat field is updated."""
    config = await get_active_config(db, agent_id)
    if config is None:
        raise HTTPException(status_code=404, detail="Agent not found")

    # Apply partial updates to the heartbeat config
    hb = config.heartbeat
    if req.enabled is not None:
        hb.enabled = req.enabled
    if req.interval_minutes is not None:
        hb.interval_minutes = req.interval_minutes
    if req.task_prompt is not None:
        hb.task_prompt = req.task_prompt
    if req.max_cost_per_heartbeat is not None:
        hb.max_cost_per_heartbeat = req.max_cost_per_heartbeat
    if req.consecutive_failure_threshold is not None:
        hb.consecutive_failure_threshold = req.consecutive_failure_threshold
    config.heartbeat = hb

    version = await save_agent(db, config)
    return {
        "agent_id": agent_id,
        "version": version.version_number,
        "heartbeat": hb.model_dump(),
    }


@router.post("/heartbeat/{agent_id}/fire")
async def fire_heartbeat(
    agent_id: str,
    operator: Operator = Depends(require_operator),
) -> dict:
    """Manually trigger a heartbeat run for an agent."""
    try:
        result = await scheduler_service.fire_now(agent_id)
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/alerts")
async def list_alerts(
    operator: Operator = Depends(require_operator),
) -> list[dict]:
    """List active scheduler alerts (consecutive heartbeat failures)."""
    alerts = scheduler_service.get_alerts()
    return [
        {
            "agent_id": a.agent_id,
            "agent_name": a.agent_name,
            "consecutive_failures": a.consecutive_failures,
            "threshold": a.threshold,
            "last_error": a.last_error,
            "timestamp": _iso(a.timestamp),
        }
        for a in alerts
    ]


@router.post("/alerts/{agent_id}/clear")
async def clear_alert(
    agent_id: str,
    operator: Operator = Depends(require_operator),
) -> dict:
    """Clear an alert for an agent."""
    scheduler_service.clear_alert(agent_id)
    return {"agent_id": agent_id, "cleared": True}
