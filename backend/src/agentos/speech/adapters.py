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
import re
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


def _audio_url(base: str, path: str) -> str:
    """Provider base_urls may already end in /v1 (OpenAI-compatible presets)
    or carry no version (api.openai.com) — join without doubling."""
    b = base.rstrip("/")
    return f"{b}/{path}" if re.search(r"/v\d+(?:beta)?$", b) else f"{b}/v1/{path}"


async def _audio_transcriptions(req: SpeechRequest, base: str) -> TranscriptResult:
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
                    _audio_url(base, "audio/transcriptions"),
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


async def _audio_speech(
    req: SpeechRequest, base: str, *, default_voice: str | None = "alloy"
) -> SynthesisResult:
    voice = (req.options.get("voice") or "").strip() if req.options.get("voice") else ""
    payload: dict[str, str] = {
        "model": req.model,
        "input": req.text,
        "response_format": "mp3",
    }
    effective_voice = voice or default_voice
    if effective_voice:
        payload["voice"] = effective_voice
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
                    "POST", _audio_url(base, "audio/speech"), headers=headers, json=payload
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


def _audio_base_or_raise(req: SpeechRequest) -> str:
    if not req.api_key:
        raise SpeechError(f"{req.provider_type} provider has no API key.")
    base = _audio_base(req)
    if not base:
        raise SpeechError(f"No audio endpoint known for provider type '{req.provider_type}'.")
    return base


async def _openai_stt(req: SpeechRequest) -> TranscriptResult:
    return await _audio_transcriptions(req, _audio_base_or_raise(req))


async def _openai_tts(req: SpeechRequest) -> SynthesisResult:
    return await _audio_speech(req, _audio_base_or_raise(req))


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


# OpenRouter exposes two audio surfaces: dedicated speech models route to
# /audio/speech and /audio/transcriptions (same OpenAI shapes — heygen,
# voxtral-tts, whisper), while multimodal chat models use chat-completions
# input_audio / modalities. Slug heuristics pick the surface the model
# actually serves; the wrong surface answers with a pre-billing 4xx.
_OR_DEDICATED_STT = ("whisper", "stt", "transcri")
_OR_DEDICATED_TTS = ("tts", "voice", "speak")


async def _openrouter_stt(req: SpeechRequest) -> TranscriptResult:
    if not req.api_key:
        raise SpeechError("OpenRouter provider has no API key.")
    if any(h in req.model.lower() for h in _OR_DEDICATED_STT):
        return await _audio_transcriptions(req, _openrouter_base(req))
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
    if any(h in req.model.lower() for h in _OR_DEDICATED_TTS):
        # Dedicated TTS models (heygen-voice, voxtral-tts, gpt-*-tts) serve
        # the OpenAI /audio/speech shape; voice passes through only when set.
        return await _audio_speech(req, _openrouter_base(req), default_voice=None)
    voice = (req.options.get("voice") or "").strip() if req.options.get("voice") else ""
    # No invented default — a voice ID is provider/model-specific, so an
    # unset option means "the model's own default voice", not an OpenAI name.
    audio_cfg: dict[str, str] = {"format": "mp3"}
    if voice:
        audio_cfg["voice"] = voice
    payload = {
        "model": req.model,
        "modalities": ["text", "audio"],
        "audio": audio_cfg,
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


# --- ElevenLabs --------------------------------------------------------------
#
# Verified contract (ElevenLabs API reference):
#   STT: multipart POST /v1/speech-to-text, fields file + model_id
#   (scribe_v1/scribe_v2, optional language_code) → {"text": ...}.
#   TTS: JSON POST /v1/text-to-speech/{voice_id} {text, model_id}
#   → raw audio bytes. Auth is the xi-api-key header. The voice option is
#   the path voice_id — ElevenLabs voices have no usable default, so a
#   missing voice is an honest configuration error, never a guess.

_ELEVENLABS_BASE = "https://api.elevenlabs.io"


def _elevenlabs_base(req: SpeechRequest) -> str:
    return (req.base_url or _ELEVENLABS_BASE).rstrip("/")


async def _elevenlabs_stt(req: SpeechRequest) -> TranscriptResult:
    if not req.api_key:
        raise SpeechError("ElevenLabs provider has no API key.")
    base = _elevenlabs_base(req)
    headers = {"xi-api-key": req.api_key}
    data: dict[str, str] = {"model_id": req.model}
    language = (req.options.get("language") or "").strip() if req.options.get("language") else ""
    if language:
        data["language_code"] = language
    ext = _MIME_TO_FORMAT.get(req.mime.split("/")[-1], "bin")
    files = {"file": (f"audio.{ext}", req.audio, req.mime or "application/octet-stream")}
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
                    f"{base}/v1/speech-to-text",
                    headers=headers,
                    data=data,
                    files=files,
                )
                if response.status_code != 200:
                    raise SpeechProviderError(
                        f"ElevenLabs transcription failed (HTTP {response.status_code})."
                    )
                body = response.content
                if len(body) > _RESPONSE_LIMIT:
                    raise ValueError("oversized response")
        payload = json.loads(body)
        transcript = str(payload.get("text") or "").strip()
    except (TimeoutError, httpx.TimeoutException) as exc:
        raise TimeoutError("ElevenLabs transcription timed out; it may have been billed.") from exc
    except (httpx.HTTPError, OSError, json.JSONDecodeError) as exc:
        raise SpeechProviderError("ElevenLabs transcription request failed.") from exc
    return TranscriptResult(
        text=transcript,
        usage={"latency_ms": int((time.monotonic() - started) * 1000)},
    )


