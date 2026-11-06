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
