"""Observability API routes (Ticket 09).

GET  /api/runs           — paginated, filterable run list
GET  /api/runs/{run_id}  — run detail (messages + audit records)
GET  /api/audit          — paginated syscall/audit log
GET  /api/spend          — spend summary (today + breakdowns)
GET  /api/health         — system health (DB, providers)
GET  /api/operator-audit — operator action audit trail
GET  /api/stats          — dashboard stats (KPIs + time-series + per-agent)
"""

import asyncio
import json
import logging
from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import require_operator
from ..db import get_db
from ..models.agent import Agent
from ..models.audit import AuditRecord
from ..models.execution_manifest import ExecutionManifest
from ..models.model_call import ModelCall
from ..models.operator import OperatorAuditLog
from ..models.provider import Provider
from ..models.run import Message, Run
from ..redaction import (
    project_args,
    project_result,
    redact_secrets,
    redact_text,
)
from ..sandbox import probe as sandbox_probe
from ..services.observability_filters import filter_runs
from ..services.observability_spend import platform_spend
from ..services.observability_timeline import build_run_timeline

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["observability"])


def _decode_json(value: str | None, default: Any) -> Any:
    try:
        return json.loads(value) if value else default
    except (TypeError, json.JSONDecodeError):
        return default


# --- Response models ---


class RunSummary(BaseModel):
    id: str
    agent_id: str
    agent_name: str | None = None
    session_id: str
    status: str
    trigger: str
    tokens_in: int
    tokens_out: int
    cost: float
    latency_ms: int
    is_test: bool
    started_at: datetime
    completed_at: datetime | None = None
    error: str | None = None


class MessageOut(BaseModel):
    id: str
    run_id: str
    role: str
    content: str
    seq: int
    created_at: datetime
    subagent_id: str | None = None


class AuditOut(BaseModel):
    id: str
    run_id: str
    agent_id: str
    sub_agent_id: str | None = None
    call_id: str | None = None
    capability_name: str
    allowed: bool
    outcome: str = "ok"
    denied_reason: str | None = None
    cost: float
    latency_ms: int
    args: str
    result: str | None = None
    effects: list[str] | None = None
    created_at: datetime | None = None


class TimelineEvent(BaseModel):
    id: str
    type: str
    at: datetime | None = None
    call_id: str | None = None
    sub_agent_id: str | None = None
    parent_id: str | None = None
    status: str | None = None
    data: dict = {}
    redacted: bool = False
    truncated: bool = False
    estimated_time: bool = False


class ModelCallOut(BaseModel):
    id: str
    run_id: str | None = None
    agent_id: str | None = None
    sub_agent_id: str | None = None
    turn: int
    kind: str = "chat"
    purpose: str = "reasoning"
    provider_id: str | None = None
    model_name: str | None = None
    model_str: str | None = None
    streamed: bool = False
    tokens_in: int
    tokens_out: int
    cached_tokens: int | None = None
    thinking_tokens: int | None = None
    detail: dict | None = None
    cost: float
    latency_ms: int
    status: str
    error: str | None = None
    created_at: datetime | None = None


class ManifestOut(BaseModel):
    agent_version_id: str | None = None
    agent_version_number: int | None = None
    model_provider_id: str | None = None
    model_name: str | None = None
    plan_revision_id: str | None = None
    schedule_revision_id: str | None = None
    skill_revision_ids: dict[str, str] | list[str] = []
    retrieval_profile_revision_id: str | None = None
    knowledge_snapshot_ids: list[str] = []
    browser_profile_id: str | None = None
    artifact_base_revision_ids: list[str] = []


class RunDetail(BaseModel):
    id: str
    agent_id: str
    agent_name: str | None = None
    session_id: str
    status: str
    trigger: str
    tokens_in: int
    tokens_out: int
    cost: float
    latency_ms: int
    is_test: bool
    started_at: datetime
    completed_at: datetime | None = None
    error: str | None = None
    context_tokens: int = 0
    max_context_tokens: int = 0
    compacted: bool = False
    context_breakdown: dict[str, int] = {}
    loaded_capabilities: list[str] = []
    manifest: ManifestOut | None = None
    messages: list[MessageOut]
    audit_records: list[AuditOut]
    model_calls: list[ModelCallOut] = []
    timeline: list[TimelineEvent] = []


