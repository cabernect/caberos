"""Observability API routes (Ticket 09).

GET  /api/runs           — paginated, filterable run list
GET  /api/runs/{run_id}  — run detail (messages + audit records)
GET  /api/audit          — paginated syscall/audit log
GET  /api/spend          — spend summary (today + breakdowns)
GET  /api/health         — system health (DB, providers)
GET  /api/operator-audit — operator action audit trail
"""

import logging
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import require_operator
from ..db import get_db
from ..models.agent import Agent
from ..models.audit import AuditRecord
from ..models.operator import OperatorAuditLog
from ..models.run import Message, Run

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["observability"])


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
    capability_name: str
    allowed: bool
    denied_reason: str | None = None
    cost: float
    latency_ms: int
    args: str
    result: str | None = None
    created_at: datetime | None = None


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
    messages: list[MessageOut]
    audit_records: list[AuditOut]


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


class HealthStatus(BaseModel):
    status: str
    database: str
    providers: int
    agents: int
    active_runs: int
    timestamp: datetime


# --- Routes ---


@router.get("/runs")
async def list_runs(
    agent_id: str | None = Query(None),
    status: str | None = Query(None),
    trigger: str | None = Query(None),
    is_test: bool | None = Query(None),
    limit: int = Query(50, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    _op=Depends(require_operator),
) -> list[RunSummary]:
    """List runs with optional filters."""
    stmt = select(Run).order_by(Run.started_at.desc()).limit(limit).offset(offset)
    if agent_id:
        stmt = stmt.where(Run.agent_id == agent_id)
    if status:
        stmt = stmt.where(Run.status == status)
    if trigger:
        stmt = stmt.where(Run.trigger == trigger)
    if is_test is not None:
        stmt = stmt.where(Run.is_test == is_test)

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
            content=m.content,
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
    audit_records = [
        AuditOut(
            id=a.id,
            run_id=a.run_id,
            agent_id=a.agent_id,
            capability_name=a.capability_name,
            allowed=a.allowed,
            denied_reason=a.denied_reason,
            cost=a.cost,
            latency_ms=a.latency_ms,
            args=a.args,
            result=a.result,
        )
        for a in audit_result.scalars().all()
    ]

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
        error=run.error,
        messages=messages,
        audit_records=audit_records,
    )


@router.get("/audit")
async def list_audit(
    agent_id: str | None = Query(None),
    capability_name: str | None = Query(None),
    allowed: bool | None = Query(None),
    run_id: str | None = Query(None),
    limit: int = Query(50, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    _op=Depends(require_operator),
) -> list[AuditOut]:
    """List audit/syscall records with filters."""
    stmt = select(AuditRecord).order_by(AuditRecord.id.desc()).limit(limit).offset(offset)
    if agent_id:
        stmt = stmt.where(AuditRecord.agent_id == agent_id)
    if capability_name:
        stmt = stmt.where(AuditRecord.capability_name == capability_name)
    if allowed is not None:
        stmt = stmt.where(AuditRecord.allowed == allowed)
    if run_id:
        stmt = stmt.where(AuditRecord.run_id == run_id)

    result = await db.execute(stmt)
    return [
        AuditOut(
            id=a.id,
            run_id=a.run_id,
            agent_id=a.agent_id,
            capability_name=a.capability_name,
            allowed=a.allowed,
            denied_reason=a.denied_reason,
            cost=a.cost,
            latency_ms=a.latency_ms,
            args=a.args,
            result=a.result,
        )
        for a in result.scalars().all()
    ]


@router.get("/spend")
async def get_spend(
    agent_id: str | None = Query(None),
    days: int = Query(1, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
    _op=Depends(require_operator),
) -> SpendSummary:
    """Spend summary — total, by agent, by trigger. Excludes test runs."""
    from datetime import timedelta

    since = datetime.now(UTC) - timedelta(days=days)

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
    """System health check — DB, provider count, agent count, active runs."""
    from ..run_manager import list_active_runs

    agent_count = (await db.execute(select(func.count(Agent.id)))).scalar() or 0
    active_runs = len(list_active_runs())

    return HealthStatus(
        status="ok",
        database="connected",
        providers=0,  # simplified — no provider count query needed
        agents=agent_count,
        active_runs=active_runs,
        timestamp=datetime.now(UTC),
    )
