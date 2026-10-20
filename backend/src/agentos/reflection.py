"""Session-close reflection orchestration using the ordinary harness/syscalls."""

import asyncio
import hashlib
import json
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from .capabilities.builtin import register_builtin_capabilities
from .capabilities.catalog import _grant_for
from .config import settings
from .config_schema import CapabilityGrant
from .harness.base_prompt import REFLECTION_SYSTEM_PROMPT
from .harness.conversation import Conversation
from .harness.loop import Harness
from .manifest import capture_execution_manifest
from .memory.history_queries import freeze_session_evidence
from .models.contact import Contact
from .models.model_call import ModelCall
from .models.run import Message, Run
from .models.session import Session
from .models.skill_reflection import SkillReflection
from .providers import ProviderRegistry
from .skills.resolution import resolve_effective_skills, skill_pins
from .skills.service import SkillConflict, SkillEditSession
from .syscall.mediator import SyscallHandler
from .syscall.protocol import ExecutionRestrictions

MAX_TURNS = 8
MAX_OUTPUT_TOKENS = 4096
MAX_INITIAL_ROWS = 12
MAX_INITIAL_CHARS = 12000
REFLECTION_CAPABILITIES = frozenset(
    {
        "read_file",
        "write_file",
        "skills_list",
        "skills_load",
        "skills_read_resource",
        "skills_usage",
        "search_history",
    }
)