class SpendBreakdown(BaseModel):
    agent_id: str
    agent_name: str | None = None
    total_cost: float
    run_count: int
    tokens_in: int
    tokens_out: int


class SpendSummary(BaseModel):
    total_cost: float
    total_runs: int
    total_tokens_in: int
    total_tokens_out: int
    by_agent: list[SpendBreakdown]
    by_trigger: dict[str, float]


class OperatorAuditOut(BaseModel):
    id: str
    operator_id: str
    action: str
    target: str
    created_at: datetime


class SandboxStatus(BaseModel):
    kind: str
    state: str
    reason: str | None = None
    setup_required: bool = False


class HealthStatus(BaseModel):
    status: str
    database: str
    providers: int
    agents: int
    active_runs: int
    sandbox: SandboxStatus
    # The desktop shell compares this against its own version. An installer that
    # replaces the shell but leaves the bundled gateway stale would otherwise
    # run a new frontend against an old backend — silently, and across schema
    # patches applied by init_db() at startup.
    version: str | None = None
    timestamp: datetime


def _dump_payload(value) -> str | None:
    """Projected payloads serialize as JSON text (matching the column's
    existing string shape); strings pass through already-bounded."""
    if value is None:
        return None
    if isinstance(value, (dict, list)):
        return json.dumps(value, default=str)
    return str(value)


def _redact_str(value: str | None) -> str | None:
    if value is None:
        return None
    return redact_secrets(value)[0]


def _safe_manifest_map(raw) -> dict | list:
    """skill_revision_ids is a name→revision pin map — keep the mapping;
    malformed content collapses to {}."""
    parsed = _decode_json(raw, {})
    if not isinstance(parsed, dict):
        return {}
    return {str(k)[:255]: str(v)[:255] for k, v in list(parsed.items())[:50] if isinstance(v, str)}


def _safe_manifest_list(raw) -> list:
    parsed = _decode_json(raw, [])
    if not isinstance(parsed, list):
        return []
    return [
        redact_secrets(str(v))[0][:255] for v in parsed[:50] if isinstance(v, (str, int, float))
    ]


_CALL_DETAIL_KEYS = (
    "resource_id",
    "generation_id",
    "operation",
    "chunk_count",
    "cost_source",
)


def _safe_call_detail(detail) -> dict | None:
    if not isinstance(detail, dict):
        return None
    return {k: redact_secrets(str(detail[k]))[0][:255] for k in _CALL_DETAIL_KEYS if k in detail}


def _audit_out(a: AuditRecord) -> AuditOut:
    """Flat-list audit rows get the same projection as timeline events —
    the legacy fields can't be a redaction bypass."""
    args, _red, _trunc = project_args(a.capability_name, a.args)
    result, _red, _trunc = project_result(a.capability_name, a.result)
    denied_reason, _, _ = redact_text(a.denied_reason, 500)
    return AuditOut(
        id=a.id,
        run_id=a.run_id,
        agent_id=a.agent_id,
        sub_agent_id=a.sub_agent_id,
        call_id=a.call_id,
        capability_name=a.capability_name,
        allowed=a.allowed,
        outcome=a.outcome,
        denied_reason=denied_reason,
        cost=a.cost,
        latency_ms=a.latency_ms,
        args=_dump_payload(args) or "{}",
        result=_dump_payload(result),
        effects=a.effects,
        created_at=a.created_at,
    )


# tool_call message payloads keep only these fields, ever.
_TOOL_CALL_KEYS = {
    "id",
    "capability",
    "args",
    "status",
    "result",
    "reason",
    "approval_id",
    "approval_batch_id",
    "approval_batch_size",
    "subagent_id",
}
_TOOL_CALL_SCALAR = {
    "id",
    "capability",
    "status",
    "reason",
    "subagent_id",
    "approval_id",
    "approval_batch_id",
}
_TOOL_CALL_INT = {"approval_batch_size"}