async def _elevenlabs_tts(req: SpeechRequest) -> SynthesisResult:
    if not req.api_key:
        raise SpeechError("ElevenLabs provider has no API key.")
    voice = (req.options.get("voice") or "").strip() if req.options.get("voice") else ""
    if not voice:
        raise SpeechError(
            "ElevenLabs synthesis needs a voice ID — set Voice on the "
            "Text to Speech binding (e.g. from your ElevenLabs voice library)."
        )
    base = _elevenlabs_base(req)
    headers = {
        "xi-api-key": req.api_key,
        "Content-Type": "application/json",
    }
    payload = {"text": req.text, "model_id": req.model}
    try:
        async with asyncio.timeout(_TIMEOUT_S):
            async with httpx.AsyncClient(
                verify=SSL_CERT_PATH,
                timeout=_TIMEOUT_S,
                follow_redirects=False,
                trust_env=False,
            ) as client:
                response = await client.post(
                    f"{base}/v1/text-to-speech/{voice}",
                    headers=headers,
                    json=payload,
                )
                if response.status_code != 200:
                    raise SpeechProviderError(
                        f"ElevenLabs synthesis failed (HTTP {response.status_code})."
                    )
                audio = bytearray()
                async for chunk in response.aiter_bytes(chunk_size=64 * 1024):
                    audio.extend(chunk)
                    if len(audio) > _RESPONSE_LIMIT:
                        raise ValueError("oversized response")
    except (TimeoutError, httpx.TimeoutException) as exc:
        raise TimeoutError("ElevenLabs synthesis timed out; it may have been billed.") from exc
    except (httpx.HTTPError, OSError) as exc:
        raise SpeechProviderError("ElevenLabs synthesis request failed.") from exc
    return SynthesisResult(audio=bytes(audio), mime="audio/mpeg", characters=len(req.text))


register_adapter("elevenlabs", "stt", _elevenlabs_stt)
register_adapter("elevenlabs", "tts", _elevenlabs_tts)


# --- Deepgram Aura TTS -------------------------------------------------------
#
# Verified contract: POST /v1/speak?model=aura-* JSON {"text": ...} → audio
# bytes (encoding=mp3). Token auth like /v1/listen. The dg-char-count
# response header reports billed characters.

_DEEPGRAM_SPEAK = "https://api.deepgram.com/v1/speak"


async def _deepgram_tts(req: SpeechRequest) -> SynthesisResult:
    if not req.api_key:
        raise SpeechError("Deepgram provider has no API key.")
    params = {"model": req.model, "encoding": "mp3"}
    headers = {
        "Authorization": f"Token {req.api_key}",
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
                    _DEEPGRAM_SPEAK,
                    params=params,
                    headers=headers,
                    json={"text": req.text},
                )
                if response.status_code != 200:
                    raise SpeechProviderError(
                        f"Deepgram synthesis failed (HTTP {response.status_code})."
                    )
                char_count = response.headers.get("dg-char-count")
                audio = bytearray()
                async for chunk in response.aiter_bytes(chunk_size=64 * 1024):
                    audio.extend(chunk)
                    if len(audio) > _RESPONSE_LIMIT:
                        raise ValueError("oversized response")
    except (TimeoutError, httpx.TimeoutException) as exc:
        raise TimeoutError("Deepgram synthesis timed out; it may have been billed.") from exc
    except (httpx.HTTPError, OSError) as exc:
        raise SpeechProviderError("Deepgram synthesis request failed.") from exc
    usage: dict[str, object] = {}
    if char_count and char_count.isdigit():
        usage["characters_reported"] = int(char_count)
    return SynthesisResult(
        audio=bytes(audio), mime="audio/mpeg", characters=len(req.text), usage=usage
    )


