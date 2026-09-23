"""Global app settings API — runtime toggles like YOLO mode."""

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from ..auth import require_operator
from ..config import settings
from ..models.operator import Operator

router = APIRouter(prefix="/api/settings", tags=["settings"])


class YoloModeOut(BaseModel):
    yolo_mode: bool


class YoloModeUpdate(BaseModel):
    yolo_mode: bool


@router.get("/yolo")
async def get_yolo_mode(
    operator: Operator = Depends(require_operator),
) -> YoloModeOut:
    return YoloModeOut(yolo_mode=settings.yolo_mode)


@router.put("/yolo")
async def set_yolo_mode(
    req: YoloModeUpdate,
    operator: Operator = Depends(require_operator),
) -> YoloModeOut:
    settings.yolo_mode = req.yolo_mode
    return YoloModeOut(yolo_mode=settings.yolo_mode)


# --- Browser runtime ------------------------------------------------------


class BrowserSettingsOut(BaseModel):
    binary_override: str
    override_source: str  # "env" | "persisted" | "none"
    resolved_binary: str | None
    detected: list[dict]  # [{name, path}] installed Chromium-family browsers
    runtime: dict


class BrowserSettingsUpdate(BaseModel):
    binary_override: str = ""


def _override_source() -> str:
    from ..config import env_pinned

    if env_pinned("browser_binary"):
        return "env"
    return "persisted" if settings.browser_binary else "none"


@router.get("/browser")
async def get_browser_settings(
    operator: Operator = Depends(require_operator),
) -> BrowserSettingsOut:
    from ..browser.runtime import detected_browsers, find_browser_binary, runtime_status

    resolved = find_browser_binary()
    return BrowserSettingsOut(
        binary_override=settings.browser_binary,
        override_source=_override_source(),
        resolved_binary=str(resolved) if resolved else None,
        detected=detected_browsers(),
        runtime=runtime_status(),
    )


@router.put("/browser")
async def set_browser_settings(
    req: BrowserSettingsUpdate,
    operator: Operator = Depends(require_operator),
) -> BrowserSettingsOut:
    from pathlib import Path

    from fastapi import HTTPException

    from ..browser.runtime import find_browser_binary, runtime_status
    from ..config import env_pinned, persist_setting

    if env_pinned("browser_binary"):
        raise HTTPException(
            status_code=409,
            detail="browser_binary is pinned by AGENTOS_BROWSER_BINARY — "
            "remove it from the environment or .env to manage it here",
        )

    override = req.binary_override.strip()
    if override and not Path(override).expanduser().is_file():
        raise HTTPException(
            status_code=422,
            detail=f"not a file: {override} — point at a Chromium-family binary",
        )
    persist_setting("browser_binary", override)
    resolved = find_browser_binary()
    from ..browser.runtime import detected_browsers

    return BrowserSettingsOut(
        binary_override=settings.browser_binary,
        override_source=_override_source(),
        resolved_binary=str(resolved) if resolved else None,
        detected=detected_browsers(),
        runtime=runtime_status(),
    )
