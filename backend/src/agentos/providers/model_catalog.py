"""Provider model discovery + offering registry (W11 catalog slice).

Discovery is provider HTTP only: each adapter returns the fields the
endpoint actually reports — never LiteLLM metadata, never guessed
limits, never invented effort lists. A failed or incomplete discovery is
``unknown``/``partial``, never an authoritative absence.

Reads are detached and local: ``list_offerings`` recomputes resolution
against the *current* snapshot + provider config — stored rows, virtual
catalog entries for official providers, and custom model names merge
into one view without writing to the DB. Config changes invalidate
prior observations immediately; a proxy that moved never inherits the
old provider's facts.

``refresh_provider`` runs the bounded discovery job: config read in one
short session → HTTP → recheck-before-commit → short persist session.
Sanitized error text only (provider URLs can carry API keys).
"""

import asyncio
import hashlib
import json
import logging
import time
from datetime import UTC, datetime
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.model_catalog import ModelCatalogOffering, ModelCatalogRevision
from ..models.provider import Provider
from ..secret_store import decrypt
from ..ssl_utils import SSL_CERT_PATH as _SSL_CERT
from .catalog import _bounded_error, get_catalog_snapshot
from .catalog_policy import catalog_identity, resolve_fields, validate_overrides

logger = logging.getLogger(__name__)

PROVIDER_DISCOVERY_SECONDS = 900  # 15-minute availability cadence

_DEFAULT_BASE_URLS: dict[str, str] = {
    "deepseek": "https://api.deepseek.com/v1",
    "xai": "https://api.x.ai/v1",
    "mistral": "https://api.mistral.ai/v1",
    "groq": "https://api.groq.com/openai/v1",
    "together_ai": "https://api.together.xyz/v1",
    "fireworks_ai": "https://api.fireworks.ai/inference/v1",
    "perplexity": "https://api.perplexity.ai",
    "cohere": "https://api.cohere.com/v1",
    "ai21": "https://api.ai21.com/v1",
    "nvidia_nim": "https://integrate.api.nvidia.com/v1",
    "huggingface": "https://api-inference.huggingface.co/v1",
    "dashscope": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "moonshot": "https://api.moonshot.cn/v1",
    "zhipu": "https://open.bigmodel.cn/api/paas/v4",
    "minimax": "https://api.minimax.chat/v1",
}

# Providers return ALL models (embeddings, TTS, image gen, moderation).
# Name-pattern filtering is presentation only — not a claimed fact.
_NON_CHAT_PATTERNS: tuple[str, ...] = (
    "embedding",
    "embed",
    "whisper",
    "tts",
    "speech",
    "transcribe",
    "dall-e",
    "gpt-image",
    "chatgpt-image",
    "search-api",
    "davinci",
    "babbage",
    "ada-002",
    "moderation",
    "text-moderation",
    "audio",
    "realtime",
    "sora",
)

_DISCOVERY_PAGES = 10
_DISCOVERY_MODEL_CAP = 10_000


def _is_chat_model(model_id: str) -> bool:
    name = model_id.lower()
    return not any(pattern in name for pattern in _NON_CHAT_PATTERNS)


# --- Live discovery: observed fields only, failure raises -------------


async def discover_provider_models(provider: dict[str, Any]) -> list[dict[str, Any]] | dict:
    """Discover observed model records for a provider config dict.

    Returns the model list for complete discoveries, or
    ``{"state": "partial", "models": [...]}`` when bounded pagination
    stopped early or the response shape is incomplete. Hard failures
    raise — callers map that to "unknown". Fields are exactly what the
    endpoint reports.
    """
    ptype = provider["type"]
    if ptype == "openai":
        return await _discover_openai(provider)
    if ptype in ("gemini", "google"):
        return await _discover_gemini(provider)
    if ptype == "ollama":
        return await _discover_ollama(provider)
    if ptype == "openrouter":
        return await _discover_openrouter(provider)
    if ptype == "anthropic":
        return await _discover_anthropic(provider)
    if ptype in _DEFAULT_BASE_URLS or provider.get("base_url"):
        return await _discover_openai_compat(provider, ptype)
    raise ValueError(f"no discovery adapter for provider type {ptype}")


def _openai_shape(data: Any) -> tuple[list, bool]:
    """data[] list + complete flag — unknown shapes are partial."""
    if not isinstance(data, dict) or not isinstance(data.get("data"), list):
        return [], False
    return data["data"], True


