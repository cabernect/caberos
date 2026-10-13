"""Provider management API routes (D39, D40).

Providers are first-class configured entities. Keys are encrypted at rest,
never returned in plaintext. Model discovery is dynamic where available
(OpenAI, Google, Ollama), free-text fallback otherwise (Anthropic).
"""

import json
import logging
import uuid
from datetime import UTC

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..agent_service import get_active_config, save_agent
from ..auth import require_operator
from ..db import get_db
from ..harness.litellm_adapter import LiteLLMAdapter
from ..models.agent import Agent
from ..models.operator import Operator
from ..models.provider import Provider
from ..notifications import create_notification
from ..secret_store import encrypt

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/providers", tags=["providers"])


def classify_provider_error(error: str) -> tuple[str, str]:
    message = error.lower()
    if "429" in message or "rate limit" in message or "too many requests" in message:
        return "rate_limit", "The provider rate limit was reached. Wait and try again."
    if any(
        term in message
        for term in ("401", "403", "unauthorized", "invalid api key", "authentication")
    ):
        return "authentication", "Check the provider credentials in Settings."
    if any(term in message for term in ("timeout", "timed out", "connection", "ssl", "dns")):
        return "network", "Check your network connection and provider endpoint."
    return "internal", "The provider returned an unexpected error. Check the gateway logs."


class ProviderCreate(BaseModel):
    name: str
    type: str  # openai, anthropic, google, ollama, azure, ...
    api_key: str | None = None  # plaintext on input, encrypted at rest
    base_url: str | None = None
    org_id: str | None = None
    extra_params: dict | None = None


class ProviderUpdate(BaseModel):
    name: str | None = None
    api_key: str | None = None  # if provided, re-encrypt
    base_url: str | None = None
    org_id: str | None = None
    extra_params: dict | None = None


class ProviderOut(BaseModel):
    id: str
    name: str
    type: str
    has_key: bool
    base_url: str | None = None
    org_id: str | None = None
    extra_params: dict = {}
    custom_models: list[str] = []

    @classmethod
    def from_model(cls, p: Provider) -> "ProviderOut":
        return cls(
            id=p.id,
            name=p.name,
            type=p.type,
            has_key=p.encrypted_key is not None,
            base_url=p.base_url,
            org_id=p.org_id,
            extra_params=json.loads(p.extra_params) if p.extra_params else {},
            custom_models=json.loads(p.custom_models) if p.custom_models else [],
        )


class ModelInfo(BaseModel):
    id: str
    name: str
    supports_vision: bool = False
    supports_thinking: bool = False
    thinking_efforts: list[str] = []
    max_context_tokens: int | None = None
    context_window_tokens: int | None = None
    max_output_tokens: int | None = None
    # W11 additive fields — optional so older rows stay valid.
    display_name: str | None = None
    availability: str | None = None  # available | unavailable | unknown
    lifecycle: str | None = None
    provenance: dict | None = None
    pricing: dict | None = None
    revision: int | None = None
    snapshot_revision: str | None = None
    discovery_error: str | None = None
    stale: bool | None = None
    last_confirmed_at: str | None = None


@router.get("")
async def list_providers(
    operator: Operator = Depends(require_operator),
    db: AsyncSession = Depends(get_db),
) -> list[ProviderOut]:
    result = await db.execute(select(Provider).order_by(Provider.name))
    return [ProviderOut.from_model(p) for p in result.scalars().all()]


@router.post("")
async def create_provider(
    data: ProviderCreate,
    operator: Operator = Depends(require_operator),
    db: AsyncSession = Depends(get_db),
) -> ProviderOut:
    provider = Provider(
        id=str(uuid.uuid4()),
        name=data.name,
        type=data.type,
        encrypted_key=encrypt(data.api_key) if data.api_key else None,
        base_url=data.base_url,
        org_id=data.org_id,
        extra_params=json.dumps(data.extra_params or {}),
    )
    db.add(provider)
    await db.commit()
    await db.refresh(provider)
    from ..providers.model_catalog import schedule_provider_refresh

    schedule_provider_refresh(provider.id)
    return ProviderOut.from_model(provider)


@router.get("/{provider_id}")
async def get_provider(
    provider_id: str,
    operator: Operator = Depends(require_operator),
    db: AsyncSession = Depends(get_db),
) -> ProviderOut:
    result = await db.execute(select(Provider).where(Provider.id == provider_id))
    provider = result.scalar_one_or_none()
    if provider is None:
        raise HTTPException(status_code=404, detail="Provider not found")
    return ProviderOut.from_model(provider)


