"""Approval API — list pending approvals, approve or reject them (Ticket 04).

The operator views pending approvals (inline in the conversation or via a
queue page) and decides. Deciding sets the asyncio.Event in the approval
registry, unblocking the paused run.
"""

import json

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import require_operator
from ..db import get_db
from ..models.approval import ApprovalRequest
from ..models.operator import Operator
from ..models.run import Run
from ..syscall.approval_registry import approval_registry

router = APIRouter(prefix="/api/approvals", tags=["approvals"])


class ApprovalOut(BaseModel):
    id: str
    run_id: str
    agent_id: str
    capability_name: str
    args: dict
    status: str
    created_at: str
    decided_by: str | None = None
    decided_at: str | None = None

    @classmethod
    def from_model(cls, a: ApprovalRequest, agent_id: str) -> "ApprovalOut":
        return cls(
            id=a.id,
            run_id=a.run_id,
            agent_id=agent_id,
            capability_name=a.capability_name,
            args=json.loads(a.args) if a.args else {},
            status=a.status,
            created_at=a.created_at.isoformat() if a.created_at else "",
            decided_by=a.decided_by,
            decided_at=a.decided_at.isoformat() if a.decided_at else None,
        )


@router.get("")
async def list_approvals(
    status: str = "pending",
    operator: Operator = Depends(require_operator),
    db: AsyncSession = Depends(get_db),
) -> list[ApprovalOut]:
    """List approvals, filtered by status (default: pending)."""
    result = await db.execute(
        select(ApprovalRequest, Run)
        .join(Run, ApprovalRequest.run_id == Run.id)
        .where(ApprovalRequest.status == status)
        .order_by(ApprovalRequest.created_at.desc())
    )
    return [ApprovalOut.from_model(a, run.agent_id) for a, run in result.all()]


class ApproveRequest(BaseModel):
    remember: bool = False  # if True, auto-approve for this session
    remember_scope: str = "exact"  # "exact", "same_verb", "pattern", or "capability"
    remember_pattern: str | None = None  # wildcard pattern for "pattern" scope (e.g. "cd *")


@router.post("/{approval_id}/approve")
async def approve(
    approval_id: str,
    body: ApproveRequest,
    operator: Operator = Depends(require_operator),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Approve a pending approval. Unblocks the paused run.

    If `remember` is True, subsequent calls in the same session will be
    auto-approved based on `remember_scope`:
      - "exact":      same capability + same args (e.g. `cd abc` only)
      - "same_verb":  same capability + same command verb (e.g. all `cd *`)
      - "pattern":    wildcard pattern match (e.g. `git push *`, `npm test *`)
      - "capability": same capability, any args (e.g. all terminal calls)
    """
    from ..syscall.approval_registry import RememberScope

    try:
        scope = RememberScope(body.remember_scope)
    except ValueError:
        scope = RememberScope.EXACT

    result = await db.execute(select(ApprovalRequest).where(ApprovalRequest.id == approval_id))
    approval = result.scalar_one_or_none()
    if approval is None:
        raise HTTPException(status_code=404, detail="Approval not found")
    if approval.status != "pending":
        raise HTTPException(status_code=400, detail=f"Approval already {approval.status}")

    # Persist before resolving the in-process event. Otherwise the mediator
    # can wake up and write the same row while this request still holds a
    # SQLite read transaction, producing "database is locked".
    approval.status = "approved"
    approval.decided_by = operator.id
    from datetime import UTC, datetime

    approval.decided_at = datetime.now(UTC)
    await db.commit()

    # Resolve the asyncio.Event — unblocks the mediator. Persisting first also
    # handles approvals for detached runs with no in-memory event.
    approval_registry.resolve(
        approval_id,
        "approved",
        operator.id,
        remember=body.remember,
        remember_scope=scope,
        remember_pattern=body.remember_pattern,
    )

    return {"status": "approved"}


@router.post("/{approval_id}/reject")
async def reject(
    approval_id: str,
    operator: Operator = Depends(require_operator),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Reject a pending approval. The run continues with a denied result."""
    result = await db.execute(select(ApprovalRequest).where(ApprovalRequest.id == approval_id))
    approval = result.scalar_one_or_none()
    if approval is None:
        raise HTTPException(status_code=404, detail="Approval not found")
    if approval.status != "pending":
        raise HTTPException(status_code=400, detail=f"Approval already {approval.status}")

    # Persist before resolving the in-process event for the same reason as
    # approval: the mediator must not race this request on the SQLite row.
    approval.status = "rejected"
    approval.decided_by = operator.id
    from datetime import UTC, datetime

    approval.decided_at = datetime.now(UTC)
    await db.commit()
    approval_registry.resolve(approval_id, "rejected", operator.id)

    return {"status": "rejected"}
