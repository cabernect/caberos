"""Agent service — CRUD, versioning, YAML import/export (D25)."""

import json
from typing import Any

import yaml
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .config_schema import AgentConfig
from .models.agent import Agent, AgentVersion


def _config_to_json(config: AgentConfig) -> str:
    return json.dumps(config.to_dict(), ensure_ascii=False, indent=2)


def _json_to_config(json_str: str) -> AgentConfig:
    return AgentConfig.from_dict(json.loads(json_str))


async def create_agent(db: AsyncSession, config: AgentConfig) -> Agent:
    """Create a new agent with its first version."""
    agent = Agent(id=config.id, name=config.name, enabled=True)
    db.add(agent)
    await db.flush()

    version = AgentVersion(
        agent_id=config.id,
        version_number=1,
        config=_config_to_json(config),
        is_active=True,
    )
    db.add(version)
    await db.flush()

    agent.active_version_id = version.id
    await db.flush()
    await db.commit()
    return agent


async def get_agent(db: AsyncSession, agent_id: str) -> Agent | None:
    result = await db.execute(select(Agent).where(Agent.id == agent_id))
    return result.scalar_one_or_none()


async def get_active_config(db: AsyncSession, agent_id: str) -> AgentConfig | None:
    """Get the active version's config as an AgentConfig."""
    agent = await get_agent(db, agent_id)
    if agent is None or agent.active_version_id is None:
        return None
    result = await db.execute(
        select(AgentVersion).where(AgentVersion.id == agent.active_version_id)
    )
    version = result.scalar_one_or_none()
    if version is None:
        return None
    return _json_to_config(version.config)


async def list_agents(db: AsyncSession) -> list[Agent]:
    result = await db.execute(select(Agent).order_by(Agent.name))
    return list(result.scalars().all())


async def save_agent(db: AsyncSession, config: AgentConfig) -> AgentVersion:
    """Save a new version of an agent's config. Advances the active pointer."""
    agent = await get_agent(db, config.id)
    if agent is None:
        raise ValueError(f"Agent {config.id} not found")

    # Get the current max version number
    result = await db.execute(
        select(AgentVersion)
        .where(AgentVersion.agent_id == config.id)
        .order_by(AgentVersion.version_number.desc())
    )
    versions = result.scalars().all()
    next_num = (versions[0].version_number + 1) if versions else 1

    # Deactivate old active version
    for v in versions:
        if v.is_active:
            v.is_active = False

    # Create new version
    version = AgentVersion(
        agent_id=config.id,
        version_number=next_num,
        config=_config_to_json(config),
        is_active=True,
    )
    db.add(version)
    await db.flush()

    agent.active_version_id = version.id
    agent.name = config.name
    await db.commit()
    return version


async def list_versions(db: AsyncSession, agent_id: str) -> list[AgentVersion]:
    result = await db.execute(
        select(AgentVersion)
        .where(AgentVersion.agent_id == agent_id)
        .order_by(AgentVersion.version_number)
    )
    return list(result.scalars().all())


async def rollback_to(db: AsyncSession, agent_id: str, version_id: str) -> AgentVersion:
    """Rollback to a previous version by creating a new version that copies the old config."""
    result = await db.execute(select(AgentVersion).where(AgentVersion.id == version_id))
    old_version = result.scalar_one_or_none()
    if old_version is None or old_version.agent_id != agent_id:
        raise ValueError(f"Version {version_id} not found for agent {agent_id}")

    old_config = _json_to_config(old_version.config)
    return await save_agent(db, old_config)


async def disable_agent(db: AsyncSession, agent_id: str) -> None:
    agent = await get_agent(db, agent_id)
    if agent is None:
        raise ValueError(f"Agent {agent_id} not found")
    agent.enabled = False
    await db.commit()


async def export_agent(db: AsyncSession, agent_id: str) -> str:
    """Export agent config as YAML."""
    config = await get_active_config(db, agent_id)
    if config is None:
        raise ValueError(f"Agent {agent_id} not found")
    return yaml.dump(config.to_dict(), default_flow_style=False, sort_keys=False)


async def import_agent(db: AsyncSession, yaml_str: str) -> Agent:
    """Import an agent from YAML. Validates and creates."""
    data: dict[str, Any] = yaml.safe_load(yaml_str)
    config = AgentConfig.from_dict(data)
    existing = await get_agent(db, config.id)
    if existing is not None:
        await save_agent(db, config)
        return existing
    return await create_agent(db, config)
