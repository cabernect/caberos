"""Global app settings API — runtime toggles like YOLO mode."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..auth import require_operator
from ..config import env_pinned, settings
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
    from ..config import env_pinned, persist_setting

    if env_pinned("yolo_mode"):
        raise HTTPException(
            status_code=409,
            detail="yolo_mode is pinned by AGENTOS_YOLO_MODE — "
            "remove it from the environment or .env to manage it here",
        )
    persist_setting("yolo_mode", req.yolo_mode)
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
    from pathlib import Path

    from ..browser.runtime import detected_browsers, find_browser_binary, runtime_status

    resolved = find_browser_binary()
    override = settings.browser_binary
    return BrowserSettingsOut(
        binary_override=str(Path(override).expanduser().resolve()) if override else "",
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
    override = str(Path(override).expanduser().resolve()) if override else ""
    persist_setting("browser_binary", override)
    resolved = find_browser_binary()
    from ..browser.runtime import detected_browsers

    return BrowserSettingsOut(
        binary_override=override,
        override_source=_override_source(),
        resolved_binary=str(resolved) if resolved else None,
        detected=detected_browsers(),
        runtime=runtime_status(),
    )


class ModelCatalogStatusOut(BaseModel):
    auto_refresh: bool
    pinned: bool
    available: bool
    source: str
    revision: str | None
    fetched_at: str | None
    refresh_in_progress: bool
    last_error: str | None


class ModelCatalogUpdate(BaseModel):
    auto_refresh: bool


def _catalog_status() -> ModelCatalogStatusOut:
    from ..providers.catalog import get_catalog_snapshot

    st = get_catalog_snapshot().status()
    return ModelCatalogStatusOut(
        auto_refresh=settings.model_catalog_auto_refresh,
        pinned=env_pinned("model_catalog_auto_refresh"),
        available=st["available"],
        source=st["source"],
        revision=st["revision"],
        fetched_at=st["fetched_at"],
        refresh_in_progress=st["refresh_in_progress"],
        last_error=st["last_error"],
    )


@router.get("/model-catalog")
async def get_model_catalog(
    operator: Operator = Depends(require_operator),
) -> ModelCatalogStatusOut:
    """Local catalog status — never fetches."""
    return _catalog_status()


@router.put("/model-catalog")
async def set_model_catalog(
    req: ModelCatalogUpdate,
    operator: Operator = Depends(require_operator),
) -> ModelCatalogStatusOut:
    from ..config import persist_setting

    if env_pinned("model_catalog_auto_refresh"):
        raise HTTPException(
            status_code=409,
            detail="model_catalog_auto_refresh is pinned by "
            "AGENTOS_MODEL_CATALOG_AUTO_REFRESH — remove it to manage here",
        )
    persist_setting("model_catalog_auto_refresh", req.auto_refresh)
    return _catalog_status()


@router.post("/model-catalog/refresh")
async def refresh_model_catalog(
    operator: Operator = Depends(require_operator),
) -> dict:
    """Explicit operator refresh — the only fetch path besides the
    consent-gated daily worker. Runs the deduplicated snapshot job."""
    from ..providers.catalog import get_catalog_snapshot

    snapshot = get_catalog_snapshot()
    snapshot.schedule_refresh()
    return {
        "scheduled": True,
        **_catalog_status().model_dump(),
    }
