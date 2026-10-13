"""Embedding service — LiteLLM `aembedding` seam over a configured
EmbeddingResource (provider credentials + model).

Egress rule: a provider whose endpoint is local (ollama, lmstudio, or a
loopback base_url) embeds freely; anything remote requires the resource's
``egress_allowed`` flag set by the operator at configuration time.
"""

from __future__ import annotations

import asyncio
import json
import time
from urllib.parse import urlparse

import litellm
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.knowledge_index import EmbeddingResource
from ..models.model_call import ModelCall
from ..models.provider import Provider
from ..secret_store import decrypt

_LOCAL_PROVIDER_TYPES = {"ollama", "lmstudio", "vllm", "llama.cpp", "local"}
_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "0.0.0.0"}
_EMBED_TIMEOUT_SECONDS = 60
_BATCH_SIZE = 64


class EmbeddingUnavailable(RuntimeError):
    """Raised when the embedding call cannot complete — callers mark pending."""


def provider_is_local(provider: Provider) -> bool:
    """True when the embedding endpoint stays on this machine."""
    if provider.type.lower() in _LOCAL_PROVIDER_TYPES:
        return True
    base = (provider.base_url or "").strip()
    if not base:
        return False
    host = urlparse(base if "://" in base else f"http://{base}").hostname or ""
    return host.lower() in _LOCAL_HOSTS or host.endswith(".local")


def egress_permitted(provider: Provider, resource: EmbeddingResource) -> bool:
    """Vault text may leave the machine only by explicit operator opt-in."""
    return provider_is_local(provider) or resource.egress_allowed


async def _provider_for(db: AsyncSession, resource: EmbeddingResource) -> Provider:
    provider = await db.scalar(select(Provider).where(Provider.id == resource.provider_id))
    if provider is None:
        raise EmbeddingUnavailable("embedding provider no longer exists")
    return provider


def _provider_config(provider: Provider) -> dict:
    """Plain config dict for rate capture — matches the adapter shape."""
    return {
        "api_key": decrypt(provider.encrypted_key) if provider.encrypted_key else "",
        "base_url": provider.base_url,
        "org_id": provider.org_id,
        "extra_params": json.loads(provider.extra_params or "{}"),
        "type": provider.type,
    }


def _litellm_kwargs(provider: Provider, resource: EmbeddingResource) -> dict:
    api_key = decrypt(provider.encrypted_key) if provider.encrypted_key else None
    extra = json.loads(provider.extra_params or "{}")
    kwargs = {
        "model": f"{provider.type}/{resource.model_name}",
        "api_key": api_key,
        "api_base": provider.base_url or None,
        **extra.get("embedding", {}),
    }
    return {k: v for k, v in kwargs.items() if v is not None}


def _record_call(
    db: AsyncSession,
    resource: EmbeddingResource,
    provider: Provider,
    *,
    operation: str,
    generation_id: str | None,
    run_id: str | None,
    agent_id: str | None,
    chunk_count: int,
    tokens_in: int,
    cost: float,
    latency_ms: int,
    status: str,
    error: str | None,
    model_str: str,
    cost_receipt: dict | None = None,
    assessment_source: str = "unknown",
) -> None:
    """Ledger entry per provider call — best-effort accounting: a
    bookkeeping failure must never break embedding work."""
    try:
        db.add(
            ModelCall(
                kind="embedding",
                purpose="embedding",
                run_id=run_id,
                agent_id=agent_id,
                provider_id=provider.id,
                model_name=resource.model_name,
                model_str=model_str,
                streamed=False,
                tokens_in=tokens_in,
                tokens_out=0,
                cost=cost,
                latency_ms=latency_ms,
                status=status,
                error=(error[:2000] if error else None),
                detail={
                    "resource_id": resource.id,
                    "generation_id": generation_id,
                    "operation": operation,
                    "chunk_count": chunk_count,
                    "cost_source": assessment_source,
                    **(cost_receipt or {}),
                },
            )
        )
    except Exception:
        import logging

        logging.getLogger("agentos.knowledge.embeddings").debug("Could not record embedding call")


