"""Media generation capabilities — W6 first slice: image generation.

Bounded provider dispatch: one request, fixed n=1, allowlisted options from the
frozen `media.image` binding, bytes (never URLs) validated by magic bytes and a
size cap, staged under the workspace `artifacts/` and tracked via the artifact
service. Every real provider attempt lands in the model_calls ledger through
`record_system_call` with rate-provenance cost assessment.
"""

import asyncio
import base64
import json
import logging
import time
import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx

from ...artifacts import service as artifact_service
from ...artifacts.service import ArtifactError
from ...secret_store import decrypt
from ...services.call_accounting import capture_call_rates, unknown_call_rates
from ...services.model_ledger import record_system_call

log = logging.getLogger(__name__)

_MAX_OUTPUT_BYTES = 16 * 1024 * 1024  # 16 MiB — honest cap, not a format promise
_TIMEOUT_S = 120.0

_MAGIC = (
    (b"\x89PNG\r\n\x1a\n", "png", "image/png"),
    (b"\xff\xd8\xff", "jpeg", "image/jpeg"),
    (b"RIFF", "webp", "image/webp"),  # RIFF....WEBP checked below
)


def _classify_image_bytes(data: bytes) -> tuple[str, str] | None:
    """Magic-byte check → (ext, mime). A claimed format string is not proof."""
    for prefix, ext, mime in _MAGIC:
        if data.startswith(prefix):
            if ext == "webp" and data[8:12] != b"WEBP":
                continue
            return ext, mime
    return None


async def _openrouter_image(
    provider: Any,
    model: str,
    prompt: str,
    options: dict,
    api_key: str | None,
) -> Any:
    """OpenRouter's dedicated POST /images API.

    Litellm's openrouter image transform dispatches to /chat/completions,
    which Images-API-only models (gpt-image-2.5-*, grok-imagine, …) refuse
    with 404. Same response contract as ImageResponse: data[].b64_json +
    usage with native prompt/completion/cost fields for the ledger.
    """
    base = (provider.base_url or "https://openrouter.ai/api/v1").rstrip("/")
    body: dict[str, Any] = {"model": model, "prompt": prompt, "n": 1}
    for opt in ("size", "quality"):
        val = options.get(opt)
        if val and val != "auto":
            body[opt] = val
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{base}/images",
            headers={"Authorization": f"Bearer {api_key or ''}"},
            json=body,
            timeout=_TIMEOUT_S,
        )
    if resp.status_code >= 400:
        try:
            detail = (resp.json().get("error") or {}).get("message") or resp.text[:200]
        except Exception:  # noqa: BLE001 — a non-JSON error body still reports status
            detail = resp.text[:200]
        raise RuntimeError(f"openrouter images {resp.status_code}: {detail}")
    d = resp.json()
    usage = d.get("usage") or {}
    return SimpleNamespace(
        data=[
            SimpleNamespace(
                b64_json=i.get("b64_json"),
                revised_prompt=i.get("revised_prompt"),
            )
            for i in d.get("data", [])
            if isinstance(i, dict)
        ],
        usage={
            **usage,
            "input_tokens": usage.get("prompt_tokens"),
            "output_tokens": usage.get("completion_tokens"),
        },
    )