def _bounded_view(rows, summary, coverage_known):
    parent = [row for row in rows if row.role in ("user", "assistant")]
    selected = []
    for row in parent[-MAX_INITIAL_ROWS:]:
        content = row.content or ""
        offset = max(0, len(content) - MAX_INITIAL_CHARS // MAX_INITIAL_ROWS)
        selected.append(
            {
                "message_id": row.id,
                "run_id": row.run_id,
                "role": row.role,
                "content": content[offset:],
                "content_offset": offset,
                "content_length": len(content),
            }
        )
    summary = summary or ""
    view = {
        "summary": summary[: MAX_INITIAL_CHARS // 2],
        "summary_length": len(summary),
        "summary_truncated": len(summary) > MAX_INITIAL_CHARS // 2,
        "coverage_known": coverage_known,
        "messages": selected,
        "omitted_parent_rows": len(parent) - len(selected),
        "evidence_records_total": len(rows),
    }
    while len(json.dumps(view, ensure_ascii=False)) > MAX_INITIAL_CHARS and selected:
        selected.pop(0)
        view["omitted_parent_rows"] += 1
    return view


async def _finish(db, activity_id, run_id, *, outcome, error, revision_ids, started):
    await db.rollback()
    activity = await db.get(SkillReflection, activity_id)
    run = await db.get(Run, run_id)
    if activity is None or run is None:
        return None
    totals = (
        await db.execute(
            select(
                func.coalesce(func.sum(ModelCall.tokens_in), 0),
                func.coalesce(func.sum(ModelCall.tokens_out), 0),
                func.coalesce(func.sum(ModelCall.cost), 0.0),
            ).where(ModelCall.run_id == run_id)
        )
    ).one()
    now = datetime.now(UTC)
    activity.outcome, activity.error = outcome, error
    activity.completed_at = now
    activity._revision_ids = json.dumps(revision_ids)
    run.status = "completed" if outcome in ("changed", "no_change") else "failed"
    run.completed_at, run.error = now, error
    run.tokens_in, run.tokens_out, run.cost = totals
    run.latency_ms = int((time.monotonic() - started) * 1000)
    await db.commit()
    return activity


async def reflect_session(db, agent_config, session, contact_id, source_run_ids):
    """Claim one evidence batch, run with narrowed authority, publish local edits."""
    if agent_config.model is None or not agent_config.model.is_configured:
        return None
    fresh = await db.get(Session, session.id, populate_existing=True)
    contact = await db.get(Contact, contact_id)
    if (
        fresh is None
        or not fresh.closed
        or (fresh.agent_id, fresh.contact_id) != (agent_config.id, contact_id)
        or contact is None
        or contact.channel != "dashboard_chat"
        or contact.bot_id != agent_config.id
    ):
        return None
    session_id, agent_id = fresh.id, agent_config.id
    activity_token = str(fresh.last_activity_at)
    rows = await freeze_session_evidence(
        db,
        session_id=session_id,
        agent_id=agent_id,
        contact_id=contact_id,
        run_ids=source_run_ids,
    )
    parent_ids = sorted(row.id for row in rows if row.role in ("user", "assistant"))
    if not parent_ids:
        return None
    # Silent skip — the agent is mid-task or the session already gained
    # activity; skip BEFORE claiming the fingerprint so no failed/noise row
    # is written. The publish-time precondition still guards the race
    # window where a run starts during reflection.
    busy = await db.scalar(
        select(Run.id)
        .where(
            Run.agent_id == agent_id,
            Run.trigger != "reflection",
            Run.is_test.is_(False),
            Run.status.not_in(("completed", "failed", "stopped", "interrupted")),
        )
        .limit(1)
    )
    if busy is not None:
        return None
    # Fast claim check — an already-reflected evidence batch exits before
    # the resolution work below. The unique constraint stays as the race
    # backstop; this just keeps retry scans cheap.
    fingerprint = hashlib.sha256(json.dumps(parent_ids, separators=(",", ":")).encode()).hexdigest()
    claimed = await db.scalar(
        select(SkillReflection.id).where(
            SkillReflection.session_id == session_id,
            SkillReflection.source_fingerprint == fingerprint,
        )
    )
    if claimed is not None:
        return None
    # Reject lexical symlinks before live resolution can hash their targets.
    local_root = Path(settings.workspace_root) / agent_id / "skills"
    for path in (local_root, *local_root.parents):
        if path.is_symlink():
            raise ValueError("Symlinked skill root")
    if local_root.exists() and any(path.is_symlink() for path in local_root.rglob("*")):
        raise ValueError("Symlinked live skill")
    resolved = await resolve_effective_skills(db, agent_id)
    evolve = next((skill for skill in resolved if skill.name == "evolve"), None)
    if evolve is None:
        return None
    summary, _, _, _, coverage_known = await Conversation.coverage_state(db, fresh)
    view = _bounded_view(rows, summary, coverage_known)
    frozen_scope = {
        "session_id": session_id,
        "agent_id": agent_id,
        "contact_id": contact_id,
        "run_ids": sorted({row.run_id for row in rows}),
        "message_ids": [row.id for row in rows],
    }
    run_id, activity_id = str(uuid.uuid4()), str(uuid.uuid4())
    db.add(
        Run(
            id=run_id,
            session_id=session_id,
            agent_id=agent_id,
            contact_id=contact_id,
            trigger="reflection",
            status="running",
            is_test=False,
        )
    )
    await db.flush()
    db.add(
        SkillReflection(
            id=activity_id,
            run_id=run_id,
            session_id=session_id,
            agent_id=agent_id,
            contact_id=contact_id,
            source_fingerprint=fingerprint,
            _source_run_ids=json.dumps(frozen_scope["run_ids"]),
            _source_message_ids=json.dumps(frozen_scope["message_ids"]),
            outcome="running",
        )
    )
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        return None
    edits = None
    started, outcome, error, saved = time.monotonic(), "failed", None, []

    async def precondition(_name=None):
        current = await db.get(Session, session_id, populate_existing=True)
        if (
            current is None
            or not current.closed
            or str(current.last_activity_at) != activity_token
            or (current.agent_id, current.contact_id) != (agent_id, contact_id)
        ):
            raise SkillConflict("Session changed during reflection")
        active = await db.scalar(
            select(Run.id)
            .where(
                Run.agent_id == agent_id,
                Run.trigger != "reflection",
                Run.is_test.is_(False),
                Run.status.not_in(("completed", "failed", "stopped", "interrupted")),
            )
            .limit(1)
        )
        if active is not None:
            raise SkillConflict("Agent has an active task")

    try:
        register_builtin_capabilities()
        edits = SkillEditSession(db, agent_id, resolved)
        procedure = await edits.load_skill(evolve)
        allowed = []
        for name in sorted(REFLECTION_CAPABILITIES):
            grant = _grant_for(agent_config, name)
            if grant is not None and not grant.require_approval:
                allowed.append(
                    {
                        "name": name,
                        "enabled": True,
                        "subject": getattr(grant, "subject", "none"),
                        "always_loaded": True,
                    }
                )
        run_config = agent_config.model_copy(deep=True)
        run_config.capabilities = [CapabilityGrant(**grant) for grant in allowed]
        run_config.limits.max_turns_per_run = min(MAX_TURNS, run_config.limits.max_turns_per_run)
        run_config.model.max_tokens = min(
            MAX_OUTPUT_TOKENS, run_config.model.max_tokens or MAX_OUTPUT_TOKENS
        )
        run_config.compaction.auto_compaction = False
        pins = skill_pins(resolved)
        if evolve.scope == "agent-local":
            pins["evolve"] = "live:" + procedure["content_hash"]
        await capture_execution_manifest(
            db,
            run_id=run_id,
            agent_id=agent_id,
            agent_config=run_config,
            skill_revision_ids=pins,
        )
        message = json.dumps(
            {"evidence": view, "evolve_procedure": procedure["body"]}, ensure_ascii=False
        )
        db.add(Message(run_id=run_id, role="user", content=message, seq=0))
        await db.commit()
        adapter = await ProviderRegistry(db).for_model(run_config.model.provider_id)
        handler = SyscallHandler(
            db,
            str(Path(settings.workspace_root) / agent_id),
            "strict",
            restrictions=ExecutionRestrictions(
                capability_names=frozenset(grant["name"] for grant in allowed),
                skill_edits=edits,
                history_scope=frozen_scope,
            ),
        )
        seq = 1

        async def persist_event(event_type, payload):
            nonlocal seq
            if event_type != "tool_call" or payload.get("status") not in {
                "complete",
                "denied",
                "failed",
                "timeout",
                "interrupted",
            }:
                return None
            row = Message(
                id=str(uuid.uuid4()),
                run_id=run_id,
                role="tool_call",
                content=json.dumps(payload),
                seq=seq,
            )
            seq += 1
            db.add(row)
            await db.commit()
            return {"tool_message_id": row.id}

        await db.commit()
        result = await Harness(adapter).run(
            run_config,
            fresh,
            message,
            handler,
            run_id,
            conversation=Conversation(session_id=""),
            trigger="reflection",
            resolved_skills=resolved,
            event_emitter=persist_event,
            system_prompt_override=REFLECTION_SYSTEM_PROMPT,
        )
        db.add(Message(run_id=run_id, role="assistant", content=result.final_answer or "", seq=seq))
        await db.commit()
        if result.status != "completed" or not result.final_answer.strip():
            error = result.error or result.status or "empty final output"
        else:
            published = await edits.publish(
                reason=result.final_answer[:2000],
                source_run_id=run_id,
                precondition=precondition,
            )
            saved = published["revision_ids"]
            failed_writes = any(
                call["name"] == "write_file" and not call["allowed"]
                for call in result.tool_calls_made
            )
            if published["errors"] or (failed_writes and not saved):
                error = "; ".join(published["errors"]) or "Skill write failed"
            else:
                outcome = (
                    "changed" if saved else ("conflict" if published["conflicts"] else "no_change")
                )
    except BaseException as exc:
        error = type(exc).__name__
        if isinstance(exc, (asyncio.CancelledError, KeyboardInterrupt, SystemExit)):
            await _finish(
                db,
                activity_id,
                run_id,
                outcome="failed",
                error=error,
                revision_ids=saved,
                started=started,
            )
            raise
    finally:
        if edits is not None:
            await edits.close()
    return await _finish(
        db, activity_id, run_id, outcome=outcome, error=error, revision_ids=saved, started=started
    )
