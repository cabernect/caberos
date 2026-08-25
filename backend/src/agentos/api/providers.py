"""Provider management API routes (D39, D40).

Providers are first-class configured entities. Keys are encrypted at rest,
never returned in plaintext. Model discovery is dynamic where available
(OpenAI, Google, Ollama), free-text fallback otherwise (Anthropic).
"""

import json
import uuid

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
from ..secret_store import encrypt

router = APIRouter(prefix="/api/providers", tags=["providers"])


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
    """Dynamic model discovery (D40). Returns models if the provider supports it."""
    result = await db.execute(select(Provider).where(Provider.id == provider_id))
    provider = result.scalar_one_or_none()
    if provider is None:
        raise HTTPException(status_code=404, detail="Provider not found")

    adapter = LiteLLMAdapter(db)
    models = await adapter.discover_models(provider_id)
    return {
        "discovery": "dynamic" if models else "unavailable",
        "models": [ModelInfo(**m) for m in models],
    }


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
    except Exception as e:
        return {"valid": False, "error": str(e)}


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
