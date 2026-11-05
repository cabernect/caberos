"""W10 — shared speech operation service + operator endpoints.

Operator actions, not agent tools: frozen binding, bounded inputs, adapter
dispatch, one model_calls receipt per real attempt, honest failures.
"""

import asyncio
import json
import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from agentos.api import speech as speech_api
from agentos.auth import require_operator
from agentos.db import get_db
from agentos.main import app
from agentos.models.model_call import ModelCall
from agentos.models.operator import Operator
from agentos.models.provider import Provider
from agentos.models.run import Message, Run
from agentos.models.tool_binding import ToolBinding
from agentos.secret_store import encrypt
from agentos.speech import service as speech_service
from agentos.speech.service import (
    SpeechBounds,
    SpeechError,
    SpeechNotConfigured,
    SpeechUnavailable,
    SynthesisResult,
    TranscriptResult,
    synthesize,
    transcribe,
)


@pytest.fixture
async def client(db):
    async def fake_operator():
        return Operator(id="test-operator", username="test", password_hash="x")

    app.dependency_overrides[require_operator] = fake_operator
    app.dependency_overrides[get_db] = lambda: db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as http:
        yield http
    app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def clean_adapters():
    saved = dict(speech_service._ADAPTERS)
    yield
    speech_service._ADAPTERS.clear()
    speech_service._ADAPTERS.update(saved)


@pytest.fixture(autouse=True)
def clean_rate_limit():
    for q in speech_api._requests.values():
        q.clear()
    yield


async def _speech_provider(db, type_="deepgram") -> Provider:
    p = Provider(
        id=str(uuid.uuid4()),
        name="SpeechProv",
        type=type_,
        encrypted_key=encrypt("fake-key"),
        base_url=None,
        org_id=None,
        extra_params="{}",
        custom_models="[]",
    )
    db.add(p)
    await db.flush()
    return p


async def _bind(db, key, provider, model="nova-3", options=None):
    b = ToolBinding(
        id=str(uuid.uuid4()),
        key=key,
        provider_id=provider.id,
        model=model,
        options=json.dumps(options or {}),
    )
    db.add(b)
    await db.flush()
    return b


async def _message(db, role="assistant", content="Hello there."):
    run = Run(
        id=str(uuid.uuid4()),
        session_id=str(uuid.uuid4()),
        agent_id=str(uuid.uuid4()),
        contact_id="contact-1",
    )
    db.add(run)
    msg = Message(id=str(uuid.uuid4()), run_id=run.id, role=role, content=content, seq=1)
    db.add(msg)
    await db.flush()
    return msg, run


# --- service ---


async def test_transcribe_unconfigured_is_honest(db):
    with pytest.raises(SpeechNotConfigured):
        await transcribe(db=db, audio=b"x", mime="audio/wav")


async def test_transcribe_bounds_and_mime_before_dispatch(db):
    with pytest.raises(SpeechBounds):
        await transcribe(db=db, audio=b"x" * (speech_service.STT_MAX_AUDIO_BYTES + 1), mime="a")
    with pytest.raises(SpeechError, match="Unsupported audio format"):
        await transcribe(db=db, audio=b"x", mime="application/pdf")


async def test_cancel_before_dispatch_makes_no_calls(db, monkeypatch):
    called = False
    monkeypatch.setitem(
        speech_service._ADAPTERS,
        ("deepgram", "stt"),
        lambda req: called or True,  # would flag if reached
    )
    cancel = asyncio.Event()
    cancel.set()
    with pytest.raises(asyncio.CancelledError):
        await transcribe(db=db, audio=b"x", mime="audio/wav", cancel=cancel)
    assert called is False
    assert (await db.scalars(select(ModelCall))).all() == []


async def test_transcribe_dispatch_records_receipt(db, monkeypatch):
    provider = await _speech_provider(db)
    binding = await _bind(db, "speech.stt", provider, model="nova-3", options={"language": "en"})
    seen = {}

    async def fake(req):
        seen["model"] = req.model
        seen["options"] = req.options
        seen["revision"] = req.binding_revision
        return TranscriptResult(text="hello world", audio_seconds=1.2)

    monkeypatch.setitem(speech_service._ADAPTERS, ("deepgram", "stt"), fake)
    result, request_id = await transcribe(db=db, audio=b"pcm", mime="audio/wav")
    assert result.text == "hello world"
    assert seen == {"model": "nova-3", "options": {"language": "en"}, "revision": binding.revision}

    rows = (await db.scalars(select(ModelCall))).all()
    assert len(rows) == 1
    row = rows[0]
    assert row.kind == "speech" and row.purpose == "transcription"
    assert row.provider_id == provider.id and row.model_name == "nova-3"
    assert row.status == "ok" and row.tokens_in == 0 and row.cost == 0.0
    assert row.detail["request_id"] == request_id
    assert row.detail["operation"] == "stt"
    assert row.detail["audio_seconds"] == 1.2
    assert row.detail["binding_revision"] == binding.revision


async def test_adapter_error_records_failed_receipt(db, monkeypatch):
    provider = await _speech_provider(db)
    await _bind(db, "speech.stt", provider)

    async def boom(req):
        raise RuntimeError("provider exploded")

    monkeypatch.setitem(speech_service._ADAPTERS, ("deepgram", "stt"), boom)
    with pytest.raises(RuntimeError):
        await transcribe(db=db, audio=b"x", mime="audio/wav")
    rows = (await db.scalars(select(ModelCall))).all()
    assert rows[0].status == "error"
    assert "provider exploded" not in (rows[0].error or "")  # type-only receipt