async def _discover_openai_compat(
    provider: dict[str, Any], ptype: str
) -> list[dict[str, Any]] | dict:
    base = provider["base_url"] or _DEFAULT_BASE_URLS.get(ptype, "")
    if not base:
        raise ValueError("no base_url configured for discovery")
    headers = {}
    if provider["api_key"]:
        headers["Authorization"] = f"Bearer {provider['api_key']}"
    async with httpx.AsyncClient(verify=_SSL_CERT) as client:
        resp = await client.get(f"{base}/models", headers=headers, timeout=10)
        resp.raise_for_status()
        data = resp.json()
    items, complete = _openai_shape(data)
    models = [
        {"id": model["id"], "name": model["id"]}
        for model in items[:_DISCOVERY_MODEL_CAP]
        if isinstance(model, dict) and _is_chat_model(str(model.get("id", "")))
    ]
    if not complete or len(items) >= _DISCOVERY_MODEL_CAP:
        return {"state": "partial", "models": models}
    return models


async def _discover_openai(provider: dict[str, Any]) -> list[dict[str, Any]] | dict:
    headers = {"Authorization": f"Bearer {provider['api_key']}"}
    if provider["org_id"]:
        headers["OpenAI-Organization"] = provider["org_id"]
    base = provider["base_url"] or "https://api.openai.com/v1"
    async with httpx.AsyncClient(verify=_SSL_CERT) as client:
        resp = await client.get(f"{base}/models", headers=headers, timeout=10)
        resp.raise_for_status()
        data = resp.json()
    items, complete = _openai_shape(data)
    models = [
        {"id": model["id"], "name": model["id"]}
        for model in items[:_DISCOVERY_MODEL_CAP]
        if isinstance(model, dict) and _is_chat_model(str(model.get("id", "")))
    ]
    if not complete or len(items) >= _DISCOVERY_MODEL_CAP:
        return {"state": "partial", "models": models}
    return models


async def _discover_gemini(provider: dict[str, Any]) -> dict:
    """Paged via nextPageToken — an unexhausted page chain is partial."""
    base = provider["base_url"] or "https://generativelanguage.googleapis.com/v1beta"
    models: list[dict[str, Any]] = []
    complete = True
    page_token: str | None = None
    async with httpx.AsyncClient(verify=_SSL_CERT) as client:
        for _ in range(_DISCOVERY_PAGES):
            url = f"{base}/models?key={provider['api_key']}&pageSize=1000"
            if page_token:
                url += f"&pageToken={page_token}"
            try:
                resp = await client.get(url, timeout=10)
                resp.raise_for_status()
                data = resp.json()
            except Exception:
                complete = False
                break
            if not isinstance(data, dict) or not isinstance(data.get("models"), list):
                complete = False
                break
            for model in data["models"]:
                model_id = str(model.get("name", "")).replace("models/", "")
                if not model_id or not _is_chat_model(model_id):
                    continue
                models.append(
                    {
                        "id": model_id,
                        "name": model.get("displayName", model["name"]),
                        "display_name": model.get("displayName"),
                        # inputTokenLimit is the INPUT limit — it is not
                        # the total context window.
                        "max_context_tokens": model.get("inputTokenLimit"),
                        "max_output_tokens": model.get("outputTokenLimit"),
                    }
                )
                if len(models) >= _DISCOVERY_MODEL_CAP:
                    return {"state": "partial", "models": models}
            page_token = data.get("nextPageToken")
            if not page_token:
                break
        else:
            complete = False  # exhausted page budget while paginating
            if not page_token:
                complete = True
    return {"state": "available" if complete else "partial", "models": models}


async def _discover_ollama(provider: dict[str, Any]) -> list[dict[str, Any]] | dict:
    base = provider["base_url"] or "http://localhost:11434"
    async with httpx.AsyncClient(verify=_SSL_CERT) as client:
        resp = await client.get(f"{base}/api/tags", timeout=10)
        resp.raise_for_status()
        data = resp.json()
    items = data.get("models") if isinstance(data, dict) else None
    models = [
        {"id": model["name"], "name": model["name"]}
        for model in (items or [])[:_DISCOVERY_MODEL_CAP]
        if isinstance(model, dict) and _is_chat_model(str(model.get("name", "")))
    ]
    if not isinstance(items, list) or len(items) >= _DISCOVERY_MODEL_CAP:
        return {"state": "partial", "models": models}
    return models