def _message_content(m: Message) -> str:
    """Read-boundary sanitization for legacy message rows.

    tool_call messages carry JSON payloads → strict allowlist projection
    (a stray field can't bypass the capability projectors). Ordinary text
    (user/assistant/thinking) gets secret regex redaction only — content
    is never wholesale-dropped. ``tool`` role bodies are raw tool output
    with no capability linkage, so they fail closed to a placeholder.
    Stored rows are never mutated.
    """
    if m.role == "tool_call":
        try:
            payload = json.loads(m.content)
        except (ValueError, TypeError):
            payload = None
        if not isinstance(payload, dict):
            return json.dumps({"status": "unavailable"})
        capability = payload.get("capability", "")
        if not isinstance(capability, str):
            capability = ""
        args, _r, _t = project_args(capability, payload.get("args"))
        result, _r, _t = project_result(capability, payload.get("result"))
        projected: dict = {"args": args, "result": result}
        for key in _TOOL_CALL_SCALAR:
            value = payload.get(key)
            if isinstance(value, str):
                projected[key] = redact_secrets(value)[0]
        for key in _TOOL_CALL_INT:
            value = payload.get(key)
            if isinstance(value, int):
                projected[key] = value
        return json.dumps(projected, default=str)
    if m.role == "tool":
        return "Tool result omitted from trace; inspect its linked syscall summary."
    return redact_secrets(m.content)[0]


# --- Routes ---


def _utc(value: datetime | None) -> datetime | None:
    """Naive time params are interpreted as UTC."""
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


@router.get("/runs")
async def list_runs(
    agent_id: str | None = Query(None),
    status: str | None = Query(None),
    trigger: str | None = Query(None),
    is_test: bool | None = Query(None),
    provider_id: str | None = Query(None),
    model: str | None = Query(None),
    purpose: str | None = Query(None),
    kind: str | None = Query(None),
    schedule_id: str | None = Query(None),
    channel: str | None = Query(None),
    capability: str | None = Query(None),
    tool_status: str | None = Query(None),
    browser_profile: str | None = Query(None),
    artifact_format: str | None = Query(None),
    retrieval_mode: str | None = Query(None),
    retrieval_degraded: bool | None = Query(None),
    effect: str | None = Query(None),
    since: datetime | None = Query(None),
    until: datetime | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    _op=Depends(require_operator),
) -> list[RunSummary]:
    """List runs with optional filters."""
    since = _utc(since)
    until = _utc(until)
    if since is not None and until is not None and since >= until:
        raise HTTPException(422, "since must be earlier than until")

    stmt = select(Run).order_by(Run.started_at.desc()).limit(limit).offset(offset)
    if agent_id:
        stmt = stmt.where(Run.agent_id == agent_id)
    if status is not None:
        statuses = [s.strip() for s in status.split(",") if s.strip()]
        if not statuses:
            raise HTTPException(422, "status must name at least one value")
        stmt = stmt.where(
            Run.status.in_(statuses) if len(statuses) > 1 else Run.status == statuses[0]
        )
    if trigger:
        stmt = stmt.where(Run.trigger == trigger)
    if is_test is not None:
        stmt = stmt.where(Run.is_test == is_test)

    stmt = filter_runs(
        stmt,
        db,
        provider_id=provider_id,
        model=model,
        purpose=purpose,
        kind=kind,
        schedule_id=schedule_id,
        channel=channel,
        capability=capability,
        tool_status=tool_status,
        browser_profile=browser_profile,
        artifact_format=artifact_format,
        retrieval_mode=retrieval_mode,
        retrieval_degraded=retrieval_degraded,
        effect=effect,
        since=since,
        until=until,
    )

    result = await db.execute(stmt)
    runs = result.scalars().all()

    # Batch-fetch agent names
    agent_ids = {r.agent_id for r in runs}
    agent_names: dict[str, str] = {}
    if agent_ids:
        ag_result = await db.execute(select(Agent.id, Agent.name).where(Agent.id.in_(agent_ids)))
        agent_names = {aid: name for aid, name in ag_result.all()}

    return [
        RunSummary(
            id=r.id,
            agent_id=r.agent_id,
            agent_name=agent_names.get(r.agent_id),
            session_id=r.session_id,
            status=r.status,
            trigger=r.trigger,
            tokens_in=r.tokens_in,
            tokens_out=r.tokens_out,
            cost=r.cost,
            latency_ms=r.latency_ms,
            is_test=r.is_test,
            started_at=r.started_at,
            completed_at=r.completed_at,
            error=r.error,
        )
        for r in runs
    ]


