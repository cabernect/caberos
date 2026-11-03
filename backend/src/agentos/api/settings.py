"""Global app settings API — runtime toggles like YOLO mode."""

import json
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import require_operator
from ..config import env_pinned, settings
from ..db import get_db
from ..models.operator import Operator, OperatorAuditLog

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


# --- Global tool bindings (W5) ----------------------------------------------
# How supported tools execute — engine options or provider/model — kept
# separate from per-agent capability authority. No provider calls happen
# here: validation is local-only by contract.

from ..capabilities.bindings import (  # noqa: E402
    BINDING_SPECS,
    BindingSpec,
    resolve_binding,
    spec_for,
    validate_options,
)
from ..models.provider import Provider  # noqa: E402
from ..models.tool_binding import ToolBinding  # noqa: E402


def _options_schema(spec: BindingSpec) -> list[dict[str, Any]]:
    return [
        {
            "name": f.name,
            "kind": f.kind,
            "label": f.label,
            "default": f.default,
            "choices": list(f.choices),
            "required": f.required,
        }
        for f in spec.option_fields
    ]


async def _binding_out(db: AsyncSession, spec: BindingSpec) -> dict[str, Any]:
    resolution = await resolve_binding(db, spec.key)
    provider = resolution.provider
    return {
        "key": spec.key,
        "title": spec.title,
        "description": spec.description,
        "kind": spec.kind,
        "implemented": spec.implemented,
        "planned_note": spec.planned_note,
        "capability_names": list(spec.capability_names),
        "state": resolution.state,
        "ready": resolution.ready,
        "reason": resolution.reason,
        "options": resolution.options,
        "options_schema": _options_schema(spec),
        "binding": (
            {
                "provider_id": resolution.binding.provider_id,
                "provider_name": provider.name if provider else None,
                "provider_type": provider.type if provider else None,
                "model": resolution.binding.model,
                "revision": resolution.binding.revision,
                "updated_at": resolution.binding.updated_at.isoformat()
                if resolution.binding.updated_at
                else None,
            }
            if resolution.binding
            else None
        ),
    }


@router.get("/tools")
async def list_tool_bindings(
    operator: Operator = Depends(require_operator),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Every bindable tool with resolution state — configured, ready or
    unimplemented reasons kept separate. Never returns secrets."""
    return {
        "tools": [await _binding_out(db, spec) for spec in BINDING_SPECS],
    }


class ToolBindingUpdate(BaseModel):
    provider_id: str | None = None
    model: str | None = None
    options: dict[str, Any] | None = None
    # Optimistic concurrency — required only when a binding already exists.
    expected_revision: int | None = None


@router.put("/tools/{key}")
async def put_tool_binding(
    key: str,
    req: ToolBindingUpdate,
    operator: Operator = Depends(require_operator),
    db: AsyncSession = Depends(get_db),
) -> dict:
    spec = spec_for(key)
    if spec is None:
        raise HTTPException(status_code=404, detail=f"unknown tool binding: {key}")
    if not spec.implemented:
        raise HTTPException(
            status_code=422,
            detail=f"{spec.title} is not implemented in this release — "
            "there is nothing to bind yet",
        )

    provider: Provider | None = None
    if spec.kind == "engine":
        if req.provider_id:
            raise HTTPException(status_code=422, detail="engine bindings do not take a provider")
        if req.model:
            raise HTTPException(status_code=422, detail="engine bindings do not take a model")
    else:  # model-backed
        if not req.provider_id:
            raise HTTPException(status_code=422, detail="a provider is required for this tool")
        provider = await db.get(Provider, req.provider_id)
        if provider is None:
            raise HTTPException(status_code=422, detail="provider not found")
        if req.model is None or not req.model.strip():
            raise HTTPException(status_code=422, detail="a model name is required")

    try:
        options = validate_options(spec, req.options or {})
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e

    binding = await db.scalar(select(ToolBinding).where(ToolBinding.key == key))
    if binding is not None:
        if req.expected_revision is not None and req.expected_revision != binding.revision:
            raise HTTPException(
                status_code=409,
                detail=f"binding changed since you loaded it "
                f"(revision {binding.revision}) — reload and retry",
            )
        binding.provider_id = provider.id if provider else None
        binding.model = req.model.strip() if req.model else ""
        binding.options = json.dumps(options)
        binding.revision += 1
    else:
        binding = ToolBinding(
            id=str(uuid.uuid4()),
            key=key,
            provider_id=provider.id if provider else None,
            model=req.model.strip() if req.model else "",
            options=json.dumps(options),
            revision=1,
        )
        db.add(binding)

    db.add(
        OperatorAuditLog(
            id=str(uuid.uuid4()),
            operator_id=operator.id,
            action="tool_binding.update",
            target=f"{key} rev {binding.revision}",
        )
    )
    await db.commit()
    return await _binding_out(db, spec)


@router.delete("/tools/{key}")
async def reset_tool_binding(
    key: str,
    operator: Operator = Depends(require_operator),
    db: AsyncSession = Depends(get_db),
) -> dict:
    spec = spec_for(key)
    if spec is None:
        raise HTTPException(status_code=404, detail=f"unknown tool binding: {key}")
    binding = await db.scalar(select(ToolBinding).where(ToolBinding.key == key))
    if binding is not None:
        await db.delete(binding)
        db.add(
            OperatorAuditLog(
                id=str(uuid.uuid4()),
                operator_id=operator.id,
                action="tool_binding.reset",
                target=key,
            )
        )
        await db.commit()
    return await _binding_out(db, spec)
