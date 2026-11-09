"""Gemini speech adapter fixtures — generateContent shapes for STT
inlineData and TTS audio modality, auth, PCM→WAV wrapping, and honest
failures. No live calls: verified contract is encoded in fixtures."""

import base64
import json

import httpx
import pytest

from agentos.speech.adapters import SpeechProviderError, _gemini_stt
from agentos.speech.service import SpeechRequest


def _req(**over) -> SpeechRequest:
    base = dict(
        operation="stt",
        request_id="r1",
        provider_id="p1",
        provider_type="gemini",
        model="gemini-2.5-flash",
        options={},
        api_key="gm-secret-key",
        binding_revision=3,
        audio=b"RIFF-fake",
        mime="audio/wav",
    )
    base.update(over)
    return SpeechRequest(**base)


_REAL_CLIENT = httpx.AsyncClient


def _client(payload, status=200, capture=None):
    def handler(request: httpx.Request) -> httpx.Response:
        if capture is not None:
            capture.append(request)
        return httpx.Response(status, json=payload)

    return _REAL_CLIENT(transport=httpx.MockTransport(handler))


def _bytes_client(body: bytes, status=200, capture=None, ctype="application/octet-stream"):
    def handler(request: httpx.Request) -> httpx.Response:
        if capture is not None:
            capture.append(request)
        return httpx.Response(status, content=body, headers={"content-type": ctype})

    return _REAL_CLIENT(transport=httpx.MockTransport(handler))


def _stt_payload(text="hello world"):
    return {
        "candidates": [{"content": {"parts": [{"text": text}]}}],
        "usageMetadata": {"totalTokenCount": 42},
    }


async def test_stt_request_shape_auth_and_transcript(monkeypatch):
    seen = []
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: _client(_stt_payload(), capture=seen))
    result = await _gemini_stt(_req(options={"language": "vi"}))

    request = seen[0]
    assert (
        str(request.url)
        == "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent"
    )
    assert request.headers["x-goog-api-key"] == "gm-secret-key"
    parts = json.loads(request.content)["contents"][0]["parts"]
    assert parts[0]["inlineData"]["mimeType"] == "audio/wav"
    assert base64.b64decode(parts[0]["inlineData"]["data"]) == b"RIFF-fake"
    assert "vi" in parts[1]["text"]
    assert result.text == "hello world"
    assert result.usage["tokens_reported"] == 42


@pytest.mark.parametrize(
    "payload",
    [{}, {"candidates": []}, {"candidates": [{"content": {"parts": None}}]}, "not a dict"],
)
async def test_stt_malformed_payload_is_honest_error(monkeypatch, payload):
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: _client(payload))
    with pytest.raises(SpeechProviderError, match="unreadable"):
        await _gemini_stt(_req())


@pytest.mark.parametrize("status", [400, 401, 403, 429, 500])
async def test_status_errors_never_echo_key_or_body(monkeypatch, status):
    body = json.dumps({"err": "key gm-secret-key rejected"}).encode()

    def handler(request):
        return httpx.Response(status, content=body)

    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kw: _REAL_CLIENT(transport=httpx.MockTransport(handler)),
    )
    with pytest.raises(SpeechProviderError) as exc:
        await _gemini_stt(_req())
    assert f"HTTP {status}" in str(exc.value)
    assert "gm-secret-key" not in str(exc.value)


async def test_missing_key_is_clear_error():
    from agentos.speech.service import SpeechError

    with pytest.raises(SpeechError, match="no API key"):
        await _gemini_stt(_req(api_key=None))


# --- OpenAI-compatible audio adapters ---------------------------------------

from agentos.speech.adapters import _openai_stt, _openai_tts  # noqa: E402


def _oai_req(**over) -> SpeechRequest:
    base = dict(
        operation="stt",
        request_id="r2",
        provider_id="p2",
        provider_type="openai",
        model="whisper-1",
        options={},
        api_key="sk-test",
        binding_revision=1,
        audio=b"wav-bytes",
        mime="audio/wav",
    )
    base.update(over)
    return SpeechRequest(**base)