@router.put("/{provider_id}")
async def update_provider(
    provider_id: str,
    data: ProviderUpdate,
    operator: Operator = Depends(require_operator),
    db: AsyncSession = Depends(get_db),
) -> ProviderOut:
    result = await db.execute(select(Provider).where(Provider.id == provider_id))
    provider = result.scalar_one_or_none()
    if provider is None:
        raise HTTPException(status_code=404, detail="Provider not found")

    if data.name is not None:
        provider.name = data.name
    if data.api_key is not None:
        provider.encrypted_key = encrypt(data.api_key)
    if data.base_url is not None:
        provider.base_url = data.base_url
    if data.org_id is not None:
        provider.org_id = data.org_id
    if data.extra_params is not None:
        provider.extra_params = json.dumps(data.extra_params)

    await db.commit()
    await db.refresh(provider)
    from ..providers.model_catalog import schedule_provider_refresh

    schedule_provider_refresh(provider.id)
    return ProviderOut.from_model(provider)


@router.delete("/{provider_id}")
async def delete_provider(
    provider_id: str,
    operator: Operator = Depends(require_operator),
    db: AsyncSession = Depends(get_db),
) -> dict:
    result = await db.execute(select(Provider).where(Provider.id == provider_id))
    provider = result.scalar_one_or_none()
    if provider is None:
        raise HTTPException(status_code=404, detail="Provider not found")

    # Find all agents whose active config references this provider.
    # Clear their model config so they don't point to a deleted provider.
    affected_agents: list[str] = []
    agent_result = await db.execute(select(Agent))
    for agent in agent_result.scalars().all():
        config = await get_active_config(db, agent.id)
        if config and config.model.provider_id == provider_id:
            config.model.provider_id = ""
            config.model.name = ""
            await save_agent(db, config)
            affected_agents.append(agent.id)

    await db.delete(provider)
    await db.commit()
    return {"status": "deleted", "affected_agents": affected_agents}


@router.get("/{provider_id}/models")
async def list_models(
    provider_id: str,
    operator: Operator = Depends(require_operator),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Local resolved offerings (D40) — never fetches, never validates.

    Populated by the scheduled/explicit discovery path; a provider with
    no discovery yet reports unknown availability rather than a fake
    empty list.
    """
    from ..providers.catalog import get_catalog_snapshot
    from ..providers.model_catalog import list_offerings, provider_refresh_in_progress

    result = await db.execute(select(Provider).where(Provider.id == provider_id))
    provider = result.scalar_one_or_none()
    if provider is None:
        raise HTTPException(status_code=404, detail="Provider not found")

    offerings = await list_offerings(db, provider_id)
    by_id = {o.model_id: o for o in offerings}
    custom = json.loads(provider.custom_models) if provider.custom_models else []
    # Custom names without an offering yet surface as unknown too.

    # Snapshot freshness gate — a stale active pointer still serves, but
    # the UI should show it as aged, not live.
    snapshot = get_catalog_snapshot()
    snapshot_status = snapshot.status()
    snapshot_sha = snapshot_status.get("revision")
    fetched_at = snapshot_status.get("fetched_at")
    snapshot_stale = None
    if fetched_at:
        try:
            from datetime import datetime

            snapshot_stale = (
                datetime.now(UTC) - datetime.fromisoformat(fetched_at)
            ).total_seconds() >= 86400
        except Exception:
            snapshot_stale = None

    models: list[ModelInfo] = []
    for offering in offerings:
        resolved = json.loads(offering.resolved_json or "{}")
        prov = resolved.pop("provenance", {}) or {}
        models.append(
            ModelInfo(
                id=offering.model_id,
                name=offering.model_id,  # exact request id — never a display alias
                display_name=resolved.get("display_name"),
                supports_vision=resolved.get("supports_vision", False),
                supports_thinking=resolved.get("supports_thinking", False),
                thinking_efforts=resolved.get("thinking_efforts", []),
                max_context_tokens=resolved.get("max_context_tokens"),
                context_window_tokens=resolved.get("context_window_tokens"),
                max_output_tokens=resolved.get("max_output_tokens"),
                availability=offering.discovery_state,
                lifecycle=resolved.get("lifecycle"),
                provenance=prov or None,
                pricing=resolved.get("pricing"),
                revision=offering.revision,
                snapshot_revision=offering.snapshot_revision or None,
                discovery_error=offering.discovery_error,
                stale=snapshot_stale,
                last_confirmed_at=(
                    offering.discovered_at.isoformat() if offering.discovered_at else None
                ),
            )
        )
    for name in custom:
        if name not in by_id:
            models.append(ModelInfo(id=name, name=name, availability="unknown"))

    # Composite revision: snapshot SHA + provider config fingerprint +
    # summed row revisions — a collision on max(row.rev) can't hide a
    # snapshot or config change.
    import hashlib as _hashlib

    rev_material = "|".join(
        [
            str(snapshot_sha or "none"),
            provider.type or "",
            provider.base_url or "",
            ",".join(f"{o.model_id}:{o.revision}" for o in offerings),
        ]
    )
    return {
        "discovery": "dynamic",
        "models": models,
        "revision": _hashlib.sha256(rev_material.encode()).hexdigest(),
        "fetched_at": fetched_at,
        "snapshot_revision": snapshot_sha,
        "refresh_in_progress": provider_refresh_in_progress(provider_id),
    }


@router.post("/{provider_id}/models/refresh")
async def refresh_models(
    provider_id: str,
    operator: Operator = Depends(require_operator),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Explicit provider discovery — schedules the bounded job."""
    from ..providers.model_catalog import schedule_provider_refresh

    result = await db.execute(select(Provider).where(Provider.id == provider_id))
    if result.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="Provider not found")
    schedule_provider_refresh(provider_id)
    return {"scheduled": True}