@router.get("/runs/{run_id}")
async def get_run_detail(
    run_id: str,
    db: AsyncSession = Depends(get_db),
    _op=Depends(require_operator),
) -> RunDetail:
    """Get full run detail: messages + audit records."""
    result = await db.execute(select(Run).where(Run.id == run_id))
    run = result.scalar_one_or_none()
    if run is None:
        raise HTTPException(404, "Run not found")

    # Agent name
    ag_result = await db.execute(select(Agent.name).where(Agent.id == run.agent_id))
    agent_name = ag_result.scalar_one_or_none()

    # Messages
    msg_result = await db.execute(
        select(Message).where(Message.run_id == run_id).order_by(Message.seq)
    )
    messages = [
        MessageOut(
            id=m.id,
            run_id=m.run_id,
            role=m.role,
            content=_message_content(m),
            seq=m.seq,
            created_at=m.created_at,
            subagent_id=m.subagent_id,
        )
        for m in msg_result.scalars().all()
    ]

    # Audit records
    audit_result = await db.execute(
        select(AuditRecord).where(AuditRecord.run_id == run_id).order_by(AuditRecord.id)
    )
    audit_records = [_audit_out(a) for a in audit_result.scalars().all()]

    # Execution manifest (immutable provenance captured at run start)
    manifest_result = await db.execute(
        select(ExecutionManifest).where(ExecutionManifest.run_id == run_id)
    )
    manifest_row = manifest_result.scalar_one_or_none()
    manifest = (
        ManifestOut(
            agent_version_id=manifest_row.agent_version_id,
            agent_version_number=manifest_row.agent_version_number,
            model_provider_id=manifest_row.model_provider_id,
            model_name=_redact_str(manifest_row.model_name),
            plan_revision_id=manifest_row.plan_revision_id,
            schedule_revision_id=manifest_row.schedule_revision_id,
            skill_revision_ids=_safe_manifest_map(manifest_row.skill_revision_ids),
            retrieval_profile_revision_id=manifest_row.retrieval_profile_revision_id,
            knowledge_snapshot_ids=_safe_manifest_list(manifest_row.knowledge_snapshot_ids),
            browser_profile_id=manifest_row.browser_profile_id,
            artifact_base_revision_ids=_safe_manifest_list(manifest_row.artifact_base_revision_ids),
        )
        if manifest_row is not None
        else None
    )

    # Per-model-call accounting (v0.2)
    model_call_result = await db.execute(
        select(ModelCall).where(ModelCall.run_id == run_id).order_by(ModelCall.created_at)
    )
    model_calls = [
        ModelCallOut(
            id=m.id,
            run_id=m.run_id,
            agent_id=m.agent_id,
            sub_agent_id=m.sub_agent_id,
            turn=m.turn,
            kind=m.kind,
            purpose=m.purpose,
            provider_id=m.provider_id,
            model_name=_redact_str(m.model_name),
            model_str=_redact_str(m.model_str),
            streamed=m.streamed,
            tokens_in=m.tokens_in,
            tokens_out=m.tokens_out,
            cached_tokens=m.cached_tokens,
            thinking_tokens=m.thinking_tokens,
            detail=_safe_call_detail(m.detail),
            cost=m.cost,
            latency_ms=m.latency_ms,
            status=m.status,
            error=_redact_str(m.error),
            created_at=m.created_at,
        )
        for m in model_call_result.scalars().all()
    ]

    timeline = await build_run_timeline(db, run)

    raw_breakdown = _decode_json(run.context_breakdown, {})
    context_breakdown = (
        {str(k): v for k, v in raw_breakdown.items() if isinstance(v, (int, float))}
        if isinstance(raw_breakdown, dict)
        else {}
    )
    raw_caps = _decode_json(run.loaded_capabilities, [])
    loaded_capabilities = (
        [str(c)[:255] for c in raw_caps if isinstance(c, str)] if isinstance(raw_caps, list) else []
    )

    return RunDetail(
        id=run.id,
        agent_id=run.agent_id,
        agent_name=agent_name,
        session_id=run.session_id,
        status=run.status,
        trigger=run.trigger,
        tokens_in=run.tokens_in,
        tokens_out=run.tokens_out,
        cost=run.cost,
        latency_ms=run.latency_ms,
        is_test=run.is_test,
        started_at=run.started_at,
        completed_at=run.completed_at,
        error=_redact_str(run.error),
        context_tokens=run.context_tokens,
        max_context_tokens=run.max_context_tokens,
        compacted=run.compacted,
        context_breakdown=context_breakdown,
        loaded_capabilities=loaded_capabilities,
        manifest=manifest,
        messages=messages,
        audit_records=audit_records,
        model_calls=model_calls,
        timeline=[TimelineEvent(**e) for e in timeline],
    )