async def test_openai_stt_multipart_shape_and_defaults(monkeypatch):
    seen = []
    monkeypatch.setattr(
        httpx, "AsyncClient", lambda **kw: _client({"text": "hi there"}, capture=seen)
    )
    result = await _openai_stt(_oai_req(options={"language": "vi"}))
    request = seen[0]
    assert str(request.url) == "https://api.openai.com/v1/audio/transcriptions"
    assert request.headers["authorization"] == "Bearer sk-test"
    body = request.content.decode()
    assert 'name="model"' in body and "whisper-1" in body
    assert 'name="language"' in body and "vi" in body
    assert 'name="file"' in body and "audio/wav" in body
    assert result.text == "hi there"


async def test_openai_stt_groq_base_and_no_language_param(monkeypatch):
    seen = []
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: _client({"text": "x"}, capture=seen))
    await _openai_stt(_oai_req(provider_type="groq", model="whisper-large-v3"))
    assert str(seen[0].url).startswith("https://api.groq.com/openai/v1/audio/transcriptions")
    assert 'name="language"' not in seen[0].content.decode()


async def test_openai_stt_custom_base_url_wins(monkeypatch):
    seen = []
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: _client({"text": "x"}, capture=seen))
    await _openai_stt(_oai_req(base_url="http://localhost:9999/api"))
    assert str(seen[0].url).startswith("http://localhost:9999/api/v1/audio/transcriptions")


async def test_openai_stt_verbose_json_400_retries_once_with_json(monkeypatch):
    """gpt-transcribe family rejects verbose_json; the adapter retries once
    with json and still reads duration from usage.seconds."""
    seen = []

    def handler(request):
        seen.append(request)
        if len(seen) == 1:
            return httpx.Response(
                400,
                json={
                    "error": {
                        "message": "response_format 'verbose_json' is not compatible "
                        "with model 'gpt-transcribe'. Use 'json' or 'text' instead."
                    }
                },
            )
        return httpx.Response(200, json={"text": "hi", "usage": {"seconds": 1.0}})

    monkeypatch.setattr(
        httpx, "AsyncClient", lambda **kw: _REAL_CLIENT(transport=httpx.MockTransport(handler))
    )
    result = await _openai_stt(_oai_req(model="gpt-transcribe"))
    assert len(seen) == 2
    assert 'verbose_json' in seen[0].content.decode()
    assert 'name="response_format"\r\n\r\njson' in seen[1].content.decode()
    assert result.text == "hi" and result.audio_seconds == 1.0


async def test_openai_stt_non_format_400_does_not_retry(monkeypatch):
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(400, json={"error": {"message": "corrupted file"}})

    monkeypatch.setattr(
        httpx, "AsyncClient", lambda **kw: _REAL_CLIENT(transport=httpx.MockTransport(handler))
    )
    with pytest.raises(SpeechProviderError, match="400"):
        await _openai_stt(_oai_req())
    assert len(seen) == 1


async def test_openai_tts_shape_and_bytes(monkeypatch):
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, content=b"MP3BYTES", headers={"content-type": "audio/mpeg"})

    monkeypatch.setattr(
        httpx, "AsyncClient", lambda **kw: _REAL_CLIENT(transport=httpx.MockTransport(handler))
    )
    req = _oai_req(operation="tts", model="tts-1", options={"voice": "nova"}, text="say this")
    result = await _openai_tts(req)
    request = seen[0]
    assert str(request.url) == "https://api.openai.com/v1/audio/speech"
    payload = json.loads(request.content)
    assert payload == {
        "model": "tts-1",
        "voice": "nova",
        "input": "say this",
        "response_format": "mp3",
    }
    assert result.audio == b"MP3BYTES" and result.mime == "audio/mpeg"


@pytest.mark.parametrize("fn", [_openai_stt, _openai_tts])
async def test_openai_errors_never_echo_key(monkeypatch, fn):
    def handler(request):
        return httpx.Response(401, content=b'{"error": "bad key sk-test"}')

    monkeypatch.setattr(
        httpx, "AsyncClient", lambda **kw: _REAL_CLIENT(transport=httpx.MockTransport(handler))
    )
    with pytest.raises(SpeechProviderError) as exc:
        await fn(_oai_req(operation="stt" if fn is _openai_stt else "tts"))
    assert "sk-test" not in str(exc.value)


# --- OpenRouter chat-completions audio --------------------------------------

from agentos.speech.adapters import _openrouter_stt, _openrouter_tts  # noqa: E402


