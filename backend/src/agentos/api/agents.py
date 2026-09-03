"""Agent management API routes — CRUD, versioning, YAML import/export, duplicate, disable."""

import json
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..agent_service import (
    create_agent,
    disable_agent,
    duplicate_agent,
    enable_agent,
    export_agent,
    get_active_config,
    get_agent,
    import_agent,
    list_versions,
    rollback_to,
    save_agent,
)
from ..auth import require_operator
from ..config_schema import AgentConfig
from ..db import get_db
from ..models.agent import Agent, AgentVersion
from ..models.mcp import McpServer, McpTool
from ..models.operator import Operator

router = APIRouter(prefix="/api/agents", tags=["agents"])


# --- Capabilities listing ---


@router.get("/capabilities")
async def list_capabilities(
    operator: Operator = Depends(require_operator),
    db: AsyncSession = Depends(get_db),
) -> list[dict[str, Any]]:
    """List registered capabilities from enabled MCP servers and built-ins."""
    from ..capabilities.registry import registry

    enabled_result = await db.execute(
        select(
            McpTool.capability_name,
            McpTool.tool_name,
            McpServer.id,
            McpServer.name,
            McpServer.tool_filter,
        )
        .join(McpServer, McpServer.id == McpTool.mcp_server_id)
        .where(McpServer.enabled.is_(True))
    )
    enabled_mcp = {}
    for cap_name, tool_name, server_id, server_name, tool_filter_json in enabled_result:
        tool_filter = json.loads(tool_filter_json) if tool_filter_json else None
        if tool_filter and tool_name not in tool_filter:
            continue
        enabled_mcp[cap_name] = {"server_id": server_id, "server_name": server_name}

    capabilities = []
    for cap in registry.list_all():
        server_info = enabled_mcp.get(cap.name)
        if cap.name.startswith("mcp.") and server_info is None:
            continue
        capabilities.append(
            {
                "name": cap.name,
                "kind": cap.kind,
                "description": cap.description,
                "egress": cap.egress,
                "require_approval": cap.require_approval,
                "server_id": server_info["server_id"] if server_info else None,
                "server_name": server_info["server_name"] if server_info else None,
            }
        )
    return capabilities


# --- Request models ---


class CreateAgentRequest(BaseModel):
    name: str
    provider_id: str = ""
    model_name: str = ""
    soul: str = ""
    persona: str = ""
    task: str = ""


class UpdateAgentRequest(BaseModel):
    """Partial update — only provided fields are applied."""

    name: str | None = None
    provider_id: str | None = None
    model_name: str | None = None
    thinking_enabled: bool | None = None
    thinking_effort: str | None = None
    soul: str | None = None
    persona: str | None = None
    task: str | None = None
    capabilities: list[dict[str, Any]] | None = None
    limits: dict[str, Any] | None = None
    heartbeat: dict[str, Any] | None = None
    sandbox_mode: str | None = None


class DuplicateAgentRequest(BaseModel):
    new_id: str
    new_name: str


class ImportAgentRequest(BaseModel):
    yaml: str


