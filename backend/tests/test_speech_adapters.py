"""Deepgram STT adapter fixtures — request shape, auth, normalization, and
honest failures. No live calls: verified contract is encoded in fixtures."""

import base64
import json

import httpx
import pytest

from agentos.speech.adapters import SpeechProviderError, _deepgram_stt
from agentos.speech.service import SpeechRequest


def _req(**over) -> SpeechRequest:
    base = dict(
        operation="stt",
        request_id="r1",
        provider_id="p1",
        provider_type="deepgram",
        model="nova-3",
        options={},
        api_key="dg-secret-key",
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


def _payload(text="hello world", duration=1.5):
    return {
        "metadata": {"request_id": "dg-123", "duration": duration},
        "results": {"channels": [{"alternatives": [{"transcript": text}]}]},
    }


async def test_request_shape_auth_and_model(monkeypatch):
    seen = []
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: _client(_payload(), capture=seen))
    req = _req(options={"language": "en"})
    result = await _deepgram_stt(req)

    request = seen[0]
    assert str(request.url).startswith("https://api.deepgram.com/v1/listen")
    assert request.url.params["model"] == "nova-3"
    assert request.url.params["language"] == "en"
    assert request.url.params["smart_format"] == "true"
    assert request.headers["authorization"] == "Token dg-secret-key"
    assert request.headers["content-type"] == "audio/wav"
    assert request.content == b"RIFF-fake"
    assert result.text == "hello world"
    assert result.audio_seconds == 1.5
    assert result.usage["dg_request_id"] == "dg-123"


async def test_blank_language_enables_detect_language(monkeypatch):
    seen = []
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: _client(_payload(), capture=seen))
    await _deepgram_stt(_req(options={"language": ""}))
    params = seen[0].url.params
    assert params["detect_language"] == "true"
    assert "language" not in params


async def test_empty_transcript_is_empty_result(monkeypatch):
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: _client(_payload(text="", duration=0.2)))
    result = await _deepgram_stt(_req())
    assert result.text == "" and result.audio_seconds == 0.2


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"results": {}},
        {"results": {"channels": []}},
        {"results": {"channels": [{"alternatives": None}]}},
        "not a dict",
    ],
)
async def test_malformed_payload_is_honest_error(monkeypatch, payload):
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: _client(payload))
    with pytest.raises(SpeechProviderError, match="unreadable"):
        await _deepgram_stt(_req())


@pytest.mark.parametrize("status", [400, 401, 403, 429, 500])
async def test_status_errors_never_echo_key_or_body(monkeypatch, status):
    body = json.dumps({"err": "key dg-secret-key rejected"}).encode()

    def handler(request):
        return httpx.Response(status, content=body)

    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kw: _REAL_CLIENT(transport=httpx.MockTransport(handler)),
    )
    with pytest.raises(SpeechProviderError) as exc:
        await _deepgram_stt(_req())
    assert f"HTTP {status}" in str(exc.value)
    assert "dg-secret-key" not in str(exc.value)


async def test_missing_key_is_clear_error():
    from agentos.speech.service import SpeechError

    with pytest.raises(SpeechError, match="no API key"):
        await _deepgram_stt(_req(api_key=None))


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


# --- Deepgram Aura TTS --------------------------------------------------------

from agentos.speech.adapters import _deepgram_tts  # noqa: E402


def _dg_tts_req(**over) -> SpeechRequest:
    base = dict(
        operation="tts",
        request_id="r5",
        provider_id="p5",
        provider_type="deepgram",
        model="aura-2-thalia-en",
        options={},
        api_key="dg-secret",
        binding_revision=1,
        text="read me",
    )
    base.update(over)
    return SpeechRequest(**base)


async def test_deepgram_tts_posts_text_and_collects_audio(monkeypatch):
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, content=b"MP3BYTES", headers={"dg-char-count": "7"})

    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kw: _REAL_CLIENT(transport=httpx.MockTransport(handler)),
    )
    result = await _deepgram_tts(_dg_tts_req())
    request = seen[0]
    assert str(request.url).startswith("https://api.deepgram.com/v1/speak")
    assert request.url.params["model"] == "aura-2-thalia-en"
    assert request.url.params["encoding"] == "mp3"
    assert request.headers["authorization"] == "Token dg-secret"
    assert json.loads(request.content) == {"text": "read me"}
    assert result.audio == b"MP3BYTES" and result.mime == "audio/mpeg"
    assert result.usage["characters_reported"] == 7


async def test_deepgram_tts_error_no_key_echo(monkeypatch):
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: _bytes_client(b"err", status=403))
    with pytest.raises(SpeechProviderError, match="403") as exc:
        await _deepgram_tts(_dg_tts_req())
    assert "dg-secret" not in str(exc.value)


# --- Gradium ------------------------------------------------------------------

from agentos.speech.adapters import _gradium_stt, _gradium_tts  # noqa: E402


def _gr_req(**over) -> SpeechRequest:
    base = dict(
        operation="stt",
        request_id="r6",
        provider_id="p6",
        provider_type="gradium",
        model="default",
        options={},
        api_key="gr-secret",
        binding_revision=1,
        audio=b"wav-bytes",
        mime="audio/wav",
    )
    base.update(over)
    return SpeechRequest(**base)


async def test_gradium_stt_ndjson_and_shape(monkeypatch):
    seen = []
    ndjson = b'{"type":"text","text":"hello"}\n{"type":"step"}\n{"type":"text","text":"world"}\n'
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: _bytes_client(ndjson, capture=seen))
    result = await _gradium_stt(_gr_req(options={"language": "en"}))
    request = seen[0]
    assert str(request.url).startswith("https://api.gradium.ai/api/post/speech/asr")
    assert request.headers["x-api-key"] == "gr-secret"
    assert request.headers["content-type"] == "audio/wav"
    assert request.url.params["model"] == "default"
    assert json.loads(request.url.params["json_config"]) == {"language": "en"}
    assert result.text == "hello world"


async def test_gradium_stt_rejects_webm_upfront(monkeypatch):
    called = []
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: called.append(1) or _client({}))
    with pytest.raises(SpeechError, match="wav/ogg/pcm"):
        await _gradium_stt(_gr_req(mime="audio/webm"))
    assert called == []


async def test_gradium_stt_stream_error_is_honest(monkeypatch):
    ndjson = b'{"type":"text","text":"hi"}\n{"type":"error","message":"x"}\n'
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: _bytes_client(ndjson))
    with pytest.raises(SpeechProviderError, match="mid-stream"):
        await _gradium_stt(_gr_req())


async def test_gradium_tts_only_audio_shape(monkeypatch):
    seen = []
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: _bytes_client(b"WAVDATA", capture=seen))
    result = await _gradium_tts(
        _gr_req(operation="tts", options={"voice": "YTpq7expH9539ERJ"}, text="hi")
    )
    request = seen[0]
    assert str(request.url) == "https://api.gradium.ai/api/post/speech/tts"
    payload = json.loads(request.content)
    assert payload["only_audio"] is True
    assert payload["output_format"] == "wav"
    assert payload["voice_id"] == "YTpq7expH9539ERJ"
    assert payload["text"] == "hi" and payload["model_name"] == "default"
    assert result.audio == b"WAVDATA" and result.mime == "audio/wav"
