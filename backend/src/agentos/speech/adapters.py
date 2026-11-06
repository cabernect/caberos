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
import base64
import json
import time

import httpx

from ..providers.search import SSL_CERT_PATH
from .service import (
    SpeechError,
    SpeechRequest,
    SynthesisResult,
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


# --- OpenAI-compatible audio (/v1/audio/*) ---------------------------------
#
# Verified contract (OpenAI audio API): STT is multipart POST
# /v1/audio/transcriptions with file + model (+ language, response_format);
# TTS is JSON POST /v1/audio/speech {model, voice, input, response_format}
# returning audio bytes. Bearer auth. Groq exposes the same shapes
# (whisper STT, playai TTS) on its openai-compatible base.

_OPENAI_BASES: dict[str, str] = {
    "openai": "https://api.openai.com",
    "groq": "https://api.groq.com/openai",
}


def _audio_base(req: SpeechRequest) -> str:
    return (req.base_url or _OPENAI_BASES.get(req.provider_type) or "").rstrip("/")


async def _openai_stt(req: SpeechRequest) -> TranscriptResult:
    if not req.api_key:
        raise SpeechError(f"{req.provider_type} provider has no API key.")
    base = _audio_base(req)
    if not base:
        raise SpeechError(f"No audio endpoint known for provider type '{req.provider_type}'.")
    data: dict[str, str] = {"model": req.model, "response_format": "json"}
    language = (req.options.get("language") or "").strip() if req.options.get("language") else ""
    if language:
        data["language"] = language
    headers = {"Authorization": f"Bearer {req.api_key}"}
    try:
        async with asyncio.timeout(_TIMEOUT_S):
            async with httpx.AsyncClient(
                verify=SSL_CERT_PATH,
                timeout=_TIMEOUT_S,
                follow_redirects=False,
                trust_env=False,
            ) as client:
                response = await client.post(
                    f"{base}/v1/audio/transcriptions",
                    headers=headers,
                    data=data,
                    files={"file": ("audio", req.audio, req.mime)},
                )
                if response.status_code != 200:
                    raise SpeechProviderError(
                        f"Transcription failed (HTTP {response.status_code})."
                    )
                body = response.content
                if len(body) > _RESPONSE_LIMIT:
                    raise ValueError("oversized response")
    except (TimeoutError, httpx.TimeoutException) as exc:
        raise TimeoutError("Transcription timed out; it may have been billed.") from exc
    except (httpx.HTTPError, OSError) as exc:
        raise SpeechProviderError("Transcription request failed.") from exc
    try:
        payload = json.loads(body)
        transcript = str(payload["text"]).strip()
    except (KeyError, TypeError, json.JSONDecodeError) as exc:
        raise SpeechProviderError("Provider returned an unreadable transcription.") from exc
    return TranscriptResult(text=transcript)


async def _openai_tts(req: SpeechRequest) -> SynthesisResult:
    if not req.api_key:
        raise SpeechError(f"{req.provider_type} provider has no API key.")
    base = _audio_base(req)
    if not base:
        raise SpeechError(f"No audio endpoint known for provider type '{req.provider_type}'.")
    voice = (req.options.get("voice") or "").strip() if req.options.get("voice") else ""
    payload = {
        "model": req.model,
        "voice": voice or "alloy",
        "input": req.text,
        "response_format": "mp3",
    }
    headers = {"Authorization": f"Bearer {req.api_key}", "Content-Type": "application/json"}
    try:
        async with asyncio.timeout(_TIMEOUT_S):
            async with httpx.AsyncClient(
                verify=SSL_CERT_PATH,
                timeout=_TIMEOUT_S,
                follow_redirects=False,
                trust_env=False,
            ) as client:
                async with client.stream(
                    "POST", f"{base}/v1/audio/speech", headers=headers, json=payload
                ) as response:
                    if response.status_code != 200:
                        raise SpeechProviderError(
                            f"Speech synthesis failed (HTTP {response.status_code})."
                        )
                    audio = bytearray()
                    async for chunk in response.aiter_bytes(chunk_size=64 * 1024):
                        audio.extend(chunk)
                        if len(audio) > 20 * 1024 * 1024:
                            raise ValueError("oversized response")
    except (TimeoutError, httpx.TimeoutException) as exc:
        raise TimeoutError("Speech synthesis timed out; it may have been billed.") from exc
    except (httpx.HTTPError, OSError) as exc:
        raise SpeechProviderError("Speech synthesis request failed.") from exc
    return SynthesisResult(audio=bytes(audio), mime="audio/mpeg", characters=len(req.text))


register_adapter("openai", "stt", _openai_stt)
register_adapter("openai", "tts", _openai_tts)
register_adapter("groq", "stt", _openai_stt)
register_adapter("groq", "tts", _openai_tts)


# --- OpenRouter chat-completions audio --------------------------------------
#
# Verified contract (OpenRouter multimodal audio guide): audio travels through
# /api/v1/chat/completions, not /v1/audio/*.
#   STT: input_audio content part (base64 data + format string); the model's
#   reply text is the transcript.
#   TTS: modalities ["text","audio"] + audio {voice, format}; the reply
#   message's audio.data is base64 audio bytes.

_OPENROUTER_BASE = "https://openrouter.ai/api/v1"
_MIME_TO_FORMAT = {
    "wav": "wav",
    "x-wav": "wav",
    "mpeg": "mp3",
    "mp3": "mp3",
    "ogg": "ogg",
    "flac": "flac",
    "m4a": "m4a",
    "mp4": "m4a",
    "webm": "webm",
}


def _openrouter_base(req: SpeechRequest) -> str:
    return (req.base_url or _OPENROUTER_BASE).rstrip("/")


async def _chat_audio_request(req: SpeechRequest, payload: dict) -> dict:
    base = _openrouter_base(req)
    headers = {
        "Authorization": f"Bearer {req.api_key}",
        "Content-Type": "application/json",
    }
    try:
        async with asyncio.timeout(_TIMEOUT_S):
            async with httpx.AsyncClient(
                verify=SSL_CERT_PATH,
                timeout=_TIMEOUT_S,
                follow_redirects=False,
                trust_env=False,
            ) as client:
                response = await client.post(
                    f"{base}/chat/completions", headers=headers, json=payload
                )
                if response.status_code != 200:
                    raise SpeechProviderError(
                        f"Audio request failed (HTTP {response.status_code})."
                    )
                body = response.content
                if len(body) > _RESPONSE_LIMIT * 4:  # base64 inflates ~33%
                    raise ValueError("oversized response")
        return json.loads(body)
    except (TimeoutError, httpx.TimeoutException) as exc:
        raise TimeoutError("Audio request timed out; it may have been billed.") from exc
    except (httpx.HTTPError, OSError, json.JSONDecodeError) as exc:
        raise SpeechProviderError("Audio request failed.") from exc


async def _openrouter_stt(req: SpeechRequest) -> TranscriptResult:
    if not req.api_key:
        raise SpeechError("OpenRouter provider has no API key.")
    fmt = _MIME_TO_FORMAT.get(req.mime.split("/")[-1], "wav")
    language = (req.options.get("language") or "").strip() if req.options.get("language") else ""
    hint = f" The spoken language is {language}." if language else ""
    payload = {
        "model": req.model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": (
                            "Transcribe this audio verbatim. Output only the "
                            f"transcript text, nothing else.{hint}"
                        ),
                    },
                    {
                        "type": "input_audio",
                        "input_audio": {
                            "data": base64.b64encode(req.audio).decode(),
                            "format": fmt,
                        },
                    },
                ],
            }
        ],
    }
    out = await _chat_audio_request(req, payload)
    try:
        content = out["choices"][0]["message"]["content"]
        transcript = (
            content
            if isinstance(content, str)
            else " ".join(p.get("text", "") for p in content if isinstance(p, dict))
        ).strip()
    except (KeyError, IndexError, TypeError) as exc:
        raise SpeechProviderError("Provider returned an unreadable transcription.") from exc
    return TranscriptResult(text=transcript)


async def _openrouter_tts(req: SpeechRequest) -> SynthesisResult:
    if not req.api_key:
        raise SpeechError("OpenRouter provider has no API key.")
    voice = (req.options.get("voice") or "").strip() if req.options.get("voice") else ""
    payload = {
        "model": req.model,
        "modalities": ["text", "audio"],
        "audio": {"voice": voice or "alloy", "format": "mp3"},
        "messages": [
            {
                "role": "user",
                "content": f"Read the following text aloud exactly as written:\n\n{req.text}",
            }
        ],
    }
    out = await _chat_audio_request(req, payload)
    try:
        audio_b64 = out["choices"][0]["message"]["audio"]["data"]
        audio = base64.b64decode(audio_b64)
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        raise SpeechProviderError("Provider returned no audio output.") from exc
    return SynthesisResult(audio=audio, mime="audio/mpeg", characters=len(req.text))


register_adapter("openrouter", "stt", _openrouter_stt)
register_adapter("openrouter", "tts", _openrouter_tts)

# Registered as provider contracts are verified (W10 units 3/5/6):
# elevenlabs tts+stt(scribe), deepgram tts(aura), gradium tts.