async def test_unknown_provider_type_is_honest_unavailable(db):
    provider = await _speech_provider(db, type_="gradium")
    await _bind(db, "speech.stt", provider)
    with pytest.raises(SpeechUnavailable, match="gradium.*stt"):
        await transcribe(db=db, audio=b"x", mime="audio/wav")


async def test_synthesize_bounds_and_empty(db):
    with pytest.raises(SpeechBounds):
        await synthesize(db=db, text="x" * 10_001)
    with pytest.raises(SpeechError, match="Nothing speakable"):
        await synthesize(db=db, text="   ")


async def test_synthesize_records_receipt_and_caps_output(db, monkeypatch):
    provider = await _speech_provider(db, type_="elevenlabs")
    await _bind(db, "speech.tts", provider, model="eleven_multilingual_v2")

    async def fake(req):
        return SynthesisResult(audio=b"mp3" * 10, mime="audio/mpeg", characters=len(req.text))

    monkeypatch.setitem(speech_service._ADAPTERS, ("elevenlabs", "tts"), fake)
    result, request_id = await synthesize(db=db, text="read this", session_id="s1", agent_id="a1")
    assert result.audio
    rows = (await db.scalars(select(ModelCall))).all()
    assert rows[0].purpose == "synthesis"
    assert rows[0].detail["text_chars"] == len("read this")
    assert rows[0].session_id == "s1" and rows[0].agent_id == "a1"

    async def huge(req):
        return SynthesisResult(audio=b"x" * (speech_service.TTS_MAX_AUDIO_BYTES + 1))

    monkeypatch.setitem(speech_service._ADAPTERS, ("elevenlabs", "tts"), huge)
    with pytest.raises(SpeechBounds):
        await synthesize(db=db, text="again")


# --- endpoints ---


async def test_status_reports_readiness(client, db):
    r = await client.get("/api/speech/status")
    assert r.status_code == 200
    body = r.json()
    assert body["stt"]["ready"] is False and body["stt"]["configured"] is False
    assert body["tts"]["ready"] is False

    provider = await _speech_provider(db)
    await _bind(db, "speech.stt", provider)
    r = await client.get("/api/speech/status")
    body = r.json()["stt"]
    assert body["configured"] is True
    assert body["adapter"] is False  # no real adapter registered
    assert body["provider"] == "SpeechProv" and body["model"] == "nova-3"


async def test_transcribe_endpoint_flow(client, db, monkeypatch):
    provider = await _speech_provider(db)
    await _bind(db, "speech.stt", provider)

    async def fake(req):
        return TranscriptResult(text="transcribed words", audio_seconds=0.5)

    monkeypatch.setitem(speech_service._ADAPTERS, ("deepgram", "stt"), fake)
    r = await client.post(
        "/api/speech/transcribe",
        files={"file": ("note.wav", b"RIFF-data", "audio/wav")},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["transcript"] == "transcribed words"
    assert body["request_id"] and body["model"] == "nova-3"


async def test_transcribe_endpoint_rejects_oversize_and_mime(client):
    big = b"x" * (speech_service.STT_MAX_AUDIO_BYTES + 1)
    r = await client.post("/api/speech/transcribe", files={"file": ("a.wav", big, "audio/wav")})
    assert r.status_code == 413
    r = await client.post(
        "/api/speech/transcribe", files={"file": ("a.pdf", b"x", "application/pdf")}
    )
    assert r.status_code == 422


async def test_synthesize_endpoint_authorizes_message(client, db, monkeypatch):
    user_msg, _ = await _message(db, role="user", content="hi")
    r = await client.post("/api/speech/synthesize", json={"message_id": user_msg.id})
    assert r.status_code == 422

    code_only, _ = await _message(db, content="```\ncode only\n```")
    r = await client.post("/api/speech/synthesize", json={"message_id": code_only.id})
    assert r.status_code == 422
    assert "speakable" in r.json()["detail"]

    r = await client.post("/api/speech/synthesize", json={"message_id": "missing"})
    assert r.status_code == 404


async def test_synthesize_endpoint_renders_and_returns_audio(client, db, monkeypatch):
    provider = await _speech_provider(db, type_="elevenlabs")
    await _bind(db, "speech.tts", provider)
    msg, run = await _message(db, content="Here is [the link](https://x):\n\n```\ncode()\n```")
    seen = {}

    async def fake(req):
        seen["text"] = req.text
        return SynthesisResult(audio=b"AUDIO", mime="audio/mpeg")

    monkeypatch.setitem(speech_service._ADAPTERS, ("elevenlabs", "tts"), fake)
    r = await client.post("/api/speech/synthesize", json={"message_id": msg.id})
    assert r.status_code == 200
    assert r.content == b"AUDIO"
    assert r.headers["x-speech-request-id"]
    assert seen["text"] == "Here is the link: (code omitted)"

    row = (await db.scalars(select(ModelCall))).all()[-1]
    assert row.session_id == run.session_id and row.detail["message_id"] == msg.id
