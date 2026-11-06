"""Speech provider adapters — one small function per (type, operation).

Contract verified against Deepgram's prerecorded Listen API docs (W10):
POST https://api.deepgram.com/v1/listen?model=…&language=… with
`Authorization: Token <key>` and raw audio bytes as the body; the response
carries `results.channels[].alternatives[].transcript` and
`metadata.duration` seconds.

Same request discipline as providers/search.py: fixed destination, no
redirects, no ambient proxy, streamed bounded response, and errors that
never echo provider bodies (they can contain credentials or request
content).
"""

from __future__ import annotations

import asyncio
import json
import time

import httpx

from ..providers.search import SSL_CERT_PATH
from .service import (
    SpeechError,
    SpeechRequest,
    TranscriptResult,
    register_adapter,
)

_DEEPGRAM_LISTEN = "https://api.deepgram.com/v1/listen"
_RESPONSE_LIMIT = 5 * 1024 * 1024  # JSON envelope — generous vs transcript size
_TIMEOUT_S = 60.0


class SpeechProviderError(SpeechError):
    """Provider call failed; message is operator-safe (status, not body)."""

    status_code = 502


async def _deepgram_stt(req: SpeechRequest) -> TranscriptResult:
    """Deepgram prerecorded transcription — one attempt, no fallback."""
    if not req.api_key:
        raise SpeechError("Deepgram provider has no API key.")
    params: dict[str, str] = {"model": req.model}
    language = (req.options.get("language") or "").strip() if req.options.get("language") else ""
    if language:
        params["language"] = language
    else:
        params["detect_language"] = "true"
    params["smart_format"] = "true"
    headers = {
        "Authorization": f"Token {req.api_key}",
        "Content-Type": req.mime or "application/octet-stream",
    }
    started = time.monotonic()
    try:
        async with asyncio.timeout(_TIMEOUT_S):
            async with httpx.AsyncClient(
                verify=SSL_CERT_PATH,
                timeout=_TIMEOUT_S,
                follow_redirects=False,
                trust_env=False,
            ) as client:
                response = await client.post(
                    _DEEPGRAM_LISTEN, params=params, headers=headers, content=req.audio
                )
                if response.status_code != 200:
                    raise SpeechProviderError(
                        f"Deepgram transcription failed (HTTP {response.status_code})."
                    )
                body = bytearray()
                async for chunk in response.aiter_bytes(chunk_size=64 * 1024):
                    body.extend(chunk)
                    if len(body) > _RESPONSE_LIMIT:
                        raise ValueError("oversized response")
    except (TimeoutError, httpx.TimeoutException) as exc:
        raise TimeoutError("Deepgram transcription timed out; it may have been billed.") from exc
    except (httpx.HTTPError, OSError) as exc:
        raise SpeechProviderError("Deepgram transcription request failed.") from exc

    try:
        payload = json.loads(body)
        alternatives = payload["results"]["channels"][0]["alternatives"]
        transcript = " ".join(
            alt["transcript"] for alt in alternatives if alt.get("transcript")
        ).strip()
    except (KeyError, IndexError, TypeError, json.JSONDecodeError, AttributeError) as exc:
        raise SpeechProviderError("Deepgram returned an unreadable response.") from exc
    duration = payload.get("metadata", {}).get("duration")
    return TranscriptResult(
        text=transcript,
        audio_seconds=duration if isinstance(duration, (int, float)) else None,
        usage={
            "latency_ms": int((time.monotonic() - started) * 1000),
            "dg_request_id": payload.get("metadata", {}).get("request_id"),
        },
    )


register_adapter("deepgram", "stt", _deepgram_stt)

# Registered as provider contracts are verified (W10 units 3/5/6):
# elevenlabs tts+stt(scribe), deepgram tts(aura), gradium tts.
