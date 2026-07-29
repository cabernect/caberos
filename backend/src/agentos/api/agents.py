"""Agent management API routes (read side — list, get)."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..agent_service import get_active_config
from ..auth import require_operator
from ..db import get_db
from ..models.agent import Agent
from ..models.operator import Operator

router = APIRouter(prefix="/api/agents", tags=["agents"])


@router.get("")
async def list_agents(
    operator: Operator = Depends(require_operator),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """List all agents (for the landing page)."""
    result = await db.execute(select(Agent).order_by(Agent.name))
    agents = result.scalars().all()
    out = []
    for a in agents:
        config = await get_active_config(db, a.id)
        out.append(
            {
                "id": a.id,
                "name": config.name if config else a.id,
                "enabled": a.enabled,
                "model": config.model.name if config else None,
                "provider_id": config.model.provider_id if config else None,
                "soul": config.soul if config else "",
                "persona": config.persona if config else "",
                "task": config.task if config else "",
            }
        )
    return out


@router.get("/{agent_id}")
async def get_agent(
    agent_id: str,
    operator: Operator = Depends(require_operator),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Get a single agent's active config."""
    config = await get_active_config(db, agent_id)
    if config is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    return config.to_dict()
