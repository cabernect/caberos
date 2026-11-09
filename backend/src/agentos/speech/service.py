"""Shared speech operation service (W10).

One seam behind the operator STT/TTS endpoints: frozen binding resolution,
bounds, cancellation, adapter dispatch, and one `model_calls` receipt per
actual provider attempt. These are operator actions — no agent capability
crosses this service (that path would need syscall mediation separately).

Adapters register per (provider_type, operation); an unregistered pair is an
honest "not supported yet", never a silent fallback to another provider.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..capabilities.bindings import BindingResolution, resolve_binding
from ..config import settings
from ..models.provider import Provider
from ..models.speech_audio import SpeechAudioCache
from ..secret_store import decrypt
from ..services.model_ledger import record_system_call
from .pricing import estimate_speech_cost
from .renderer import RENDERER_VERSION

log = logging.getLogger(__name__)

SPEECH_STT_KEY = "speech.stt"
SPEECH_TTS_KEY = "speech.tts"

# Plan ceilings — finalize against adapter evidence (W10 unit 1).
STT_MAX_AUDIO_BYTES = 15 * 1024 * 1024
TTS_MAX_SPEAKABLE_CHARS = 10_000
TTS_MAX_AUDIO_BYTES = 20 * 1024 * 1024

STT_ALLOWED_MIME = frozenset(
    {
        "audio/wav",
        "audio/x-wav",
        "audio/mpeg",
        "audio/mp3",
        "audio/mp4",
        "audio/m4a",
        "audio/x-m4a",
        "audio/webm",
        "audio/ogg",
        "audio/flac",
    }
)


class SpeechError(Exception):
    """Mapped to an HTTP status by the API layer — `detail` is operator-safe."""

    status_code = 422


class SpeechNotConfigured(SpeechError):
    status_code = 503


class SpeechUnavailable(SpeechError):
    """The bound provider type has no adapter for this operation yet."""

    status_code = 503


class SpeechBounds(SpeechError):
    status_code = 413


@dataclass(frozen=True)
class SpeechRequest:
    """Frozen dispatch contract — binding revision, model, options and the
    decrypted key are snapshotted at admission so mid-flight edits never
    redirect an in-flight attempt."""

    operation: str  # "stt" | "tts"
    request_id: str
    provider_id: str
    provider_type: str
    model: str
    options: dict[str, Any]
    api_key: str | None
    binding_revision: int
    # Resolved provider base URL (None = adapter default) — lets an
    # OpenAI-compatible provider's custom endpoint drive audio calls.
    base_url: str | None = None
    audio: bytes = b""
    mime: str = ""
    text: str = ""


@dataclass(frozen=True)
class TranscriptResult:
    text: str
    audio_seconds: float | None = None
    # Provider-reported usage/cost stays in the receipt, never in token cols.
    usage: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SynthesisResult:
    audio: bytes
    mime: str = "audio/mpeg"
    characters: int = 0
    usage: dict[str, Any] = field(default_factory=dict)


AdapterFn = Callable[[SpeechRequest], Awaitable[Any]]
_ADAPTERS: dict[tuple[str, str], AdapterFn] = {}

_MIME_EXT = {
    "audio/mpeg": "mp3",
    "audio/mp3": "mp3",
    "audio/wav": "wav",
    "audio/x-wav": "wav",
    "audio/ogg": "ogg",
    "audio/mp4": "m4a",
    "audio/m4a": "m4a",
    "audio/x-m4a": "m4a",
    "audio/webm": "webm",
    "audio/flac": "flac",
    "audio/pcm": "pcm",
}


def _cache_key(text: str, req: SpeechRequest) -> str:
    """Replay key — rendered text + renderer version + frozen binding."""
    payload = json.dumps(
        {
            "v": RENDERER_VERSION,
            "text": text,
            "provider": req.provider_id,
            "model": req.model,
            "options": req.options,
            "revision": req.binding_revision,
        },
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def _cache_dir() -> Path:
    root = settings.db_path.parent / "speech-audio"
    root.mkdir(parents=True, exist_ok=True)
    return root


async def _cache_lookup(db: AsyncSession, key: str) -> tuple[SpeechAudioCache, bytes] | None:
    row = (
        await db.scalars(select(SpeechAudioCache).where(SpeechAudioCache.cache_key == key))
    ).first()
    if row is None:
        return None
    try:
        audio = Path(row.audio_path).read_bytes()
    except OSError:
        return None
    if not audio:
        return None  # stale row — dispatch replaces it on success
    return row, audio


async def _cache_store(
    db: AsyncSession,
    *,
    key: str,
    req: SpeechRequest,
    result: SynthesisResult,
    message_id: str | None,
    session_id: str | None,
    agent_id: str | None,
) -> None:
    """Best-effort write-through — publication failure never eats a receipt."""
    ext = _MIME_EXT.get(result.mime, "bin")
    path = _cache_dir() / f"{key}.{ext}"
    tmp = path.with_name(f"{key}.{req.request_id}.tmp")
    try:
        tmp.write_bytes(result.audio)
        tmp.replace(path)
        async with db.begin_nested():
            await db.execute(delete(SpeechAudioCache).where(SpeechAudioCache.cache_key == key))
            db.add(
                SpeechAudioCache(
                    cache_key=key,
                    message_id=message_id,
                    session_id=session_id,
                    agent_id=agent_id,
                    provider_id=req.provider_id,
                    provider_type=req.provider_type,
                    model=req.model,
                    binding_revision=req.binding_revision,
                    mime=result.mime,
                    size_bytes=len(result.audio),
                    audio_path=str(path),
                    source_request_id=req.request_id,
                )
            )
    except Exception as exc:  # noqa: BLE001 — cache must not fail synthesis
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        log.warning("speech audio cache store failed: %s", type(exc).__name__)


def register_adapter(provider_type: str, operation: str, fn: AdapterFn) -> None:
    _ADAPTERS[(provider_type, operation)] = fn


def adapter_for(provider_type: str, operation: str) -> AdapterFn | None:
    return _ADAPTERS.get((provider_type, operation))


async def _resolve(
    db: AsyncSession, key: str, operation: str
) -> tuple[BindingResolution, Provider, AdapterFn]:
    resolution = await resolve_binding(db, key)
    if not resolution.ready or resolution.binding is None or resolution.provider is None:
        raise SpeechNotConfigured(
            resolution.reason or "Speech is not configured — set it up in Tools."
        )
    provider = resolution.provider
    adapter = adapter_for(provider.type, operation)
    if adapter is None:
        raise SpeechUnavailable(
            f"Provider type '{provider.type}' does not support {operation} yet."
        )
    return resolution, provider, adapter


def _key(provider: Provider) -> str | None:
    return decrypt(provider.encrypted_key) if provider.encrypted_key else None


async def _receipt(
    *,
    operation: str,
    req: SpeechRequest,
    session_id: str | None,
    agent_id: str | None,
    latency_ms: int,
    result: TranscriptResult | SynthesisResult | None = None,
    error: BaseException | None = None,
    units: dict[str, Any] | None = None,
) -> None:
    merged = {**(units or {}), **(result.usage if result else {})}
    detail = {
        "operation": operation,
        "request_id": req.request_id,
        "binding_revision": req.binding_revision,
        **merged,
    }
    # Estimated cost from the seeded rate table — provider-reported billed
    # characters (e.g. dg-char-count) beat our submitted length when present.
    est = None
    if error is None:
        est = estimate_speech_cost(
            req.provider_type,
            req.model,
            operation,
            audio_seconds=merged.get("audio_seconds"),
            characters=merged.get("characters_reported") or merged.get("text_chars"),
        )
    if est is not None:
        detail["price_basis"] = est[1]
    await record_system_call(
        kind="speech",
        purpose="transcription" if operation == "stt" else "synthesis",
        provider_id=req.provider_id,
        model_name=req.model,
        session_id=session_id,
        agent_id=agent_id,
        latency_ms=latency_ms,
        detail=detail,
        error=error,
        explicit_cost=est[0] if est else None,
        cost_source="estimated" if est else None,
    )


async def transcribe(
    *,
    db: AsyncSession,
    audio: bytes,
    mime: str,
    session_id: str | None = None,
    agent_id: str | None = None,
    cancel: asyncio.Event | None = None,
) -> tuple[TranscriptResult, str]:
    """One dictation transcription attempt — operator action, not a tool."""
    if len(audio) > STT_MAX_AUDIO_BYTES:
        raise SpeechBounds("Recording exceeds the 15 MiB limit.")
    mime_base = mime.split(";")[0].strip().lower()
    if mime_base not in STT_ALLOWED_MIME:
        raise SpeechError(f"Unsupported audio format '{mime or 'unknown'}'.")
    if cancel is not None and cancel.is_set():
        # Cancellation before dispatch makes zero provider calls and writes
        # no receipt — the operator was never billed.
        raise asyncio.CancelledError

    resolution, provider, adapter = await _resolve(db, SPEECH_STT_KEY, "stt")
    binding = resolution.binding
    assert binding is not None and provider is not None
    req = SpeechRequest(
        operation="stt",
        request_id=uuid.uuid4().hex,
        provider_id=provider.id,
        provider_type=provider.type,
        model=binding.model,
        options=dict(resolution.options),
        api_key=_key(provider),
        binding_revision=binding.revision,
        base_url=provider.base_url,
        audio=audio,
        mime=mime_base,
    )
    started = time.monotonic()
    units = {"audio_bytes": len(audio)}
    try:
        result: TranscriptResult = await adapter(req)
    except Exception as exc:
        await _receipt(
            operation="stt",
            req=req,
            session_id=session_id,
            agent_id=agent_id,
            latency_ms=int((time.monotonic() - started) * 1000),
            error=exc,
            units=units,
        )
        raise
    units["audio_seconds"] = result.audio_seconds
    units["transcript_chars"] = len(result.text)
    await _receipt(
        operation="stt",
        req=req,
        session_id=session_id,
        agent_id=agent_id,
        latency_ms=int((time.monotonic() - started) * 1000),
        result=result,
        units=units,
    )
    return result, req.request_id


async def synthesize(
    *,
    db: AsyncSession,
    text: str,
    session_id: str | None = None,
    agent_id: str | None = None,
    message_id: str | None = None,
    cancel: asyncio.Event | None = None,
) -> tuple[SynthesisResult, str]:
    """One read-aloud synthesis attempt on already-rendered speakable text."""
    if len(text) > TTS_MAX_SPEAKABLE_CHARS:
        raise SpeechBounds("Message exceeds the 10,000 character speech limit.")
    if not text.strip():
        raise SpeechError("Nothing speakable to synthesize.")
    if cancel is not None and cancel.is_set():
        raise asyncio.CancelledError

    resolution, provider, adapter = await _resolve(db, SPEECH_TTS_KEY, "tts")
    binding = resolution.binding
    assert binding is not None and provider is not None
    req = SpeechRequest(
        operation="tts",
        request_id=uuid.uuid4().hex,
        provider_id=provider.id,
        provider_type=provider.type,
        model=binding.model,
        options=dict(resolution.options),
        api_key=_key(provider),
        binding_revision=binding.revision,
        base_url=provider.base_url,
        text=text,
    )

    # Replay check — validated audio keyed on the rendered text + frozen
    # binding replays without a provider call (and without billing).
    key = _cache_key(text, req)
    hit = await _cache_lookup(db, key)
    if hit is not None:
        row, audio = hit
        await record_system_call(
            kind="speech",
            purpose="synthesis_replay",
            provider_id=req.provider_id,
            model_name=req.model,
            session_id=session_id,
            agent_id=agent_id,
            detail={
                "reused": True,
                "cache_key": key,
                "request_id": req.request_id,
                "source_request_id": row.source_request_id,
                "text_chars": len(text),
                "audio_bytes": len(audio),
                **({"message_id": message_id} if message_id else {}),
            },
        )
        return (
            SynthesisResult(
                audio=audio,
                mime=row.mime,
                characters=len(text),
                usage={"reused": True},
            ),
            req.request_id,
        )

    started = time.monotonic()
    units: dict[str, Any] = {"text_chars": len(text)}
    if message_id:
        units["message_id"] = message_id
    try:
        result: SynthesisResult = await adapter(req)
    except Exception as exc:
        await _receipt(
            operation="tts",
            req=req,
            session_id=session_id,
            agent_id=agent_id,
            latency_ms=int((time.monotonic() - started) * 1000),
            error=exc,
            units=units,
        )
        raise
    if len(result.audio) > TTS_MAX_AUDIO_BYTES:
        err = SpeechBounds("Provider returned audio over the 20 MiB limit.")
        await _receipt(
            operation="tts",
            req=req,
            session_id=session_id,
            agent_id=agent_id,
            latency_ms=int((time.monotonic() - started) * 1000),
            error=err,
            units=units,
        )
        raise err
    units["audio_bytes"] = len(result.audio)
    units["audio_mime"] = result.mime
    await _receipt(
        operation="tts",
        req=req,
        session_id=session_id,
        agent_id=agent_id,
        latency_ms=int((time.monotonic() - started) * 1000),
        result=result,
        units=units,
    )
    await _cache_store(
        db,
        key=key,
        req=req,
        result=result,
        message_id=message_id,
        session_id=session_id,
        agent_id=agent_id,
    )
    return result, req.request_id