@router.get("/audit")
async def list_audit(
    agent_id: str | None = Query(None),
    capability_name: str | None = Query(None),
    allowed: bool | None = Query(None),
    run_id: str | None = Query(None),
    outcome: str | None = Query(None),
    call_id: str | None = Query(None),
    sub_agent_id: str | None = Query(None),
    since: datetime | None = Query(None),
    until: datetime | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    _op=Depends(require_operator),
) -> list[AuditOut]:
    """List audit/syscall records with filters.

    since/until match on the W10 `created_at` column — legacy rows carry
    NULL and therefore fall outside any time range."""
    since = _utc(since)
    until = _utc(until)
    if since is not None and until is not None and since >= until:
        raise HTTPException(422, "since must be earlier than until")
    stmt = select(AuditRecord).order_by(AuditRecord.id.desc()).limit(limit).offset(offset)
    if agent_id:
        stmt = stmt.where(AuditRecord.agent_id == agent_id)
    if capability_name:
        stmt = stmt.where(AuditRecord.capability_name == capability_name)
    if allowed is not None:
        stmt = stmt.where(AuditRecord.allowed == allowed)
    if run_id:
        stmt = stmt.where(AuditRecord.run_id == run_id)
    if outcome:
        stmt = stmt.where(AuditRecord.outcome == outcome)
    if call_id:
        stmt = stmt.where(AuditRecord.call_id == call_id)
    if sub_agent_id:
        stmt = stmt.where(AuditRecord.sub_agent_id == sub_agent_id)
    if since is not None:
        stmt = stmt.where(AuditRecord.created_at >= since)
    if until is not None:
        stmt = stmt.where(AuditRecord.created_at < until)

    result = await db.execute(stmt)
    return [_audit_out(a) for a in result.scalars().all()]


@router.get("/spend")
async def get_spend(
    agent_id: str | None = Query(None),
    days: int = Query(1, ge=1, le=365),
    scope: Literal["agent", "platform"] = Query("agent"),
    provider_id: str | None = Query(None),
    model: str | None = Query(None),
    purpose: str | None = Query(None),
    kind: str | None = Query(None),
    until: datetime | None = Query(None),
    db: AsyncSession = Depends(get_db),
    _op=Depends(require_operator),
):
    """Spend summary — `scope=agent` keeps the historic Run-totals shape;
    `scope=platform` reads the model_calls ledger directly."""
    from datetime import timedelta

    if scope == "agent" and any(v is not None for v in (provider_id, model, purpose, kind, until)):
        raise HTTPException(422, "provider/model/purpose/kind/until filters require scope=platform")

    since = datetime.now(UTC) - timedelta(days=days)

    if until is not None and _utc(until) <= since:
        raise HTTPException(422, "until must be later than the since window start")

    if scope == "platform":
        return await platform_spend(
            db,
            since=since,
            until=_utc(until),
            agent_id=agent_id,
            provider_id=provider_id,
            model=model,
            purpose=purpose,
            kind=kind,
        )

    base = select(Run).where(Run.is_test == False, Run.started_at >= since)  # noqa: E712
    if agent_id:
        base = base.where(Run.agent_id == agent_id)

    # Total — apply agent_id filter if provided
    total_stmt = select(
        func.coalesce(func.sum(Run.cost), 0.0),
        func.count(Run.id),
        func.coalesce(func.sum(Run.tokens_in), 0),
        func.coalesce(func.sum(Run.tokens_out), 0),
    ).where(Run.is_test == False, Run.started_at >= since)  # noqa: E712
    if agent_id:
        total_stmt = total_stmt.where(Run.agent_id == agent_id)
    total_result = await db.execute(total_stmt)
    total_cost, total_runs, total_tokens_in, total_tokens_out = total_result.one()

    # By agent
    agent_stmt = (
        select(
            Run.agent_id,
            func.coalesce(func.sum(Run.cost), 0.0),
            func.count(Run.id),
            func.coalesce(func.sum(Run.tokens_in), 0),
            func.coalesce(func.sum(Run.tokens_out), 0),
        )
        .where(Run.is_test == False, Run.started_at >= since)  # noqa: E712
        .group_by(Run.agent_id)
    )
    if agent_id:
        agent_stmt = agent_stmt.where(Run.agent_id == agent_id)
    agent_result = await db.execute(agent_stmt)
    agent_rows = agent_result.all()
    agent_ids = {row[0] for row in agent_rows}
    agent_names: dict[str, str] = {}
    if agent_ids:
        ag_result = await db.execute(select(Agent.id, Agent.name).where(Agent.id.in_(agent_ids)))
        agent_names = {aid: name for aid, name in ag_result.all()}

    by_agent = [
        SpendBreakdown(
            agent_id=aid,
            agent_name=agent_names.get(aid),
            total_cost=cost,
            run_count=count,
            tokens_in=tin,
            tokens_out=tout,
        )
        for aid, cost, count, tin, tout in agent_rows
    ]

    # By trigger
    trigger_stmt = (
        select(Run.trigger, func.coalesce(func.sum(Run.cost), 0.0))
        .where(Run.is_test == False, Run.started_at >= since)  # noqa: E712
        .group_by(Run.trigger)
    )
    if agent_id:
        trigger_stmt = trigger_stmt.where(Run.agent_id == agent_id)
    trigger_result = await db.execute(trigger_stmt)
    by_trigger = {trigger: cost for trigger, cost in trigger_result.all()}

    return SpendSummary(
        total_cost=total_cost or 0.0,
        total_runs=total_runs or 0,
        total_tokens_in=total_tokens_in or 0,
        total_tokens_out=total_tokens_out or 0,
        by_agent=by_agent,
        by_trigger=by_trigger,
    )


