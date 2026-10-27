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


TEST_WINDOW_SECONDS = 60


@router.post("/runtime/test-window")
async def open_test_window(_: Operator = Depends(require_operator)) -> dict:
    """Operator sanity check — launches the resolved engine visibly on
    about:blank. Not run-scoped and carries no profile scope or download
    staging. The window closes itself after TEST_WINDOW_SECONDS, or when
    the operator closes it; the scratch profile dir is removed either way.
    """
    import asyncio
    import shutil
    import tempfile
    from pathlib import Path

    from ..browser.cdp import BrowserSession, _display_available

    binary = runtime.find_browser_binary()
    if binary is None:
        raise HTTPException(
            404,
            "no browser engine resolved — install the built-in browser or set a custom path first",
        )
    if not _display_available():
        raise HTTPException(
            409,
            "no display on this host — a visible test window needs a desktop session",
        )
    # The watchdog lives in-process — if the daemon restarted mid-watch an
    # old scratch dir outlived its browser. Sweep any dir older than the
    # auto-close window (+margin) before making a new one.
    import time

    cutoff = time.time() - (TEST_WINDOW_SECONDS + 30)
    for stale in Path(tempfile.gettempdir()).glob("caberos-test-profile-*"):
        try:
            if stale.stat().st_mtime < cutoff:
                shutil.rmtree(stale, ignore_errors=True)
        except OSError:
            pass
    profile_dir = Path(tempfile.mkdtemp(prefix="caberos-test-profile-"))
    session = BrowserSession(binary, profile_dir)
    try:
        await session.open("about:blank", visible=True)
    except Exception as exc:
        shutil.rmtree(profile_dir, ignore_errors=True)
        raise HTTPException(502, f"test window failed: {exc}") from exc

    async def _watchdog() -> None:
        try:
            for _ in range(TEST_WINDOW_SECONDS * 2):
                await asyncio.sleep(0.5)
                if not session.alive():
                    break
        finally:
            await session.close()
            shutil.rmtree(profile_dir, ignore_errors=True)

    asyncio.create_task(_watchdog())
    return {
        "status": "open",
        "binary": str(binary),
        "auto_close_seconds": TEST_WINDOW_SECONDS,
    }


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