async def _discover_openrouter(provider: dict[str, Any]) -> list[dict[str, Any]] | dict:
    base = provider["base_url"] or "https://openrouter.ai/api/v1"
    headers = {}
    if provider["api_key"]:
        headers["Authorization"] = f"Bearer {provider['api_key']}"
    async with httpx.AsyncClient(timeout=15.0, verify=_SSL_CERT) as client:
        resp = await client.get(f"{base}/models", headers=headers)
        resp.raise_for_status()
        data = resp.json()
    items, complete = _openai_shape(data)
    models = []
    for model in items[:_DISCOVERY_MODEL_CAP]:
        if not isinstance(model, dict):
            continue
        model_id = str(model.get("id", ""))
        if not model_id or not _is_chat_model(model_id):
            continue
        architecture = model.get("architecture") or {}
        output_modalities = architecture.get("output_modalities") or []
        if "image" in output_modalities and not model_id.startswith("openrouter/"):
            continue
        input_modalities = architecture.get("input_modalities")
        supports_vision: bool | None
        if input_modalities:
            supports_vision = "image" in input_modalities or "video" in input_modalities
        else:
            supports_vision = None  # endpoint didn't say — stays unknown
        reasoning = model.get("reasoning")
        supports_thinking = True if isinstance(reasoning, dict) else None
        efforts = reasoning.get("supported_efforts") if reasoning else None
        models.append(
            {
                "id": model_id,
                "name": model_id,
                "supports_vision": supports_vision,
                "supports_thinking": supports_thinking,
                "thinking_efforts": efforts,
                # context_length is the total window — it is not a max
                # input budget.
                "context_window_tokens": model.get("context_length"),
                "max_output_tokens": (model.get("top_provider") or {}).get("max_completion_tokens"),
            }
        )
    if not complete or len(items) >= _DISCOVERY_MODEL_CAP:
        return {"state": "partial", "models": models}
    return models


async def _discover_anthropic(provider: dict[str, Any]) -> dict:
    """Paged models API — a mid-list failure or missing cursor keeps the
    partial observations without declaring missing models absent."""
    base = provider["base_url"] or "https://api.anthropic.com"
    headers = {
        "x-api-key": provider["api_key"],
        "anthropic-version": "2023-06-01",
    }
    models: list[dict[str, Any]] = []
    complete = True
    after_id = None
    async with httpx.AsyncClient(timeout=15.0, verify=_SSL_CERT) as client:
        for _ in range(_DISCOVERY_PAGES):
            url = f"{base}/v1/models?limit=1000"
            if after_id:
                url += f"&after_id={after_id}"
            try:
                resp = await client.get(url, headers=headers)
                resp.raise_for_status()
                data = resp.json()
            except Exception:
                complete = False
                break
            items = data.get("data") if isinstance(data, dict) else None
            if not isinstance(items, list):
                complete = False
                break
            for model in items:
                capabilities = model.get("capabilities") or {}
                image_cap = capabilities.get("image_input") or {}
                thinking_caps = capabilities.get("thinking") or {}
                supports_thinking = (
                    thinking_caps.get("supported") if "supported" in thinking_caps else None
                )
                # Effort levels are only provider facts when the API
                # enumerates them; 'adaptive' is a mode, not an effort.
                efforts = None
                thinking_types = thinking_caps.get("types") or {}
                enumerated = thinking_types.get("efforts")
                if isinstance(enumerated, list):
                    efforts = [str(v) for v in enumerated if isinstance(v, (str, int))] or None
                models.append(
                    {
                        "id": model["id"],
                        "name": model.get("display_name", model["id"]),
                        "display_name": model.get("display_name"),
                        "supports_vision": (
                            image_cap.get("supported") if "supported" in image_cap else None
                        ),
                        "supports_thinking": supports_thinking,
                        "thinking_efforts": efforts,
                        # max_input_tokens is the input limit; there is
                        # no separate total-context field here.
                        "max_context_tokens": model.get("max_input_tokens"),
                        "max_output_tokens": model.get("max_tokens"),
                    }
                )
                if len(models) >= _DISCOVERY_MODEL_CAP:
                    return {"state": "partial", "models": models}
            if not data.get("has_more"):
                break
            after_id = data.get("last_id")
            if not after_id:
                complete = False
                break
        else:
            complete = False
    return {"state": "available" if complete else "partial", "models": models}


def _discoverable(provider: dict[str, Any]) -> bool:
    """Only configured, user-authorized endpoints get probed."""
    ptype = provider["type"]
    if ptype == "ollama":
        return True  # local endpoint — configuring the provider is the consent
    return bool(provider["api_key"] or provider.get("base_url"))


