"""Elicitation API — list pending elicitation requests, respond to them.

When the agent calls `agent.ask_user(question)`, the mediator creates an
ElicitationRequest and pauses the run. The user responds via this API,
which sets the asyncio.Event in the elicitation registry, unblocking the run.
"""

import json

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import require_operator
from ..db import get_db
from ..models.elicitation import ElicitationRequest
from ..models.operator import Operator
from ..syscall.elicitation_registry import elicitation_registry

router = APIRouter(prefix="/api/elicitation", tags=["elicitation"])


class ElicitationOut(BaseModel):
    id: str
    run_id: str
    question: str
    options: list[str] | None = None
    status: str


class ElicitationResponse(BaseModel):
    response: str


@router.get("", response_model=list[ElicitationOut])
async def list_pending_elicitation(
    db: AsyncSession = Depends(get_db),
    operator: Operator = Depends(require_operator),
) -> list[ElicitationOut]:
    """List all pending elicitation requests."""
    result = await db.execute(
        select(ElicitationRequest).where(ElicitationRequest.status == "pending")
    )
    rows = result.scalars().all()
    return [
        ElicitationOut(
            id=r.id,
            run_id=r.run_id,
            question=r.question,
            options=json.loads(r.options) if r.options else None,
            status=r.status,
        )
        for r in rows
    ]


@router.post("/{elicitation_id}/respond")
async def respond_to_elicitation(
    elicitation_id: str,
    body: ElicitationResponse,
    db: AsyncSession = Depends(get_db),
    operator: Operator = Depends(require_operator),
) -> dict:
    """Respond to a pending elicitation request. Unblocks the paused run."""
    # Find the elicitation request
    result = await db.execute(
        select(ElicitationRequest).where(ElicitationRequest.id == elicitation_id)
    )
    elicitation = result.scalar_one_or_none()
    if elicitation is None:
        raise HTTPException(status_code=404, detail="Elicitation request not found")
    if elicitation.status != "pending":
        raise HTTPException(
            status_code=400,
            detail=f"Elicitation already {elicitation.status}",
        )

    # Resolve the asyncio.Event — this unblocks the mediator
    resolved = elicitation_registry.resolve(elicitation_id, body.response, operator.id)
    if not resolved:
        raise HTTPException(
            status_code=500,
            detail="Elicitation event not found in registry (process may have restarted)",
        )

    return {"status": "answered", "elicitation_id": elicitation_id}
