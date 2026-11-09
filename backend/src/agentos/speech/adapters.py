"""Speech provider adapters — one small function per (type, operation).

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
import struct
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

_RESPONSE_LIMIT = 5 * 1024 * 1024  # JSON envelope — generous vs transcript size
_TIMEOUT_S = 60.0


class SpeechProviderError(SpeechError):
    """Provider call failed; message is operator-safe (status, not body)."""

    status_code = 502


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
    # verbose_json adds "duration" — the audio_seconds the receipt prices on.
    data: dict[str, str] = {"model": req.model, "response_format": "verbose_json"}
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
    duration = payload.get("duration") if isinstance(payload, dict) else None
    return TranscriptResult(
        text=transcript,
        audio_seconds=duration if isinstance(duration, (int, float)) else None,
    )


def _pcm_to_wav(pcm: bytes, *, rate: int, channels: int, bits: int = 16) -> bytes:
    """Wrap raw s16le PCM in a RIFF/WAVE header so browsers can play it."""
    byte_rate = rate * channels * bits // 8
    block_align = channels * bits // 8
    return (
        struct.pack(
            "<4sI4s4sIHHIIHH4sI",
            b"RIFF",
            36 + len(pcm),
            b"WAVE",
            b"fmt ",
            16,
            1,
            channels,
            rate,
            byte_rate,
            block_align,
            bits,
            b"data",
            len(pcm),
        )
        + pcm
    )


def _pcm_params(content_type: str) -> tuple[int, int]:
    rate = int(m.group(1)) if (m := re.search(r"rate=(\d+)", content_type)) else 24000
    ch = int(m.group(1)) if (m := re.search(r"channels=(\d+)", content_type)) else 1
    return rate, ch


# Format tokens recognised in provider error bodies, in the order providers
# tend to list them. Used for one-shot format retry below.
_KNOWN_FORMATS = (
    "mp3",
    "wav",
    "pcm",
    "opus",
    "aac",
    "flac",
    "ulaw",
    "mulaw",
    "alaw",
    "ogg",
    "linear16",
    "mp4",
)
_FORMAT_RE = re.compile(r"\b(" + "|".join(_KNOWN_FORMATS) + r")\b")


def _suggest_formats(body: bytes, attempted: str) -> str | None:
    """Extract an alternative response_format from an error body.

    HeyGen answers 'only supports response_format "pcm"'; ZodError-style
    bodies enumerate '"values": ["mp3","pcm"]'. First listed wins.
    """
    text = body[:4096].decode("utf-8", "replace").lower()
    for m in _FORMAT_RE.finditer(text):
        if m.group(1) != attempted:
            return m.group(1)
    return None


async def _post_speech(
    base: str, headers: dict[str, str], payload: dict[str, str]
) -> tuple[int, str, bytes]:
    """One /audio/speech POST. Returns (status, content_type, body).

    Body is the full audio stream on 200 (bounded 20 MiB), else the first
    4 KiB of the error body for format-hint parsing.
    """
    async with httpx.AsyncClient(
        verify=SSL_CERT_PATH,
        timeout=_TIMEOUT_S,
        follow_redirects=False,
        trust_env=False,
    ) as client:
        async with client.stream(
            "POST", _audio_url(base, "audio/speech"), headers=headers, json=payload
        ) as response:
            status = response.status_code
            ctype = response.headers.get("content-type", "")
            if status != 200:
                return status, ctype, (await response.aread())[:4096]
            audio = bytearray()
            async for chunk in response.aiter_bytes(chunk_size=64 * 1024):
                audio.extend(chunk)
                if len(audio) > 20 * 1024 * 1024:
                    raise ValueError("oversized response")
            return status, ctype, bytes(audio)


async def _audio_speech(
    req: SpeechRequest, base: str, *, default_voice: str | None = "alloy"
) -> SynthesisResult:
    voice = (req.options.get("voice") or "").strip() if req.options.get("voice") else ""
    fmt = (
        (req.options.get("response_format") or "").strip().lower()
        if req.options.get("response_format")
        else ""
    ) or "mp3"
    payload: dict[str, str] = {"model": req.model, "input": req.text}
    effective_voice = voice or default_voice
    if effective_voice:
        payload["voice"] = effective_voice
    headers = {"Authorization": f"Bearer {req.api_key}", "Content-Type": "application/json"}
    try:
        async with asyncio.timeout(_TIMEOUT_S):
            for attempt in (0, 1):
                status, ctype, body = await _post_speech(
                    base, headers, {**payload, "response_format": fmt}
                )
                if status == 200:
                    break
                # Some models (HeyGen) accept only one format. On a 4xx,
                # parse the provider's own error for the allowed value and
                # retry once — never more.
                retry_fmt = _suggest_formats(body, fmt) if 400 <= status < 500 else None
                if attempt == 0 and retry_fmt:
                    fmt = retry_fmt
                    continue
                raise SpeechProviderError(f"Speech synthesis failed (HTTP {status}).")
    except (TimeoutError, httpx.TimeoutException) as exc:
        raise TimeoutError("Speech synthesis timed out; it may have been billed.") from exc
    except (httpx.HTTPError, OSError) as exc:
        raise SpeechProviderError("Speech synthesis request failed.") from exc
    mime = "audio/mpeg"
    if "audio/pcm" in ctype:
        rate, channels = _pcm_params(ctype)
        body = _pcm_to_wav(body, rate=rate, channels=channels)
        mime = "audio/wav"
    return SynthesisResult(audio=body, mime=mime, characters=len(req.text))


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


# --- Gemini -------------------------------------------------------------------
#
# Verified contract (ai.google.dev speech + media docs): both operations ride
# POST /v1beta/models/{model}:generateContent with `x-goog-api-key` auth.
#   STT: audio goes as an inlineData part (base64 + mime_type); the reply's
#   text parts are the transcript.
#   TTS: generationConfig.responseModalities ["AUDIO"] +
#   speechConfig.voiceConfig.prebuiltVoiceConfig.voiceName; the reply's
#   inlineData.data is base64 raw PCM (audio/L16;rate=24000;channels=1),
#   which we wrap in WAV for browser playback.

_GEMINI_BASE = "https://generativelanguage.googleapis.com"


def _gemini_base(req: SpeechRequest) -> str:
    return (req.base_url or _GEMINI_BASE).rstrip("/")


async def _gemini_generate(req: SpeechRequest, payload: dict) -> dict:
    if not req.api_key:
        raise SpeechError("Gemini provider has no API key.")
    base = _gemini_base(req)
    headers = {"x-goog-api-key": req.api_key, "Content-Type": "application/json"}
    try:
        async with asyncio.timeout(_TIMEOUT_S):
            async with httpx.AsyncClient(
                verify=SSL_CERT_PATH,
                timeout=_TIMEOUT_S,
                follow_redirects=False,
                trust_env=False,
            ) as client:
                response = await client.post(
                    f"{base}/v1beta/models/{req.model}:generateContent",
                    headers=headers,
                    json=payload,
                )
                if response.status_code != 200:
                    raise SpeechProviderError(
                        f"Gemini audio request failed (HTTP {response.status_code})."
                    )
                body = response.content
                if len(body) > _RESPONSE_LIMIT * 4:  # base64 inflates ~33%
                    raise ValueError("oversized response")
        return json.loads(body)
    except (TimeoutError, httpx.TimeoutException) as exc:
        raise TimeoutError("Gemini audio request timed out; it may have been billed.") from exc
    except (httpx.HTTPError, OSError, json.JSONDecodeError) as exc:
        raise SpeechProviderError("Gemini audio request failed.") from exc


def _gemini_usage(out: dict) -> dict[str, object]:
    meta = out.get("usageMetadata") or {}
    total = meta.get("totalTokenCount")
    return {"tokens_reported": total} if isinstance(total, int) else {}


async def _gemini_stt(req: SpeechRequest) -> TranscriptResult:
    language = (req.options.get("language") or "").strip() if req.options.get("language") else ""
    hint = f" The spoken language is {language}." if language else ""
    payload = {
        "contents": [
            {
                "parts": [
                    {
                        "inlineData": {
                            "mimeType": req.mime or "audio/wav",
                            "data": base64.b64encode(req.audio).decode(),
                        }
                    },
                    {
                        "text": (
                            "Transcribe this audio verbatim. Output only the "
                            f"transcript text, nothing else.{hint}"
                        ),
                    },
                ]
            }
        ],
    }
    out = await _gemini_generate(req, payload)
    try:
        parts = out["candidates"][0]["content"]["parts"]
        transcript = " ".join(p["text"] for p in parts if p.get("text")).strip()
    except (KeyError, IndexError, TypeError, AttributeError) as exc:
        raise SpeechProviderError("Gemini returned an unreadable transcription.") from exc
    return TranscriptResult(text=transcript, usage=_gemini_usage(out))


async def _gemini_tts(req: SpeechRequest) -> SynthesisResult:
    voice = (req.options.get("voice") or "").strip() if req.options.get("voice") else ""
    generation_config: dict[str, object] = {"responseModalities": ["AUDIO"]}
    if voice:
        generation_config["speechConfig"] = {
            "voiceConfig": {"prebuiltVoiceConfig": {"voiceName": voice}}
        }
    payload = {
        "contents": [{"parts": [{"text": req.text}]}],
        "generationConfig": generation_config,
    }
    out = await _gemini_generate(req, payload)
    inline: dict | None = None
    try:
        for part in out["candidates"][0]["content"]["parts"]:
            if isinstance(part, dict) and part.get("inlineData"):
                inline = part["inlineData"]
                break
    except (KeyError, IndexError, TypeError) as exc:
        raise SpeechProviderError("Gemini returned an unreadable response.") from exc
    if inline is None or not inline.get("data"):
        raise SpeechProviderError("Gemini returned no audio output.")
    try:
        audio = base64.b64decode(inline["data"])
    except (ValueError, TypeError) as exc:
        raise SpeechProviderError("Gemini returned no audio output.") from exc
    mime = str(inline.get("mimeType") or "")
    if "l16" in mime.lower() or "pcm" in mime.lower() or not mime:
        rate, channels = _pcm_params(mime)
        audio = _pcm_to_wav(audio, rate=rate, channels=channels)
        mime = "audio/wav"
    return SynthesisResult(
        audio=audio, mime=mime, characters=len(req.text), usage=_gemini_usage(out)
    )


register_adapter("gemini", "stt", _gemini_stt)
register_adapter("gemini", "tts", _gemini_tts)
