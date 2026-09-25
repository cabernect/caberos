"""Browser runtime + profile management API (W4).

Operator-facing lifecycle: runtime status/install/remove, and named
domain-scoped persistent profiles. The W12 Dependencies tab surfaces the
runtime side; profile management lands with the browser UI. A tool call
never triggers an install or creates a profile silently.
"""

import json

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import require_operator
from ..browser import runtime
from ..db import get_db
from ..models.browser_profile import BrowserProfile
from ..models.operator import Operator

router = APIRouter(prefix="/api/browser", tags=["browser"])


# --- runtime -----------------------------------------------------------------


@router.get("/runtime")
async def get_runtime(_: Operator = Depends(require_operator)) -> dict:
    """Runtime status: installed/managed binary, or honest unavailable."""
    return runtime.runtime_status()


@router.post("/runtime/install")
async def install(_: Operator = Depends(require_operator)) -> dict:
    """Download + verify + install the pinned runtime. Operator-initiated."""
    return await runtime.install_runtime()


@router.delete("/runtime")
async def remove(_: Operator = Depends(require_operator)) -> dict:
    return runtime.remove_runtime()


# --- profiles ----------------------------------------------------------------


class ProfileCreate(BaseModel):
    name: str
    allowed_domains: list[str] = []
    description: str | None = None


def _profile_json(p: BrowserProfile) -> dict:
    return {
        "id": p.id,
        "name": p.name,
        "allowed_domains": json.loads(p.allowed_domains or "[]"),
        "description": p.description,
    }


@router.get("/profiles")
async def list_profiles(
    _: Operator = Depends(require_operator), db: AsyncSession = Depends(get_db)
) -> list[dict]:
    rows = (await db.execute(select(BrowserProfile))).scalars().all()
    return [_profile_json(p) for p in rows]


@router.post("/profiles", status_code=201)
async def create_profile(
    body: ProfileCreate,
    _: Operator = Depends(require_operator),
    db: AsyncSession = Depends(get_db),
) -> dict:
    name = body.name.strip()
    if not name:
        raise HTTPException(400, "name is required")
    exists = await db.execute(select(BrowserProfile).where(BrowserProfile.name == name))
    if exists.scalar_one_or_none():
        raise HTTPException(409, f"profile '{name}' already exists")
    domains = [d.strip().lower().lstrip("*.") for d in body.allowed_domains if d.strip()]
    p = BrowserProfile(
        name=name,
        allowed_domains=json.dumps(domains),
        description=body.description,
    )
    db.add(p)
    await db.commit()
    await db.refresh(p)
    return _profile_json(p)


@router.delete("/profiles/{profile_id}")
async def delete_profile(
    profile_id: str,
    _: Operator = Depends(require_operator),
    db: AsyncSession = Depends(get_db),
) -> dict:
    p = await db.get(BrowserProfile, profile_id)
    if p is None:
        raise HTTPException(404, "profile not found")
    await db.delete(p)
    await db.commit()
    return {"deleted": profile_id}