# --- Offering registry ------------------------------------------------

_refresh_locks: dict[str, asyncio.Lock] = {}
_provider_tasks: dict[str, asyncio.Task] = {}


def provider_refresh_in_progress(provider_id: str) -> bool:
    task = _provider_tasks.get(provider_id)
    return task is not None and not task.done()


def _fingerprint(provider: dict[str, Any]) -> str:
    key_hash = hashlib.sha256((provider.get("api_key") or "").encode()).hexdigest()
    material = json.dumps(
        {
            "type": provider["type"],
            "base_url": provider.get("base_url"),
            "org_id": provider.get("org_id"),
            "extra_params": provider.get("extra_params") or {},
            "key": key_hash,
        },
        sort_keys=True,
    )
    return hashlib.sha256(material.encode()).hexdigest()


async def _load_provider_config(db: AsyncSession, provider_id: str) -> dict[str, Any]:
    result = await db.execute(select(Provider).where(Provider.id == provider_id))
    row = result.scalar_one_or_none()
    if row is None:
        raise ValueError(f"Provider {provider_id} not found")
    return {
        "api_key": decrypt(row.encrypted_key) if row.encrypted_key else "",
        "base_url": row.base_url,
        "org_id": row.org_id,
        "extra_params": json.loads(row.extra_params) if row.extra_params else {},
        "type": row.type,
        "custom_models": json.loads(row.custom_models) if row.custom_models else [],
    }


async def _get_stored_offering(
    db: AsyncSession, provider_id: str, model_id: str
) -> ModelCatalogOffering | None:
    """The persisted row for mutators — reads use the detached view."""
    result = await db.execute(
        select(ModelCatalogOffering).where(
            ModelCatalogOffering.provider_id == provider_id,
            ModelCatalogOffering.model_id == model_id,
        )
    )
    return result.scalar_one_or_none()


def _resolved_envelope(
    offering: ModelCatalogOffering,
    catalog_model: dict | None,
    snapshot: Any,
    observed: dict,
    observed_at: str | None,
) -> dict:
    """Resolved fields + provenance envelope — what revisions record."""
    status = snapshot.status()
    snapshot_at = status.get("fetched_at")
    resolved = resolve_fields(
        catalog_model,
        observed=observed,
        overrides=json.loads(offering.overrides_json or "{}"),
        as_of=snapshot_at,
        observed_as_of=observed_at,
        override_as_of=(
            offering.overrides_updated_at.isoformat() if offering.overrides_updated_at else None
        ),
    )
    return {
        "provider_id": offering.provider_id,
        "model_id": offering.model_id,
        "offering_id": offering.id,
        "discovery_state": offering.discovery_state,
        "config_fingerprint": offering.config_fingerprint,
        "snapshot_sha256": status.get("revision"),
        "snapshot_revision": status.get("revision"),
        "discovered_at": (offering.discovered_at.isoformat() if offering.discovered_at else None),
        "overrides_updated_at": (
            offering.overrides_updated_at.isoformat() if offering.overrides_updated_at else None
        ),
        "resolved": resolved,
    }


async def _journal(db: AsyncSession, offering: ModelCatalogOffering, envelope: dict) -> None:
    db.add(
        ModelCatalogRevision(
            offering_id=offering.id,
            revision=offering.revision,
            resolved_json=json.dumps(envelope),
            created_at=datetime.now(UTC),
        )
    )
    await db.flush()