@router.get("/operator-audit")
async def list_operator_audit(
    limit: int = Query(50, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    _op=Depends(require_operator),
) -> list[OperatorAuditOut]:
    """List operator audit log entries."""
    result = await db.execute(
        select(OperatorAuditLog)
        .order_by(OperatorAuditLog.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    return [
        OperatorAuditOut(
            id=oal.id,
            operator_id=oal.operator_id,
            action=oal.action,
            target=oal.target,
            created_at=oal.created_at,
        )
        for oal in result.scalars().all()
    ]


@router.get("/health")
async def system_health(
    db: AsyncSession = Depends(get_db),
    _op=Depends(require_operator),
) -> HealthStatus:
    """System health check — DB, provider count, agent count, active runs, sandbox."""
    from .. import __version__
    from ..run_manager import list_active_runs

    provider_count = (await db.execute(select(func.count(Provider.id)))).scalar() or 0
    agent_count = (await db.execute(select(func.count(Agent.id)))).scalar() or 0
    active_runs = len(list_active_runs())
    # Probing spawns subprocesses while no backend is usable; keep that off the loop.
    sandbox = await asyncio.to_thread(sandbox_probe)

    return HealthStatus(
        status="ok",
        database="connected",
        providers=provider_count,
        agents=agent_count,
        active_runs=active_runs,
        sandbox=SandboxStatus(
            kind=sandbox.kind,
            state=sandbox.state,
            reason=sandbox.reason,
            setup_required=sandbox.setup_required,
        ),
        version=__version__,
        timestamp=datetime.now(UTC),
    )


# --- Dashboard stats (Langfuse-style overview) ---


class TimeSeriesPoint(BaseModel):
    date: str  # YYYY-MM-DD
    runs: int
    cost: float
    tokens: int
    errors: int


class AgentStat(BaseModel):
    agent_id: str
    agent_name: str | None = None
    run_count: int
    total_cost: float
    total_tokens: int
    error_count: int
    last_active: datetime | None = None


class DashboardStats(BaseModel):
    total_runs: int
    total_cost: float
    total_tokens: int
    error_count: int
    error_rate: float
    avg_latency_ms: float
    time_series: list[TimeSeriesPoint]
    by_agent: list[AgentStat]
    recent_runs: list[RunSummary]


@router.get("/stats")
async def get_dashboard_stats(
    days: int = Query(7, ge=1, le=90),
    db: AsyncSession = Depends(get_db),
    _op=Depends(require_operator),
) -> DashboardStats:
    """Dashboard overview stats — KPIs, time-series, per-agent, recent runs."""
    from datetime import timedelta

    now = datetime.now(UTC)
    since = now - timedelta(days=days)

    # --- KPIs ---
    kpi_result = await db.execute(
        select(
            func.count(Run.id),
            func.coalesce(func.sum(Run.cost), 0.0),
            func.coalesce(func.sum(Run.tokens_in + Run.tokens_out), 0),
            func.count(Run.id).filter(Run.status == "failed"),
            func.coalesce(func.avg(Run.latency_ms), 0.0),
        ).where(Run.is_test == False, Run.started_at >= since)  # noqa: E712
    )
    total_runs, total_cost, total_tokens, error_count, avg_latency = kpi_result.one()
    error_rate = (error_count / total_runs * 100) if total_runs > 0 else 0.0

    # --- Time series (daily aggregation) ---
    # Use func.date to truncate to day
    date_col = func.date(Run.started_at).label("run_date")
    ts_result = await db.execute(
        select(
            date_col,
            func.count(Run.id),
            func.coalesce(func.sum(Run.cost), 0.0),
            func.coalesce(func.sum(Run.tokens_in + Run.tokens_out), 0),
            func.count(Run.id).filter(Run.status == "failed"),
        )
        .where(Run.is_test == False, Run.started_at >= since)  # noqa: E712
        .group_by(date_col)
        .order_by(date_col)
    )
    ts_map: dict[str, TimeSeriesPoint] = {}
    for row in ts_result.all():
        d = str(row[0])
        ts_map[d] = TimeSeriesPoint(
            date=d,
            runs=row[1],
            cost=row[2] or 0.0,
            tokens=row[3] or 0,
            errors=row[4],
        )

    # Fill missing days with zeros
    time_series: list[TimeSeriesPoint] = []
    for i in range(days):
        day = (now - timedelta(days=days - 1 - i)).strftime("%Y-%m-%d")
        if day in ts_map:
            time_series.append(ts_map[day])
        else:
            time_series.append(TimeSeriesPoint(date=day, runs=0, cost=0.0, tokens=0, errors=0))

    # --- Per-agent stats ---
    agent_result = await db.execute(
        select(
            Run.agent_id,
            func.count(Run.id),
            func.coalesce(func.sum(Run.cost), 0.0),
            func.coalesce(func.sum(Run.tokens_in + Run.tokens_out), 0),
            func.count(Run.id).filter(Run.status == "failed"),
            func.max(Run.started_at),
        )
        .where(Run.is_test == False, Run.started_at >= since)  # noqa: E712
        .group_by(Run.agent_id)
        .order_by(func.sum(Run.cost).desc())
    )
    agent_rows = agent_result.all()
    agent_ids = {row[0] for row in agent_rows}
    agent_names: dict[str, str] = {}
    if agent_ids:
        ag_result = await db.execute(select(Agent.id, Agent.name).where(Agent.id.in_(agent_ids)))
        agent_names = {aid: name for aid, name in ag_result.all()}

    by_agent = [
        AgentStat(
            agent_id=aid,
            agent_name=agent_names.get(aid),
            run_count=count,
            total_cost=cost,
            total_tokens=tokens,
            error_count=errors,
            last_active=last_active,
        )
        for aid, count, cost, tokens, errors, last_active in agent_rows
    ]

    # --- Recent runs (last 10) ---
    recent_result = await db.execute(
        select(Run)
        .where(Run.is_test == False)  # noqa: E712
        .order_by(Run.started_at.desc())
        .limit(10)
    )
    recent_runs = [
        RunSummary(
            id=r.id,
            agent_id=r.agent_id,
            agent_name=agent_names.get(r.agent_id),
            session_id=r.session_id,
            status=r.status,
            trigger=r.trigger,
            tokens_in=r.tokens_in,
            tokens_out=r.tokens_out,
            cost=r.cost,
            latency_ms=r.latency_ms,
            is_test=r.is_test,
            started_at=r.started_at,
            completed_at=r.completed_at,
            error=r.error,
        )
        for r in recent_result.scalars().all()
    ]

    return DashboardStats(
        total_runs=total_runs or 0,
        total_cost=total_cost or 0.0,
        total_tokens=total_tokens or 0,
        error_count=error_count or 0,
        error_rate=round(error_rate, 1),
        avg_latency_ms=round(float(avg_latency or 0), 0),
        time_series=time_series,
        by_agent=by_agent,
        recent_runs=recent_runs,
    )