def _or_req(**over) -> SpeechRequest:
    base = dict(
        operation="stt",
        request_id="r3",
        provider_id="p3",
        provider_type="openrouter",
        model="openai/gpt-4o-audio-preview",
        options={},
        api_key="sk-or-test",
        binding_revision=1,
        audio=b"wav-bytes",
        mime="audio/wav",
    )
    base.update(over)
    return SpeechRequest(**base)


async def test_openrouter_stt_uses_input_audio_parts(monkeypatch):
    seen = []
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kw: _client(
            {"choices": [{"message": {"role": "assistant", "content": "spoken words"}}]},
            capture=seen,
        ),
    )
    result = await _openrouter_stt(_or_req(options={"language": "vi"}))
    request = seen[0]
    assert str(request.url) == "https://openrouter.ai/api/v1/chat/completions"
    assert request.headers["authorization"] == "Bearer sk-or-test"
    payload = json.loads(request.content)
    parts = payload["messages"][0]["content"]
    assert parts[0]["type"] == "text" and "vi" in parts[0]["text"]
    audio = parts[1]["input_audio"]
    assert base64.b64decode(audio["data"]) == b"wav-bytes" and audio["format"] == "wav"
    assert result.text == "spoken words"


async def test_openrouter_tts_requests_modalities_and_decodes(monkeypatch):
    seen = []
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kw: _client(
            {"choices": [{"message": {"audio": {"data": base64.b64encode(b"MP3X").decode()}}}]},
            capture=seen,
        ),
    )
    req = _or_req(
        operation="tts",
        model="openai/gpt-4o-audio-preview",
        options={"voice": "shimmer"},
        text="read me",
    )
    result = await _openrouter_tts(req)
    payload = json.loads(seen[0].content)
    assert payload["modalities"] == ["text", "audio"]
    assert payload["audio"] == {"voice": "shimmer", "format": "mp3"}
    assert "read me" in payload["messages"][0]["content"]
    assert result.audio == b"MP3X" and result.mime == "audio/mpeg"


async def test_openrouter_tts_no_voice_omits_voice_field(monkeypatch):
    seen = []
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kw: _client(
            {"choices": [{"message": {"audio": {"data": base64.b64encode(b"A").decode()}}}]},
            capture=seen,
        ),
    )
    await _openrouter_tts(_or_req(operation="tts", text="x"))
    payload = json.loads(seen[0].content)
    assert payload["audio"] == {"format": "mp3"}  # no invented provider default


async def test_openrouter_tts_missing_audio_is_honest(monkeypatch):
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kw: _client({"choices": [{"message": {"content": "no audio"}}]}),
    )
    with pytest.raises(SpeechProviderError, match="no audio"):
        await _openrouter_tts(_or_req(operation="tts", text="x"))


# --- ElevenLabs -------------------------------------------------------------

from agentos.speech.adapters import _elevenlabs_stt, _elevenlabs_tts  # noqa: E402
from agentos.speech.service import SpeechError  # noqa: E402


def _bytes_client(body: bytes, status=200, capture=None):
    def handler(request: httpx.Request) -> httpx.Response:
        if capture is not None:
            capture.append(request)
        return httpx.Response(status, content=body)

    return _REAL_CLIENT(transport=httpx.MockTransport(handler))


def _el_req(**over) -> SpeechRequest:
    base = dict(
        operation="stt",
        request_id="r4",
        provider_id="p4",
        provider_type="elevenlabs",
        model="scribe_v2",
        options={},
        api_key="el-secret",
        binding_revision=1,
        audio=b"wav-bytes",
        mime="audio/wav",
    )
    base.update(over)
    return SpeechRequest(**base)


async def test_elevenlabs_stt_multipart_shape(monkeypatch):
    seen = []
    monkeypatch.setattr(
        httpx, "AsyncClient", lambda **kw: _client({"text": "spoken"}, capture=seen)
    )
    result = await _elevenlabs_stt(_el_req(options={"language": "eng"}))
    request = seen[0]
    assert str(request.url) == "https://api.elevenlabs.io/v1/speech-to-text"
    assert request.headers["xi-api-key"] == "el-secret"
    body = request.content.decode()
    assert 'name="model_id"' in body and "scribe_v2" in body
    assert 'name="language_code"' in body and "eng" in body
    assert 'name="file"' in body
    assert result.text == "spoken"