async def _upsert(
    db: AsyncSession,
    provider_id: str,
    model_id: str,
    *,
    observed: dict | None = None,
    overrides: dict | None = None,
    discovery_state: str | None = None,
    discovery_error: str | None = None,
    discovered_at: datetime | None = None,
    clear_error: bool = False,
    catalog_ids: tuple[str, str] | None = None,
    catalog_explicit: bool | None = None,
    fingerprint: str | None = None,
    snapshot_sha: str | None = None,
    override_at: datetime | None = None,
) -> ModelCatalogOffering:
    offering = await _get_stored_offering(db, provider_id, model_id)
    if offering is None:
        offering = ModelCatalogOffering(
            provider_id=provider_id,
            model_id=model_id,
            observations_json="{}",
            overrides_json="{}",
            resolved_json="{}",
            config_fingerprint=fingerprint or "",
        )
        db.add(offering)
        try:
            await db.flush()
        except Exception:
            # Lost a concurrent insert — reload and continue.
            await db.rollback()
            offering = await _get_stored_offering(db, provider_id, model_id)
            if offering is None:
                raise
    if observed is not None:
        offering.observations_json = json.dumps(observed)
    if overrides is not None:
        offering.overrides_json = json.dumps(overrides)
        if override_at is not None:
            offering.overrides_updated_at = override_at
    if discovery_state is not None:
        offering.discovery_state = discovery_state
    if discovery_error is not None:
        offering.discovery_error = discovery_error
    elif clear_error:
        offering.discovery_error = None
    if discovered_at is not None:
        offering.discovered_at = discovered_at
    if catalog_ids is not None:
        offering.catalog_provider_id, offering.catalog_model_id = catalog_ids
    if catalog_explicit is not None:
        offering.catalog_mapping_explicit = catalog_explicit
    if not offering.catalog_mapping_explicit:
        provider = await _load_provider_config(db, provider_id)
        automatic = catalog_identity(provider["type"], model_id, provider.get("base_url"))
        offering.catalog_provider_id, offering.catalog_model_id = automatic or (None, None)
    if fingerprint is not None and offering.config_fingerprint != fingerprint:
        if observed is None:
            offering.observations_json = "{}"
            offering.discovered_at = None
        if discovery_state is None:
            offering.discovery_state = "unknown"
    if fingerprint is not None:
        offering.config_fingerprint = fingerprint
    if snapshot_sha is not None:
        offering.snapshot_revision = snapshot_sha

    snapshot = get_catalog_snapshot()
    catalog_model = None
    if offering.catalog_provider_id and offering.catalog_model_id:
        catalog_model = snapshot.lookup(offering.catalog_provider_id, offering.catalog_model_id)
    observed_data = json.loads(offering.observations_json or "{}")
    envelope = _resolved_envelope(
        offering,
        catalog_model,
        snapshot,
        observed_data,
        offering.discovered_at.isoformat() if offering.discovered_at else None,
    )
    new_resolved = json.dumps(envelope["resolved"])
    if new_resolved != offering.resolved_json or discovery_state is not None:
        offering.resolved_json = new_resolved
        offering.revision += 1
        await _journal(db, offering, envelope)
    return offering


# -- public reads: detached views, recomputed against current state -----


def _view_from_stored(
    stored: ModelCatalogOffering,
    provider: dict[str, Any],
    snapshot: Any,
    fingerprint: str,
) -> ModelCatalogOffering:
    """Transient offering — same shape as the row, resolved freshly."""
    view = ModelCatalogOffering(
        id=stored.id,
        provider_id=stored.provider_id,
        model_id=stored.model_id,
        observations_json=stored.observations_json,
        overrides_json=stored.overrides_json,
        resolved_json=stored.resolved_json,
        catalog_provider_id=stored.catalog_provider_id,
        catalog_model_id=stored.catalog_model_id,
        catalog_mapping_explicit=stored.catalog_mapping_explicit,
        discovery_state=stored.discovery_state,
        discovered_at=stored.discovered_at,
        discovery_error=stored.discovery_error,
        config_fingerprint=fingerprint,
        snapshot_revision=stored.snapshot_revision,
        revision=stored.revision,
        overrides_updated_at=stored.overrides_updated_at,
    )
    config_ok = stored.config_fingerprint == fingerprint
    identity = catalog_identity(
        provider["type"],
        stored.model_id,
        provider.get("base_url"),
        catalog_provider_id=stored.catalog_provider_id if stored.catalog_mapping_explicit else None,
        catalog_model_id=stored.catalog_model_id if stored.catalog_mapping_explicit else None,
    )
    if not config_ok:
        view.discovery_state = "unknown"
        view.discovered_at = None
        view.observations_json = "{}"
        identity = (
            catalog_identity(provider["type"], stored.model_id, provider.get("base_url"))
            if not stored.catalog_mapping_explicit
            else identity
        )
    catalog_model = snapshot.lookup(identity[0], identity[1]) if identity else None
    view.snapshot_revision = snapshot.status().get("revision") or ""
    envelope = _resolved_envelope(
        view,
        catalog_model,
        snapshot,
        json.loads(view.observations_json or "{}") if config_ok else {},
        view.discovered_at.isoformat() if view.discovered_at else None,
    )
    view.resolved_json = json.dumps(envelope["resolved"])
    return view