class ModelMetadataIn(BaseModel):
    fields: dict = {}
    catalog_provider_id: str | None = None
    catalog_model_id: str | None = None
    clear_catalog_mapping: bool = False


@router.put("/{provider_id}/models/{model_name:path}/metadata")
async def set_model_metadata(
    provider_id: str,
    model_name: str,
    body: ModelMetadataIn,
    operator: Operator = Depends(require_operator),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Operator-declared overrides + explicit catalog mapping.

    Overrides are validated per field — invalid values 400, they never
    coerce into model facts. The mapping is the only way a non-official
    provider claims a catalog offering.
    """
    from ..providers.model_catalog import update_override

    result = await db.execute(select(Provider).where(Provider.id == provider_id))
    if result.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="Provider not found")
    try:
        offering = await update_override(
            db,
            provider_id,
            model_name,
            body.fields,
            catalog_provider_id=body.catalog_provider_id,
            catalog_model_id=body.catalog_model_id,
            clear_catalog_mapping=body.clear_catalog_mapping,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    await db.commit()
    resolved = json.loads(offering.resolved_json or "{}")
    return {"resolved": resolved, "revision": offering.revision}


@router.post("/{provider_id}/validate")
async def validate_model(
    provider_id: str,
    body: dict,
    operator: Operator = Depends(require_operator),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Validate a model config with a cheap 1-token completion (D40)."""
    model_name = body.get("model_name")
    if not model_name:
        raise HTTPException(status_code=400, detail="model_name is required")

    result = await db.execute(select(Provider).where(Provider.id == provider_id))
    provider = result.scalar_one_or_none()
    if provider is None:
        raise HTTPException(status_code=404, detail="Provider not found")

    adapter = LiteLLMAdapter(db)
    try:
        await adapter.validate_model(provider_id, model_name)
        return {"valid": True}
    except Exception as error:
        log.exception("Provider model validation failed for provider %s", provider.id)
        error_type, guidance = classify_provider_error(str(error))
        await create_notification(
            db,
            notification_type=f"provider_{error_type}",
            severity="error",
            title=f"Provider {error_type.replace('_', ' ')}: {provider.name}",
            message=guidance,
            action_path="/settings",
            entity_id=provider.id,
        )
        await db.commit()
        return {"valid": False, "error": guidance}


class CustomModelIn(BaseModel):
    model_name: str


@router.post("/{provider_id}/models")
async def add_custom_model(
    provider_id: str,
    body: CustomModelIn,
    operator: Operator = Depends(require_operator),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Add a custom model name to a provider (for providers without discovery)."""
    result = await db.execute(select(Provider).where(Provider.id == provider_id))
    provider = result.scalar_one_or_none()
    if provider is None:
        raise HTTPException(status_code=404, detail="Provider not found")

    models = json.loads(provider.custom_models) if provider.custom_models else []
    name = body.model_name.strip()
    if name and name not in models:
        models.append(name)
        provider.custom_models = json.dumps(models)
        await db.commit()
    return {"custom_models": models}


@router.delete("/{provider_id}/models/{model_name:path}")
async def remove_custom_model(
    provider_id: str,
    model_name: str,
    operator: Operator = Depends(require_operator),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Remove a custom model from a provider."""
    result = await db.execute(select(Provider).where(Provider.id == provider_id))
    provider = result.scalar_one_or_none()
    if provider is None:
        raise HTTPException(status_code=404, detail="Provider not found")

    models = json.loads(provider.custom_models) if provider.custom_models else []
    if model_name in models:
        models.remove(model_name)
        provider.custom_models = json.dumps(models)
        await db.commit()
    return {"custom_models": models}