async def embed_texts(
    db: AsyncSession,
    resource: EmbeddingResource,
    texts: list[str],
    *,
    operation: str = "index",
    generation_id: str | None = None,
    run_id: str | None = None,
    agent_id: str | None = None,
) -> list[list[float]]:
    """Embed a batch of texts; raises EmbeddingUnavailable on any failure.
    Every provider call is ledgered in ``model_calls`` (kind="embedding";
    tokens, cost, latency) — the spend record survives the caller's
    outcome."""
    if not texts:
        return []
    provider = await _provider_for(db, resource)
    if not egress_permitted(provider, resource):
        raise EmbeddingUnavailable("remote embedding egress is not enabled for this resource")
    kwargs = _litellm_kwargs(provider, resource)
    provider_config = _provider_config(provider)
    from ..services.call_accounting import capture_call_rates

    vectors: list[list[float]] = []
    for start in range(0, len(texts), _BATCH_SIZE):
        batch = texts[start : start + _BATCH_SIZE]
        started = time.monotonic()
        # Frozen pre-call rate authority per batch — never litellm's
        # completion_cost.
        snapshot = None
        try:
            snapshot = await capture_call_rates(
                db, provider.id, resource.model_name, provider_config
            )
        except Exception:
            try:
                from ..services.call_accounting import unknown_call_rates

                snapshot = unknown_call_rates(provider.id, resource.model_name, provider_config)
            except Exception:
                pass
        try:
            response = await asyncio.wait_for(
                litellm.aembedding(input=batch, **kwargs),
                timeout=_EMBED_TIMEOUT_SECONDS,
            )
        except Exception as error:  # provider/network/timeout — caller degrades
            error_receipt = None
            if snapshot is not None:
                try:
                    error_receipt = snapshot.receipt(snapshot.assess(None, family="embedding"))
                except Exception:
                    error_receipt = None
            _record_call(
                db,
                resource,
                provider,
                operation=operation,
                generation_id=generation_id,
                run_id=run_id,
                agent_id=agent_id,
                chunk_count=len(batch),
                tokens_in=0,
                cost=0.0,
                latency_ms=int((time.monotonic() - started) * 1000),
                status="error",
                error=str(error),
                model_str=kwargs["model"],
                cost_receipt=error_receipt,
            )
            raise EmbeddingUnavailable(str(error)) from error
        # Canonical legacy fields from assessment.usage — the normalizer's
        # native tokens only (embedding family total_tokens fallback),
        # never raw SDK attribute reads.
        cost = 0.0
        cost_receipt = None
        assessment_source = "unknown"
        tokens_in = 0
        if snapshot is not None:
            try:
                assessment = snapshot.assess(response, family="embedding")
                usage = assessment.usage
                tokens_in = int(usage.input_tokens or 0) if usage else 0
                cost = float(assessment.amount) if assessment.amount is not None else 0.0
                cost_receipt = snapshot.receipt(assessment)
                assessment_source = assessment.source
            except Exception:
                cost_receipt = None
        _record_call(
            db,
            resource,
            provider,
            operation=operation,
            generation_id=generation_id,
            run_id=run_id,
            agent_id=agent_id,
            chunk_count=len(batch),
            tokens_in=tokens_in,
            cost=cost,
            latency_ms=int((time.monotonic() - started) * 1000),
            status="ok",
            error=None,
            model_str=kwargs["model"],
            cost_receipt=cost_receipt,
            assessment_source=assessment_source,
        )
        vectors.extend([item["embedding"] for item in response.data])
    return vectors


async def probe_dimensions(db: AsyncSession, resource: EmbeddingResource) -> int:
    """One bounded embed call to learn/validate the model's dimensions."""
    vectors = await embed_texts(
        db, resource, ["knowledge vault dimension probe"], operation="validate"
    )
    if not vectors or not vectors[0]:
        raise EmbeddingUnavailable("embedding probe returned no vector")
    if resource.dimensions and len(vectors[0]) != resource.dimensions:
        raise EmbeddingUnavailable(
            f"dimension mismatch: expected {resource.dimensions}, got {len(vectors[0])}"
        )
    return len(vectors[0])