def _virtual_offering(
    provider_id: str,
    model_id: str,
    provider: dict[str, Any],
    snapshot: Any,
    fingerprint: str,
) -> ModelCatalogOffering:
    """An offering that exists only in the catalog/custom list — never
    persisted by a read."""
    view = ModelCatalogOffering(
        id=f"virtual:{provider_id}:{model_id}",
        provider_id=provider_id,
        model_id=model_id,
        observations_json="{}",
        overrides_json="{}",
        resolved_json="{}",
        discovery_state="unknown",
        config_fingerprint=fingerprint,
        snapshot_revision=snapshot.status().get("revision") or "",
        revision=0,
    )
    identity = catalog_identity(provider["type"], model_id, provider.get("base_url"))
    catalog_model = snapshot.lookup(identity[0], identity[1]) if identity else None
    envelope = _resolved_envelope(view, catalog_model, snapshot, {}, None)
    view.resolved_json = json.dumps(envelope["resolved"])
    return view


async def list_offerings(db: AsyncSession, provider_id: str) -> list[ModelCatalogOffering]:
    """Detached read view — stored rows + virtual catalog/custom entries.

    Computes resolution against the current snapshot and the current
    provider fingerprint; performs no DB writes, holds no write txn.
    """
    provider = await _load_provider_config(db, provider_id)
    fingerprint = _fingerprint(provider)
    snapshot = get_catalog_snapshot()

    result = await db.execute(
        select(ModelCatalogOffering)
        .where(ModelCatalogOffering.provider_id == provider_id)
        .order_by(ModelCatalogOffering.model_id)
    )
    stored = list(result.scalars().all())

    views: dict[str, ModelCatalogOffering] = {}
    for row in stored:
        views[row.model_id] = _view_from_stored(row, provider, snapshot, fingerprint)

    identity = catalog_identity(provider["type"], "", provider.get("base_url"))
    if identity:
        for model_id in snapshot.models(identity[0]):
            if model_id not in views and _is_chat_model(model_id):
                views[model_id] = _virtual_offering(
                    provider_id, model_id, provider, snapshot, fingerprint
                )
    for name in provider["custom_models"]:
        if name not in views:
            views[name] = _virtual_offering(provider_id, name, provider, snapshot, fingerprint)
    return [views[k] for k in sorted(views)]


async def get_offering(
    db: AsyncSession,
    provider_id: str,
    model_id: str,
    *,
    provider_config: dict | None = None,
) -> ModelCatalogOffering | None:
    provider = provider_config or await _load_provider_config(db, provider_id)
    fingerprint = _fingerprint(provider)
    snapshot = get_catalog_snapshot()
    stored = await _get_stored_offering(db, provider_id, model_id)
    if stored is not None:
        return _view_from_stored(stored, provider, snapshot, fingerprint)
    return _virtual_offering(provider_id, model_id, provider, snapshot, fingerprint)


# -- mutations -----------------------------------------------------------


async def update_override(
    db: AsyncSession,
    provider_id: str,
    model_id: str,
    fields: dict,
    *,
    catalog_provider_id: str | None = None,
    catalog_model_id: str | None = None,
    clear_catalog_mapping: bool = False,
) -> ModelCatalogOffering:
    """Merge validated operator overrides — independent of catalog refresh."""
    provider = await _load_provider_config(db, provider_id)
    clean = validate_overrides(fields)
    stored = await _get_stored_offering(db, provider_id, model_id)
    existing = json.loads(stored.overrides_json) if stored else {}
    for key, value in clean.items():
        if value is None:
            existing.pop(key, None)
        else:
            existing[key] = value
    catalog_ids = None
    catalog_explicit = None
    if catalog_provider_id or catalog_model_id:
        identity = catalog_identity(
            provider["type"],
            model_id,
            provider.get("base_url"),
            catalog_provider_id=catalog_provider_id,
            catalog_model_id=catalog_model_id,
        )
        if identity is None:
            raise ValueError("incomplete catalog mapping")
        catalog_ids = identity
        catalog_explicit = True
    elif clear_catalog_mapping:
        # Strip the explicit mapping; automatic identity may still apply.
        catalog_ids = (None, None)
        catalog_explicit = False
    return await _upsert(
        db,
        provider_id,
        model_id,
        overrides=existing,
        catalog_ids=catalog_ids,
        catalog_explicit=catalog_explicit,
        fingerprint=_fingerprint(provider),
        snapshot_sha=get_catalog_snapshot().status().get("revision"),
        override_at=datetime.now(UTC),
    )


# -- discovery job --------------------------------------------------------


async def refresh_provider(provider_id: str, session_factory: Any) -> None:
    """One bounded discovery job per provider — dedup before scheduling."""
    if provider_id in _provider_tasks and not _provider_tasks[provider_id].done():
        return
    lock = _refresh_locks.setdefault(provider_id, asyncio.Lock())
    task = asyncio.create_task(_refresh_provider(provider_id, session_factory, lock))
    _provider_tasks[provider_id] = task