async def test_elevenlabs_tts_posts_to_voice_path(monkeypatch):
    seen = []
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: _bytes_client(b"MP3DATA", capture=seen))
    req = _el_req(
        operation="tts",
        model="eleven_multilingual_v2",
        options={"voice": "21m00Tcm4TlvDq8ikWAM"},
        text="hi",
    )
    result = await _elevenlabs_tts(req)
    request = seen[0]
    assert str(request.url) == "https://api.elevenlabs.io/v1/text-to-speech/21m00Tcm4TlvDq8ikWAM"
    payload = json.loads(request.content)
    assert payload == {"text": "hi", "model_id": "eleven_multilingual_v2"}
    assert result.audio == b"MP3DATA" and result.mime == "audio/mpeg"


async def test_elevenlabs_tts_missing_voice_is_honest(monkeypatch):
    called = []
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: called.append(1) or _client({}))
    with pytest.raises(SpeechError, match="voice ID"):
        await _elevenlabs_tts(_el_req(operation="tts", text="x"))
    assert called == []


async def test_elevenlabs_stt_error_no_key_echo(monkeypatch):
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: _client({"detail": "bad"}, status=401))
    with pytest.raises(SpeechProviderError, match="401") as exc:
        await _elevenlabs_stt(_el_req())
    assert "el-secret" not in str(exc.value)


async def test_elevenlabs_tts_error_no_key_echo(monkeypatch):
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: _bytes_client(b"err", status=429))
    with pytest.raises(SpeechProviderError, match="429") as exc:
        await _elevenlabs_tts(_el_req(operation="tts", options={"voice": "v"}, text="x"))
    assert "el-secret" not in str(exc.value)


# --- Gemini TTS ---------------------------------------------------------------

from agentos.speech.adapters import _gemini_tts  # noqa: E402


def _gm_tts_req(**over) -> SpeechRequest:
    base = dict(
        operation="tts",
        request_id="r5",
        provider_id="p5",
        provider_type="gemini",
        model="gemini-2.5-flash-preview-tts",
        options={"voice": "Kore"},
        api_key="gm-secret",
        binding_revision=1,
        text="read me",
    )
    base.update(over)
    return SpeechRequest(**base)


def _tts_payload(pcm: bytes, mime="audio/L16;rate=24000;channels=1"):
    return {
        "candidates": [
            {
                "content": {
                    "parts": [
                        {"inlineData": {"mimeType": mime, "data": base64.b64encode(pcm).decode()}}
                    ]
                }
            }
        ],
        "usageMetadata": {"totalTokenCount": 30},
    }


async def test_gemini_tts_shape_and_pcm_to_wav(monkeypatch):
    seen = []
    pcm = b"\x01\x02" * 240  # pretend s16le frames
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: _client(_tts_payload(pcm), capture=seen))
    result = await _gemini_tts(_gm_tts_req())
    request = seen[0]
    assert (
        str(request.url) == "https://generativelanguage.googleapis.com/v1beta/models/"
        "gemini-2.5-flash-preview-tts:generateContent"
    )
    assert request.headers["x-goog-api-key"] == "gm-secret"
    payload = json.loads(request.content)
    assert payload["contents"][0]["parts"][0]["text"] == "read me"
    gc = payload["generationConfig"]
    assert gc["responseModalities"] == ["AUDIO"]
    assert gc["speechConfig"]["voiceConfig"]["prebuiltVoiceConfig"]["voiceName"] == "Kore"
    assert result.mime == "audio/wav"
    assert result.audio[:4] == b"RIFF" and result.audio[8:12] == b"WAVE"
    assert result.audio[44:] == pcm
    assert result.usage["tokens_reported"] == 30


async def test_gemini_tts_voiceless_omits_speech_config(monkeypatch):
    seen = []
    monkeypatch.setattr(
        httpx, "AsyncClient", lambda **kw: _client(_tts_payload(b"\x00" * 4), capture=seen)
    )
    await _gemini_tts(_gm_tts_req(options={}))
    gc = json.loads(seen[0].content)["generationConfig"]
    assert gc["responseModalities"] == ["AUDIO"]
    assert "speechConfig" not in gc


async def test_gemini_tts_no_audio_part_is_honest(monkeypatch):
    payload = {"candidates": [{"content": {"parts": [{"text": "no audio"}]}}]}
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: _client(payload))
    with pytest.raises(SpeechProviderError, match="no audio"):
        await _gemini_tts(_gm_tts_req())


