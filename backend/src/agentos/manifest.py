"""Execution Manifest capture (v0.2 foundations).

At run start we snapshot which revisions of versioned things the run uses,
so a run's provenance survives later edits to agents, plans, skills,
schedules, retrieval profiles, and artifacts. The manifest is immutable
once written — it is the record of what the execution was built from.

Only IDs, version numbers, and safe hashes are stored. Never secrets,
cookies, or private content.
"""

import json
import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models.agent import Agent
from .models.execution_manifest import ExecutionManifest

log = logging.getLogger(__name__)


async def capture_execution_manifest(
    db: AsyncSession,
    *,
    run_id: str,
    agent_id: str,
    agent_config: Any,
    skill_revision_ids: list[str] | None = None,
) -> ExecutionManifest:
    """Record the run's Execution Manifest. Idempotent per run.

    Captures the effective agent config (post model-override), the active
    AgentVersion pointer, and references to any versioned entities the run
    is pinned to. Versioned entities that don't exist yet (plans,
    schedules, retrieval profiles, artifacts) stay null — the columns are
    the contract their modules fill in.
    """
    existing = await db.execute(select(ExecutionManifest).where(ExecutionManifest.run_id == run_id))
    manifest = existing.scalar_one_or_none()
    if manifest is not None:
        return manifest

    agent_version_id = None
    agent_version_number = None
    result = await db.execute(select(Agent).where(Agent.id == agent_id))
    agent = result.scalar_one_or_none()
    if agent is not None and agent.active_version_id:
        agent_version_id = agent.active_version_id
        from .models.agent import AgentVersion

        version_row = await db.execute(
            select(AgentVersion.version_number).where(AgentVersion.id == agent.active_version_id)
        )
        agent_version_number = version_row.scalar_one_or_none()

    model = getattr(agent_config, "model", None)
    manifest = ExecutionManifest(
        run_id=run_id,
        agent_version_id=agent_version_id,
        agent_version_number=agent_version_number,
        model_provider_id=getattr(model, "provider_id", None),
        model_name=getattr(model, "name", None),
        skill_revision_ids=json.dumps(skill_revision_ids or []),
    )
    db.add(manifest)
    await db.flush()
    return manifest