async def stop_all_provider_jobs() -> None:
    tasks = [t for t in _provider_tasks.values() if not t.done()]
    for task in tasks:
        task.cancel()
    for task in tasks:
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass
    _provider_tasks.clear()


async def _refresh_provider(provider_id: str, session_factory: Any, lock: asyncio.Lock) -> None:
    async with lock:
        # Session 1: read config only — never hold a session across HTTP.
        async with session_factory() as db:
            provider = await _load_provider_config(db, provider_id)
        fingerprint = _fingerprint(provider)
        try:
            if not _discoverable(provider):
                raise ValueError("provider has no authorized endpoint for discovery")
            discovered = await discover_provider_models(provider)
            if isinstance(discovered, dict):
                state, models = discovered["state"], discovered["models"]
            else:
                state, models = "available", discovered
            error = None
        except Exception as exc:
            state, models, error = "unknown", None, _bounded_error(exc)

        # Session 2: persist — recheck the provider still exists and the
        # config didn't change mid-fetch before trusting observations.
        async with session_factory() as db:
            try:
                current = await _load_provider_config(db, provider_id)
            except ValueError:
                return  # provider deleted mid-job — no orphan offerings
            if _fingerprint(current) != fingerprint:
                return  # config changed mid-fetch — discard stale results

            snapshot = get_catalog_snapshot()
            snap_sha = snapshot.status().get("revision")
            now = datetime.now(UTC)
            stored = {
                r.model_id: r
                for r in (
                    await db.execute(
                        select(ModelCatalogOffering).where(
                            ModelCatalogOffering.provider_id == provider_id
                        )
                    )
                )
                .scalars()
                .all()
            }
            if models is not None:
                seen = {m["id"]: m for m in models}
                for model_id, observed in seen.items():
                    identity = catalog_identity(
                        provider["type"], model_id, provider.get("base_url")
                    )
                    explicit_mapping = (
                        stored[model_id].catalog_mapping_explicit if model_id in stored else False
                    )
                    await _upsert(
                        db,
                        provider_id,
                        model_id,
                        observed={k: v for k, v in observed.items() if v is not None},
                        discovery_state="available",
                        discovered_at=now,
                        catalog_ids=None if explicit_mapping else identity,
                        catalog_explicit=None if explicit_mapping else False,
                        fingerprint=fingerprint,
                        snapshot_sha=snap_sha,
                        clear_error=True,
                    )
                if state == "available":
                    # Complete listing only: unseen existing rows became
                    # unavailable. Partial/malformed pages leave them be.
                    for model_id, row in stored.items():
                        if model_id not in seen and row.discovery_state == "available":
                            await _upsert(
                                db,
                                provider_id,
                                model_id,
                                discovery_state="unavailable",
                                fingerprint=fingerprint,
                            )
            else:
                # Failure: prior availability becomes unknown; known
                # observations and last-confirmed date stay put.
                for row in stored.values():
                    if row.discovery_state in ("available", "unavailable"):
                        await _upsert(
                            db,
                            provider_id,
                            row.model_id,
                            discovery_state="unknown",
                            discovery_error=error,
                            fingerprint=fingerprint,
                        )
            await db.commit()


def schedule_provider_refresh(provider_id: str, session_factory: Any = None) -> None:
    """Fire-and-forget refresh entry point for create/update/startup."""
    from ..db import async_session_factory

    factory = session_factory or async_session_factory
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return
    asyncio.create_task(refresh_provider(provider_id, factory))


