"""Deepgram STT adapter fixtures — request shape, auth, normalization, and
honest failures. No live calls: verified contract is encoded in fixtures."""

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