# --- Routes ---


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
async def get_agent_route(
    agent_id: str,
    operator: Operator = Depends(require_operator),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Get a single agent's active config."""
    config = await get_active_config(db, agent_id)
    if config is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    agent = await get_agent(db, agent_id)
    return {
        "id": agent_id,
        "name": config.name,
        "enabled": agent.enabled if agent else True,
        "model": config.model.name,
        "provider_id": config.model.provider_id,
        "thinking_enabled": config.model.thinking_enabled,
        "thinking_effort": config.model.thinking_effort,
        "soul": config.soul,
        "persona": config.persona,
        "task": config.task,
        "capabilities": [c.model_dump() for c in config.capabilities]
        if config.capabilities is not None
        else None,
        "limits": config.limits.model_dump(),
        "heartbeat": config.heartbeat.model_dump(),
        "workspace": config.workspace,
        "sandbox_mode": config.sandbox_mode,
    }


@router.post("")
async def create_agent_route(
    req: CreateAgentRequest,
    operator: Operator = Depends(require_operator),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Create a new agent with default config."""
    agent_id = str(uuid.uuid4())[:8]
    config = AgentConfig(
        id=agent_id,
        name=req.name,
        model={
            "provider_id": req.provider_id,
            "name": req.model_name,
        },  # type: ignore[arg-type]
        soul=req.soul,
        persona=req.persona,
        task=req.task,
    )
    agent = await create_agent(db, config)
    return {"id": agent.id, "name": agent.name, "enabled": agent.enabled}


@router.put("/{agent_id}")
async def update_agent_route(
    agent_id: str,
    req: UpdateAgentRequest,
    operator: Operator = Depends(require_operator),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Update an agent's config. Creates a new version."""
    config = await get_active_config(db, agent_id)
    if config is None:
        raise HTTPException(status_code=404, detail="Agent not found")

    # Apply partial updates
    if req.name is not None:
        config.name = req.name
    if req.provider_id is not None:
        config.model.provider_id = req.provider_id
    if req.model_name is not None:
        config.model.name = req.model_name
    if req.thinking_enabled is not None:
        config.model.thinking_enabled = req.thinking_enabled
    if req.thinking_effort is not None:
        config.model.thinking_effort = req.thinking_effort
    if req.soul is not None:
        config.soul = req.soul
    if req.persona is not None:
        config.persona = req.persona
    if req.task is not None:
        config.task = req.task
    if req.sandbox_mode is not None:
        config.sandbox_mode = req.sandbox_mode
    if req.capabilities is not None:
        from ..config_schema import CapabilityGrant

        config.capabilities = [CapabilityGrant(**c) for c in req.capabilities]
    if req.limits is not None:
        from ..config_schema import Limits

        config.limits = Limits(**req.limits)
    if req.heartbeat is not None:
        from ..config_schema import HeartbeatConfig

        config.heartbeat = HeartbeatConfig(**req.heartbeat)

    version = await save_agent(db, config)
    return {
        "id": agent_id,
        "version": version.version_number,
        "version_id": version.id,
    }


@router.post("/{agent_id}/disable")
async def disable_agent_route(
    agent_id: str,
    operator: Operator = Depends(require_operator),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Disable an agent."""
    await disable_agent(db, agent_id)
    return {"id": agent_id, "enabled": False}


@router.post("/{agent_id}/enable")
async def enable_agent_route(
    agent_id: str,
    operator: Operator = Depends(require_operator),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Enable a disabled agent."""
    await enable_agent(db, agent_id)
    return {"id": agent_id, "enabled": True}


@router.post("/{agent_id}/duplicate")
async def duplicate_agent_route(
    agent_id: str,
    req: DuplicateAgentRequest,
    operator: Operator = Depends(require_operator),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Duplicate an agent to a new ID."""
    agent = await duplicate_agent(db, agent_id, req.new_id, req.new_name)
    return {"id": agent.id, "name": agent.name, "enabled": agent.enabled}


@router.get("/{agent_id}/export")
async def export_agent_route(
    agent_id: str,
    operator: Operator = Depends(require_operator),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Export agent config as YAML."""
    yaml_str = await export_agent(db, agent_id)
    return {"yaml": yaml_str}


@router.post("/import")
async def import_agent_route(
    req: ImportAgentRequest,
    operator: Operator = Depends(require_operator),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Import an agent from YAML."""
    agent = await import_agent(db, req.yaml)
    return {"id": agent.id, "name": agent.name, "enabled": agent.enabled}


@router.get("/{agent_id}/versions")
async def list_versions_route(
    agent_id: str,
    operator: Operator = Depends(require_operator),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """List all versions of an agent."""
    versions = await list_versions(db, agent_id)
    return [
        {
            "id": v.id,
            "version_number": v.version_number,
            "is_active": v.is_active,
            "created_at": v.created_at.isoformat() + "Z"
            if v.created_at and v.created_at.tzinfo is None
            else (v.created_at.isoformat() if v.created_at else ""),
        }
        for v in versions
    ]


@router.get("/{agent_id}/versions/{version_id}")
async def get_version_route(
    agent_id: str,
    version_id: str,
    operator: Operator = Depends(require_operator),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Get a specific version's config."""
    result = await db.execute(
        select(AgentVersion).where(AgentVersion.id == version_id, AgentVersion.agent_id == agent_id)
    )
    version = result.scalar_one_or_none()
    if version is None:
        raise HTTPException(status_code=404, detail="Version not found")
    import json

    config = json.loads(version.config)
    return {
        "id": version.id,
        "version_number": version.version_number,
        "is_active": version.is_active,
        "config": config,
    }


@router.post("/{agent_id}/rollback/{version_id}")
async def rollback_route(
    agent_id: str,
    version_id: str,
    operator: Operator = Depends(require_operator),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Rollback to a previous version (creates a new version copying the old config)."""
    version = await rollback_to(db, agent_id, version_id)
    return {
        "id": version.id,
        "version_number": version.version_number,
        "is_active": version.is_active,
    }