class LiteLLMModelCatalog:
    """Execution-side validation — transport stays LiteLLM (separate
    from catalog reads; validate_model performs a real paid probe)."""

    def __init__(self, adapter: Any):
        self.adapter = adapter

    async def validate_model(self, provider_id: str, model_name: str) -> bool:
        """Cheap completion to validate the model config at save time.

        Follows the adapter's endpoint routing — api.openai.com models
        validate on /v1/responses (chat completions rejects reasoning
        models like gpt-6-luna, and 'max_tokens' isn't accepted there).
        Every probe is recorded on the model-call ledger (kind='probe').
        """
        provider = await self.adapter._load_provider(provider_id)
        model_str, api_base = self.adapter._route_model(provider, model_name)
        family = self.adapter._model_family(provider, model_name)
        # Frozen pre-call rate authority — a capture failure degrades to the
        # unknown snapshot so a genuine provider amount is still preserved.
        from ..services.call_accounting import (
            capture_call_rates,
            unknown_call_rates,
        )

        try:
            snapshot = await capture_call_rates(self.adapter.db, provider_id, model_name, provider)
        except Exception:
            snapshot = unknown_call_rates(provider_id, model_name, provider)
        started = time.perf_counter()
        raw = None
        error: BaseException | None = None
        try:
            if family == "responses":
                kwargs: dict[str, Any] = {
                    "model": model_str,
                    "input": [{"role": "user", "content": "Hi"}],
                    "max_output_tokens": 16,
                }
                if provider["api_key"]:
                    kwargs["api_key"] = provider["api_key"]
                if api_base or provider["base_url"]:
                    kwargs["api_base"] = api_base or provider["base_url"]
                kwargs.update(provider["extra_params"])
                raw = await self.adapter.transport.responses(**kwargs)
                return True

            kwargs = {
                "model": model_str,
                "messages": [{"role": "user", "content": "Hi"}],
                "max_tokens": 1,
            }
            if provider["api_key"]:
                kwargs["api_key"] = provider["api_key"]
            if api_base or provider["base_url"]:
                kwargs["api_base"] = api_base or provider["base_url"]
            kwargs.update(provider["extra_params"])

            raw = await self.adapter.transport.completion(**kwargs)
            return True
        except BaseException as exc:
            error = exc
            raise
        finally:
            await self._record_probe(
                provider_id, model_name, model_str, family, raw, error, started, snapshot
            )

    async def _record_probe(
        self,
        provider_id: str,
        model_name: str,
        model_str: str,
        family: str,
        raw: Any,
        error: BaseException | None,
        started: float,
        snapshot: Any | None = None,
    ) -> None:
        """File the probe on the ledger — never blocks or fails validate."""
        try:
            from ..harness.litellm_adapter import LiteLLMAdapter
            from ..harness.scripted_model import ScriptedResponse
            from ..services.model_ledger import record_system_call, response_cost

            latency_ms = int((time.perf_counter() - started) * 1000)
            response = None
            cost_source = "unknown"
            if raw is not None:
                cost_receipt = None
                if snapshot is not None:
                    # Canonical path — normalized usage + full receipt from
                    # the frozen pre-call snapshot.
                    assessment = snapshot.assess(raw, family=family)
                    usage = assessment.usage
                    tin = int(usage.input_tokens or 0) if usage else 0
                    tout = int(usage.output_tokens or 0) if usage else 0
                    cached = usage.cache_read_tokens if usage else None
                    thinking = usage.reasoning_tokens if usage else None
                    cost = float(assessment.amount) if assessment.amount is not None else 0.0
                    cost_source = assessment.source
                    cost_receipt = snapshot.receipt(assessment)
                else:
                    if family == "responses":
                        tin, tout, cached, thinking = LiteLLMAdapter._response_usage(raw)
                    else:
                        usage = getattr(raw, "usage", None) or (
                            raw.get("usage") if isinstance(raw, dict) else None
                        )
                        get = lambda k: (  # noqa: E731
                            usage.get(k) if isinstance(usage, dict) else getattr(usage, k, None)
                        )
                        tin = get("prompt_tokens") or 0
                        tout = get("completion_tokens") or 0
                        cached = LiteLLMAdapter._cached_tokens(usage)
                        thinking = LiteLLMAdapter._reasoning_tokens(usage)
                    cost, cost_source = response_cost(raw, model_str)
                response = ScriptedResponse(
                    tokens_in=tin,
                    tokens_out=tout,
                    cached_tokens=cached,
                    thinking_tokens=thinking,
                    cost=cost,
                    cost_source=cost_source,
                    cost_receipt=cost_receipt,
                )
            await record_system_call(
                kind="probe",
                purpose="reasoning",
                provider_id=provider_id,
                model_name=model_name,
                model_str=model_str,
                response=response,
                error=error,
                latency_ms=latency_ms,
                detail={"operation": "validate", "cost_source": cost_source},
            )
        except Exception:
            logger.debug("probe ledger write failed", exc_info=True)

    async def discover_models(self, provider_id: str) -> list[dict[str, Any]]:
        """Legacy callers: live observed discovery, unknown on failure."""
        provider = await self.adapter._load_provider(provider_id)
        try:
            result = await discover_provider_models(provider)
            if isinstance(result, dict):
                return result["models"]
            return result
        except Exception:
            return []
