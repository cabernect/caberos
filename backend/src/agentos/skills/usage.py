"""Activation recording — write one immutable SkillActivation per event.

Activations are recorded only after a successful skills_load or a
successful forced/slash injection render — never for menu listings,
resource reads, or failed loads. Identity comes from the resolved skill
and the persisted Run, never from model-supplied values.
"""

import hashlib
import json
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.run import Run
from ..models.skill_usage import SkillActivation
from ..skills.reconcile import _index_agent_local

_SOURCES = ("load", "forced")


def _event_key(run_id: str, sub_agent_id: str | None, source: str, call_id: str | None) -> str:
    """Deterministic over run/subagent/source/call — forced (no call_id)
    dedups to once per run scope; loads without a call_id get a unique key
    so uncorrelated dispatches never collapse into one activation."""
    if source == "forced":
        call_key = "forced"
    elif call_id:
        call_key = call_id
    else:
        call_key = uuid.uuid4().hex
    parts = [run_id, sub_agent_id or "", source, call_key]
    return hashlib.sha256(json.dumps(parts, separators=(",", ":")).encode("utf-8")).hexdigest()


async def record_skill_activation(
    db: AsyncSession,
    resolved: Any,
    run_id: str | None,
    source: str,
    call_id: str | None = None,
    sub_agent_id: str | None = None,
) -> str | None:
    """Persist one activation; returns the row id or None when invalid.

    Guards: run must exist, match a real (non-test, non-reflection) run,
    and the resolved skill must map to a stable Skill row — live
    agent-local dirs are indexed on demand so versions aggregate onto the
    same skill identity rather than a name lookup.
    """
    if resolved is None or not run_id or source not in _SOURCES:
        return None
    run = await db.get(Run, run_id)
    if run is None or run.is_test or run.trigger == "reflection":
        return None
    agent_id = run.agent_id

    skill_id = resolved.skill_id
    if skill_id is None and resolved.scope == "agent-local":
        skill = await _index_agent_local(db, agent_id, resolved.path)
        skill_id = skill.id if skill is not None else None
    if skill_id is None:
        return None

    # Forced injection: fixed key → once per run scope. Explicit loads with a
    # call_id dedup on it; loads with NO call_id get a unique key so
    # uncorrelated dispatches never collapse into one activation.
    event_key = _event_key(run_id, sub_agent_id, source, call_id)
    existing = await db.scalar(
        select(SkillActivation.id).where(SkillActivation.event_key == event_key)
    )
    if existing is not None:
        return existing

    row = SkillActivation(
        skill_id=skill_id,
        name=resolved.name,
        scope=resolved.scope,
        owner_agent_id=agent_id if resolved.scope == "agent-local" else None,
        run_id=run_id,
        agent_id=agent_id,
        sub_agent_id=sub_agent_id,
        source=source,
        call_id=call_id,
        event_key=event_key,
    )
    db.add(row)
    await db.flush()
    return row.id


async def record_skill_activation_isolated(
    resolved: Any,
    run_id: str | None,
    source: str,
    call_id: str | None = None,
    sub_agent_id: str | None = None,
) -> str | None:
    """Write the activation on its OWN session — never leaves the caller's
    transaction open or poisons it on failure. Duplicate event_keys and
    transient locks retry/fail-safe; callers get the id or None."""
    import logging

    from ..db import async_session_factory, retry_locked_transaction

    async def _persist() -> str | None:
        try:
            rid = await record_skill_activation(
                owned, resolved, run_id, source, call_id=call_id, sub_agent_id=sub_agent_id
            )
            await owned.commit()  # flush+commit inside the try — a unique
            # event_key violation surfaces as IntegrityError here
        except IntegrityError:
            await owned.rollback()
            # Concurrent duplicate event_key — idempotent; requery winner.
            return await owned.scalar(
                select(SkillActivation.id).where(
                    SkillActivation.event_key == _event_key(run_id, sub_agent_id, source, call_id)
                )
            )
        return rid

    try:
        async with async_session_factory() as owned:
            return await retry_locked_transaction(_persist, owned, f"skill-activation:{run_id}")
    except Exception as exc:  # evidence is best-effort
        logging.getLogger(__name__).debug("skill activation write failed: %s", type(exc).__name__)
        return None