async def media_image(args: dict[str, Any], workspace_path: str, **kwargs: Any) -> dict:
    """media_image(prompt) → one generated image as a tracked artifact.

    Provider/model/options come from the frozen media.image binding injected
    by the mediator — never from call args, so the model can't reroute the
    billed destination.
    """
    binding = kwargs.get("tool_binding")
    if binding is None or binding.provider is None or binding.binding is None:
        return {"error": "Image generation is not configured — see Settings → Tools."}
    provider = binding.provider
    model = binding.binding.model.strip()
    options = binding.options or {}

    prompt = str(args.get("prompt") or "").strip()
    if not prompt:
        return {"error": "prompt is required"}
    if len(prompt) > 4000:
        return {"error": "prompt exceeds the 4000-character limit"}

    # Credentials — same decryption path as the chat adapter (D39).
    api_key = decrypt(provider.encrypted_key) if provider.encrypted_key else None
    extra_params = json.loads(provider.extra_params) if provider.extra_params else {}
    if provider.encrypted_credentials:
        extra_params = {**json.loads(decrypt(provider.encrypted_credentials)), **extra_params}
    provider_config = {
        "api_key": api_key,
        "base_url": provider.base_url,
        "type": provider.type,
        "extra_params": extra_params,
    }
    model_str = f"{provider.type}/{model}"

    # Rate authority captured BEFORE dispatch — the assessment below pins this
    # snapshot even if the catalog changes while the request is in flight.
    # Missing authority degrades to an honest unknown, never a guess.
    try:
        accounting = await capture_call_rates(kwargs["db"], provider.id, model, provider_config)
    except Exception:  # noqa: BLE001 — unknown rates must not block dispatch
        accounting = unknown_call_rates(provider.id, model, provider_config)

    call_kwargs: dict[str, Any] = {
        "model": model_str,
        "prompt": prompt,
        "n": 1,
        "response_format": "b64_json",
        "api_key": api_key,
    }
    if provider.base_url:
        call_kwargs["api_base"] = provider.base_url
    for opt in ("size", "quality"):
        val = options.get(opt)
        if val and val != "auto":
            call_kwargs[opt] = val
    fmt = options.get("format")
    if fmt:
        call_kwargs["output_format"] = fmt

    start = time.monotonic()
    response = None
    error: BaseException | None = None
    try:
        if provider.type == "openrouter":
            response = await asyncio.wait_for(
                _openrouter_image(provider, model, prompt, options, api_key),
                timeout=_TIMEOUT_S,
            )
        else:
            import litellm

            response = await asyncio.wait_for(
                litellm.aimage_generation(**call_kwargs), timeout=_TIMEOUT_S
            )
    except BaseException as e:  # record the real attempt, then report honestly
        error = e
    latency_ms = int((time.monotonic() - start) * 1000)

    # Ledger: one row per actual provider attempt — success AND failure.
    def _g(obj: Any, key: str) -> Any:
        return obj.get(key) if isinstance(obj, dict) else getattr(obj, key, None)

    usage = _g(response, "usage") if response is not None else None
    assessed = None
    if response is not None:
        try:
            assessed = accounting.assess(response, family="chat")
        except Exception:  # noqa: BLE001 — odd receipt shape = unknown cost
            assessed = None
    await record_system_call(
        kind="image",
        purpose="media",
        provider_id=provider.id,
        model_name=model,
        model_str=model_str,
        run_id=kwargs.get("run_id"),
        session_id=kwargs.get("session_id"),
        agent_id=kwargs.get("agent_id"),
        sub_agent_id=kwargs.get("sub_agent_id"),
        latency_ms=latency_ms,
        response=(
            SimpleNamespace(
                tokens_in=(_g(usage, "input_tokens") or 0),
                tokens_out=(_g(usage, "output_tokens") or 0),
                cached_tokens=None,
                thinking_tokens=None,
                cost=(float(assessed.amount) if assessed and assessed.amount else 0.0),
                cost_source=(assessed.source if assessed else None),
                cost_receipt=(accounting.receipt(assessed) if assessed else None),
            )
            if response is not None
            else None
        ),
        error=error,
        detail={"modality": "image"},
    )

    if error is not None:
        if isinstance(error, (TimeoutError, asyncio.TimeoutError)):
            return {
                "error": "image generation timed out — the provider call may still have been billed"
            }
        return {"error": f"image generation failed: {type(error).__name__}"}
    if response is None:
        return {"error": "image generation returned no response"}

    # Extract bytes — b64_json only; a provider-returned URL is not fetched.
    try:
        item = response.data[0]
        b64 = getattr(item, "b64_json", None) or (
            item.get("b64_json") if isinstance(item, dict) else None
        )
        if not b64:
            return {"error": "provider returned no image bytes (URL responses are not fetched)"}
        data = base64.b64decode(b64)
    except (IndexError, KeyError, ValueError, TypeError) as e:
        return {"error": f"could not decode provider image response: {type(e).__name__}"}

    if len(data) > _MAX_OUTPUT_BYTES:
        return {
            "error": f"provider image exceeded the {_MAX_OUTPUT_BYTES // (1024 * 1024)} MiB limit"
        }
    classified = _classify_image_bytes(data)
    if classified is None:
        return {"error": "provider bytes are not a recognized image format"}
    ext, mime = classified

    # Stage under artifacts/ and track — artifact row + revision with exact
    # call correlation. Cleanup the staged file if tracking fails.
    media_dir = Path(workspace_path) / "artifacts" / "media"
    media_dir.mkdir(parents=True, exist_ok=True)
    rel_path = f"artifacts/media/image-{uuid.uuid4().hex[:12]}.{ext}"
    target = Path(workspace_path) / rel_path
    try:
        target.write_bytes(data)
        artifact, revision = await artifact_service.adopt(
            kwargs["db"],
            workspace_id=kwargs["agent_id"],
            workspace_path=workspace_path,
            rel_path=rel_path,
            created_by=kwargs.get("agent_id"),
            source_run_id=kwargs.get("run_id"),
            call_id=kwargs.get("call_id"),
            sub_agent_id=kwargs.get("sub_agent_id"),
            change_summary=f"generated image ({model})",
        )
    except (ArtifactError, OSError) as e:
        target.unlink(missing_ok=True)
        return {"error": f"could not stage generated image: {e}"}

    out: dict[str, Any] = {
        "artifact_id": artifact.id,
        "revision_id": revision.id,
        "path": rel_path,
        "mime": mime,
        "bytes": len(data),
        "model": model,
        "provider": provider.name,
    }
    revised = getattr(item, "revised_prompt", None) or (
        item.get("revised_prompt") if isinstance(item, dict) else None
    )
    if revised:
        out["revised_prompt"] = str(revised)[:2000]
    return out
