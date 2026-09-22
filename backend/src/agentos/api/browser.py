"""Browser runtime management API (W4).

Operator-facing lifecycle for the managed browser runtime — status,
install, remove. The W12 Dependencies tab surfaces this; a tool call never
triggers it silently.
"""

from fastapi import APIRouter, Depends

from ..auth import require_operator
from ..browser import runtime
from ..models.operator import Operator

router = APIRouter(prefix="/api/browser", tags=["browser"])


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