async def test_gemini_tts_error_no_key_echo(monkeypatch):
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: _bytes_client(b"err", status=403))
    with pytest.raises(SpeechProviderError, match="403") as exc:
        await _gemini_tts(_gm_tts_req())
    assert "gm-secret" not in str(exc.value)


async def test_openrouter_dedicated_tts_uses_audio_speech(monkeypatch):
    """heygen-voice-* serves POST /api/v1/audio/speech, not chat completions.
    It rejects mp3 — the adapter parses the error's allowed format and
    retries once with pcm, then wraps to WAV for playback."""
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        fmt = json.loads(request.content)["response_format"]
        if fmt != "pcm":
            return httpx.Response(
                400,
                json={
                    "error": {
                        "message": 'HeyGen Voice only supports response_format "pcm".',
                        "code": 400,
                    }
                },
            )
        return httpx.Response(
            200,
            content=b"PCM16",
            headers={"content-type": "audio/pcm;rate=44100;channels=1"},
        )

    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kw: _REAL_CLIENT(transport=httpx.MockTransport(handler)),
    )
    result = await _openrouter_tts(
        _or_req(
            operation="tts",
            model="heygen/heygen-voice-1-turbo",
            options={"voice": "nadine"},
            text="hi",
        )
    )
    assert len(seen) == 2
    assert str(seen[0].url) == "https://openrouter.ai/api/v1/audio/speech"
    first, second = (json.loads(r.content) for r in seen)
    assert first["response_format"] == "mp3" and first["voice"] == "nadine"
    assert second["response_format"] == "pcm" and second["voice"] == "nadine"
    assert result.mime == "audio/wav"
    assert result.audio[:4] == b"RIFF" and result.audio[8:12] == b"WAVE"
    assert result.audio.endswith(b"PCM16")


async def test_audio_speech_no_retry_without_format_hint(monkeypatch):
    """A 4xx whose body mentions no other format fails after one request."""
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(400, json={"error": {"message": "voice not found"}})

    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kw: _REAL_CLIENT(transport=httpx.MockTransport(handler)),
    )
    with pytest.raises(SpeechProviderError):
        await _openrouter_tts(
            _or_req(
                operation="tts",
                model="heygen/heygen-voice-1-turbo",
                options={"voice": "bogus"},
                text="hi",
            )
        )
    assert len(seen) == 1


async def test_audio_speech_retry_exhausted_raises(monkeypatch):
    """A second 4xx is not retried again."""
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            400,
            json={"error": {"message": 'HeyGen Voice only supports response_format "pcm".'}},
        )

    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kw: _REAL_CLIENT(transport=httpx.MockTransport(handler)),
    )
    with pytest.raises(SpeechProviderError):
        await _openrouter_tts(
            _or_req(
                operation="tts",
                model="heygen/heygen-voice-1-turbo",
                options={"voice": "nadine"},
                text="hi",
            )
        )
    assert len(seen) == 2


async def test_audio_speech_explicit_format_wins(monkeypatch):
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, content=b"MP3", headers={"content-type": "audio/mpeg"})

    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kw: _REAL_CLIENT(transport=httpx.MockTransport(handler)),
    )
    result = await _openrouter_tts(
        _or_req(
            operation="tts",
            model="heygen/heygen-voice-1-turbo",
            options={"voice": "nadine", "response_format": "mp3"},
            text="hi",
        )
    )
    assert json.loads(seen[0].content)["response_format"] == "mp3"
    assert result.mime == "audio/mpeg" and result.audio == b"MP3"


async def test_openrouter_dedicated_stt_uses_audio_transcriptions(monkeypatch):
    seen = []
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: _client({"text": "hi"}, capture=seen))
    result = await _openrouter_stt(_or_req(model="openai/whisper-1"))
    request = seen[0]
    assert str(request.url) == "https://openrouter.ai/api/v1/audio/transcriptions"
    assert result.text == "hi"


async def test_audio_url_joins_without_double_v1():
    from agentos.speech.adapters import _audio_url

    assert _audio_url("https://api.openai.com", "audio/speech") == (
        "https://api.openai.com/v1/audio/speech"
    )
    assert _audio_url("http://localhost:8000/v1", "audio/speech") == (
        "http://localhost:8000/v1/audio/speech"
    )
    assert _audio_url("https://openrouter.ai/api/v1", "audio/speech") == (
        "https://openrouter.ai/api/v1/audio/speech"
    )