register_adapter("deepgram", "tts", _deepgram_tts)


# --- Gradium -----------------------------------------------------------------
#
# Verified contract (docs.gradium.ai):
#   STT: POST /api/post/speech/asr, raw audio bytes, Content-Type selects
#   format (wav/pcm/ogg only — no webm/mp4), optional model + json_config
#   query params. Response is NDJSON: collect "text" messages, "error"
#   messages fail the request.
#   TTS: POST /api/post/speech/tts JSON {text, voice_id?, model_name,
#   output_format, only_audio:true} → raw audio bytes. x-api-key auth.

_GRADIUM_BASE = "https://api.gradium.ai/api"
_GRADIUM_STT_MIME = {"audio/wav", "audio/x-wav", "audio/pcm", "audio/ogg", "audio/opus"}


def _gradium_base(req: SpeechRequest) -> str:
    return (req.base_url or _GRADIUM_BASE).rstrip("/")


async def _gradium_stt(req: SpeechRequest) -> TranscriptResult:
    if not req.api_key:
        raise SpeechError("Gradium provider has no API key.")
    if req.mime and req.mime not in _GRADIUM_STT_MIME:
        raise SpeechError(f"Gradium transcription accepts wav/ogg/pcm audio, not '{req.mime}'.")
    base = _gradium_base(req)
    params: dict[str, str] = {"model": req.model}
    language = (req.options.get("language") or "").strip() if req.options.get("language") else ""
    if language:
        params["json_config"] = json.dumps({"language": language})
    headers = {
        "x-api-key": req.api_key,
        "Content-Type": req.mime or "audio/wav",
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
                    f"{base}/post/speech/asr",
                    params=params,
                    headers=headers,
                    content=req.audio,
                )
                if response.status_code != 200:
                    raise SpeechProviderError(
                        f"Gradium transcription failed (HTTP {response.status_code})."
                    )
                body = response.content
                if len(body) > _RESPONSE_LIMIT:
                    raise ValueError("oversized response")
    except (TimeoutError, httpx.TimeoutException) as exc:
        raise TimeoutError("Gradium transcription timed out; it may have been billed.") from exc
    except (httpx.HTTPError, OSError) as exc:
        raise SpeechProviderError("Gradium transcription request failed.") from exc

    parts: list[str] = []
    for line in body.decode("utf-8", "replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        if msg.get("type") == "error":
            raise SpeechProviderError("Gradium transcription failed mid-stream.")
        if msg.get("type") == "text" and msg.get("text"):
            parts.append(str(msg["text"]))
    return TranscriptResult(text=" ".join(parts).strip())


async def _gradium_tts(req: SpeechRequest) -> SynthesisResult:
    if not req.api_key:
        raise SpeechError("Gradium provider has no API key.")
    base = _gradium_base(req)
    headers = {
        "x-api-key": req.api_key,
        "Content-Type": "application/json",
    }
    voice = (req.options.get("voice") or "").strip() if req.options.get("voice") else ""
    payload: dict[str, object] = {
        "text": req.text,
        "model_name": req.model,
        "output_format": "wav",
        "only_audio": True,
    }
    if voice:
        payload["voice_id"] = voice
    try:
        async with asyncio.timeout(_TIMEOUT_S):
            async with httpx.AsyncClient(
                verify=SSL_CERT_PATH,
                timeout=_TIMEOUT_S,
                follow_redirects=False,
                trust_env=False,
            ) as client:
                response = await client.post(
                    f"{base}/post/speech/tts", headers=headers, json=payload
                )
                if response.status_code != 200:
                    raise SpeechProviderError(
                        f"Gradium synthesis failed (HTTP {response.status_code})."
                    )
                audio = bytearray()
                async for chunk in response.aiter_bytes(chunk_size=64 * 1024):
                    audio.extend(chunk)
                    if len(audio) > _RESPONSE_LIMIT:
                        raise ValueError("oversized response")
    except (TimeoutError, httpx.TimeoutException) as exc:
        raise TimeoutError("Gradium synthesis timed out; it may have been billed.") from exc
    except (httpx.HTTPError, OSError) as exc:
        raise SpeechProviderError("Gradium synthesis request failed.") from exc
    return SynthesisResult(audio=bytes(audio), mime="audio/wav", characters=len(req.text))


register_adapter("gradium", "stt", _gradium_stt)
register_adapter("gradium", "tts", _gradium_tts)
