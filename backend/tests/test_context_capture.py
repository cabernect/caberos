"""Model request capture — redacted dispatch bodies, capture↔receipt
correlation, retention, scope isolation, and the ledger boundary.
"""

import json
import uuid
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from agentos.agent_service import create_agent
from agentos.config_schema import AgentConfig, CapabilityGrant, ModelConfig
from agentos.harness.loop import Harness
from agentos.harness.scripted_model import ScriptedResponse
from agentos.models.model_call import ModelCall
from agentos.models.request_capture import ModelRequestCapture
from agentos.pipeline import InboundMessage, Pipeline


def _caps(*names: str) -> list[CapabilityGrant]:
    return [CapabilityGrant(name=n, require_approval=False) for n in names]


async def _agent(db, agent_id="cap-test", **kw):
    config = AgentConfig(
        id=agent_id,
        name="Capture Test",
        model=ModelConfig(provider_id="test", name="test-model"),
        soul="S",
        persona="P",
        task="K",
        capabilities=kw.pop("capabilities", _caps("datetime_now")),
        **kw,
    )
    await create_agent(db, config)
    return config


def _inbound(agent_id, text, session_id=None):
    return InboundMessage(
        channel="test",
        bot_id=agent_id,
        external_user_id="test-user",
        text=text,
        message_id=str(uuid.uuid4()),
        session_id=session_id,
    )


class _RecordingAdapter:
    """Adapter that captures the kwargs the transport actually received."""

    def __init__(self, response):
        self.response = response
        self.dispatched: list[dict] = []

    async def get_model_info(self, model):
        return {
            "model_str": "test",
            "api_key": None,
            "base_url": None,
            "resolved_model": {"context_window_tokens": 32000},
        }

    async def complete(self, agent_model, messages, tools=None):
        self.dispatched.append({"messages": messages, "tools": tools})
        return self.response


@pytest.mark.asyncio
async def test_budget_conflict_fails_before_dispatch(db, monkeypatch, tmp_path):
    """context_window=4096 with max_tokens=8192 is a configuration error —
    the run fails with zero transport calls, not a guessed budget."""
    await _agent(db)

    from agentos.agent_service import get_active_config, save_agent

    cfg = await get_active_config(db, "cap-test")
    cfg.model = cfg.model.model_copy(update={"max_tokens": 8192})
    await save_agent(db, cfg)

    class TinyContextAdapter(_RecordingAdapter):
        async def get_model_info(self, model):
            return {
                "model_str": "test",
                "api_key": None,
                "base_url": None,
                "resolved_model": {"context_window_tokens": 4096},
            }

    adapter = TinyContextAdapter(ScriptedResponse(content="ok"))
    pipeline = Pipeline(db=db, harness=Harness(model=adapter))
    run = await pipeline.handle_inbound(
        _inbound("cap-test", "hi"), trigger="user_message", is_test=True
    )
    assert run.status == "failed"
    assert "budget" in (run.error or "").lower() or "context" in (run.error or "").lower()
    assert adapter.dispatched == []


@pytest.mark.asyncio
async def test_capture_writes_body_and_receipt_shares_id(db, monkeypatch, tmp_path):
    """A scripted end-to-end chat run records a ModelRequestCapture whose
    id IS the ModelCall.id, with redacted content and scope metadata."""
    await _agent(db)

    from agentos.services import context_capture as cc

    captured_kwargs: list[dict] = []

    class CapAdapter:
        async def get_model_info(self, m):
            return {
                "model_str": "test",
                "api_key": None,
                "base_url": None,
                "resolved_model": {"context_window_tokens": 32000},
            }

        async def complete(self, agent_model, messages, tools=None):
            captured_kwargs.append({"messages": messages, "tools": tools})
            kwargs = {
                "model": "test-model",
                "messages": messages,
                "max_tokens": 512,
                "api_key": "sk-live-DEADBEEFDEADBEEFDEADBEEF",
            }
            result, ref = await cc.capture_dispatch("chat", kwargs, self._fake_transport)
            r = ScriptedResponse(content="reply", tokens_in=3, tokens_out=2)
            r.request_capture = ref
            return r

        async def _fake_transport(self, **kw):
            captured_kwargs.append(kw)
            return object()

    pipeline = Pipeline(db=db, harness=Harness(model=CapAdapter()))
    run = await pipeline.handle_inbound(
        _inbound("cap-test", "hello"), trigger="user_message", is_test=True
    )
    assert run.status == "completed"

    calls = (await db.execute(select(ModelCall))).scalars().all()
    chat_calls = [c for c in calls if c.kind == "chat"]
    assert len(chat_calls) == 1
    call = chat_calls[0]

    caps = (await db.execute(select(ModelRequestCapture))).scalars().all()
    assert len(caps) >= 1
    cap = next(c for c in caps if c.id == call.id)
    assert cap.state in ("available", "partial")
    body = json.loads(cap.payload)
    assert "sk-live-DEADBEEF" not in cap.payload  # never persisted
    assert "sk-live" not in json.dumps(body)
    meta = json.loads(cap.capture_meta)
    assert meta["scope"]["agent_id"] == "cap-test"
    assert meta["scope"]["purpose"] == "reasoning"


@pytest.mark.asyncio
async def test_retention_age_cutoff_and_storage_cap(db, monkeypatch, tmp_path):
    """Age boundary is exact — a row at the cutoff survives, one microsecond
    older expires. Storage cap expires oldest bodies only; metadata stays."""
    import datetime as _dt

    from agentos.config import settings
    from agentos.services.context_capture import enforce_retention

    monkeypatch.setattr(settings, "context_capture_retention_days", 7)
    monkeypatch.setattr(settings, "context_capture_max_bytes", 268435456)
    monkeypatch.setattr(settings, "context_capture_max_payload_bytes", 1048576)
    monkeypatch.setattr(settings, "db_path", tmp_path / "data" / "a.db")

    frozen = _dt.datetime.now(_dt.UTC)

    class _FrozenDt(_dt.datetime):
        @classmethod
        def now(cls, tz=None):
            return frozen

    monkeypatch.setattr("agentos.services.context_capture.datetime", _FrozenDt)
    now = _FrozenDt.now(_dt.UTC)
    cutoff = now - _dt.timedelta(days=7)
    keep = ModelRequestCapture(
        id=str(uuid.uuid4()),
        payload='{"ok":1}',
        payload_bytes=8,
        state="available",
        capture_meta="{}",
        created_at=cutoff,  # exactly at cutoff → retained
    )
    old = ModelRequestCapture(
        id=str(uuid.uuid4()),
        payload='{"old":1}',
        payload_bytes=9,
        state="available",
        capture_meta="{}",
        created_at=cutoff - _dt.timedelta(microseconds=1),
    )
    db.add_all([keep, old])
    await db.commit()

    # Retention runs on its own short transaction (separate session —
    # the durable evidence must not inherit the caller's session state).
    await enforce_retention()

    import agentos.db as _dbm

    async with _dbm.async_session_factory() as check:
        rows = (
            (
                await check.execute(
                    select(ModelRequestCapture).where(ModelRequestCapture.id.in_([keep.id, old.id]))
                )
            )
            .scalars()
            .all()
        )
    fresh_keep = next(r for r in rows if r.id == keep.id)
    fresh_old = next(r for r in rows if r.id == old.id)
    assert fresh_keep.payload is not None
    assert fresh_old.payload is None
    assert fresh_old.state == "expired"
    assert fresh_old.expiry_reason == "age_limit"
    assert fresh_old.expired_at is not None


@pytest.mark.asyncio
async def test_capture_save_failure_leaves_failed_state(db, monkeypatch, tmp_path):
    """A capture-row save failure must not block the SDK call — ref records
    the failed state and the transport still runs on original kwargs."""
    from agentos.services.context_capture import capture_dispatch, capture_scope

    monkeypatch.setattr(
        "agentos.services.context_capture._persist_capture",
        AsyncMock(side_effect=RuntimeError("disk full")),
    )
    ran: list[dict] = []

    async def fake_transport(**kw):
        ran.append(kw)
        return object()

    with capture_scope(purpose="reasoning", agent_id="x"):
        result, ref = await capture_dispatch(
            "chat",
            {"model": "m", "messages": [{"role": "user", "content": "hi"}]},
            fake_transport,
        )
    assert result is not None
    assert ref.state == "failed"
    assert ref.reason == "save_failed"
    assert ran and ran[0]["model"] == "m"


@pytest.mark.asyncio
async def test_dispatch_allowlist_and_redaction(db, monkeypatch, tmp_path):
    """Auth material and unknown extras never reach the persisted body;
    secret-looking strings inside messages are scrubbed."""
    from agentos.config import settings
    from agentos.services.context_capture import capture_dispatch

    monkeypatch.setattr(settings, "db_path", tmp_path / "data" / "a.db")

    kwargs = {
        "model": "m",
        "api_key": "sk-secret-KEY-999988887777",
        "base_url": "https://internal.example.com",
        "custom_nonstandard_field": "x",
        "messages": [
            {
                "role": "user",
                "content": "my api_key=sk-live-aaaaBBBBcccc111122223333",
            },
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAA"}},
                ],
            },
        ],
    }

    async def fake_transport(**kw):
        # The transport receives the ORIGINAL unmodified kwargs — the key is
        # still present; only the persisted body is scrubbed.
        assert kw["api_key"] == "sk-secret-KEY-999988887777"
        return object()

    result, ref = await capture_dispatch("chat", kwargs, fake_transport)
    assert result is not None
    cap = await db.get(ModelRequestCapture, ref.id)
    assert cap is not None
    assert "sk-secret-KEY" not in cap.payload
    assert "sk-live-aaaa" not in cap.payload
    assert "internal.example.com" not in cap.payload
    assert "custom_nonstandard_field" not in cap.payload
    # Extras land as a count, never as raw provider-extra key names.
    assert "custom_nonstandard_field" not in cap.capture_meta
    assert json.loads(cap.capture_meta)["omitted_extras"]["count"] == 1
    # Image content marked omitted, never persisted.
    assert "_omitted" in cap.payload


@pytest.mark.asyncio
async def test_concurrent_scopes_dont_cross(db, monkeypatch, tmp_path):
    """Two concurrent dispatches in distinct scopes never share a capture —
    each ref binds its own scope + id."""
    import asyncio as _a

    from agentos.config import settings
    from agentos.services.context_capture import capture_dispatch, capture_scope

    monkeypatch.setattr(settings, "db_path", tmp_path / "data" / "a.db")

    seen: dict[str, dict] = {}

    async def transport(**kw):
        await _a.sleep(0)
        return object()

    async def go(name: str):
        with capture_scope(purpose="reasoning", agent_id=name, run_id=f"run-{name}"):
            _res, ref = await capture_dispatch(
                "chat",
                {"model": "m", "messages": [{"role": "user", "content": name}]},
                transport,
            )
            seen[name] = ref

    await _a.gather(go("alpha"), go("beta"))
    assert seen["alpha"].id != seen["beta"].id
    cap_a = await db.get(ModelRequestCapture, seen["alpha"].id)
    cap_b = await db.get(ModelRequestCapture, seen["beta"].id)
    assert json.loads(cap_a.capture_meta)["scope"]["agent_id"] == "alpha"
    assert json.loads(cap_b.capture_meta)["scope"]["agent_id"] == "beta"


@pytest.mark.asyncio
async def test_retention_storage_cap_expires_oldest_first(db, monkeypatch, tmp_path):
    """Total-byte cap retires oldest (created_at, id) bodies only — metadata
    and newer bodies untouched."""
    import datetime as _dt

    from agentos.config import settings
    from agentos.services.context_capture import enforce_retention

    monkeypatch.setattr(settings, "context_capture_retention_days", 365)
    monkeypatch.setattr(settings, "context_capture_max_bytes", 20)

    now = _dt.datetime.now(_dt.UTC)
    rows = [
        ModelRequestCapture(
            id=str(uuid.uuid4()),
            payload='{"a":1}',
            payload_bytes=8,
            state="available",
            capture_meta="{}",
            created_at=now - _dt.timedelta(minutes=10),
        ),
        ModelRequestCapture(
            id=str(uuid.uuid4()),
            payload='{"b":2}',
            payload_bytes=8,
            state="available",
            capture_meta="{}",
            created_at=now - _dt.timedelta(minutes=9),
        ),
        ModelRequestCapture(
            id=str(uuid.uuid4()),
            payload='{"c":3}',
            payload_bytes=8,
            state="available",
            capture_meta="{}",
            created_at=now - _dt.timedelta(minutes=8),
        ),
    ]
    db.add_all(rows)
    await db.commit()

    await enforce_retention()

    import agentos.db as _dbm

    async with _dbm.async_session_factory() as check:
        out = (
            (
                await check.execute(
                    select(ModelRequestCapture).order_by(ModelRequestCapture.created_at)
                )
            )
            .scalars()
            .all()
        )
    # 24 > 20 → oldest (8 bytes) expires; remaining 16 ≤ 20.
    assert out[0].payload is None and out[0].expiry_reason == "storage_limit"
    assert out[1].payload is not None and out[2].payload is not None
    # Metadata is preserved — expiry never deletes the row.
    assert out[0].capture_meta == "{}"
    assert out[0].expired_at is not None


def _app_client(db):
    """Authenticated ASGI client bound to the test session."""
    import httpx

    from agentos.auth import require_operator
    from agentos.db import get_db
    from agentos.main import app
    from agentos.models.operator import Operator

    async def override_db():
        yield db

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[require_operator] = lambda: Operator(
        id="op", username="t", password_hash="", must_change_password=False
    )
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")
    return client, app


@pytest.mark.asyncio
async def test_context_inspection_states(db, monkeypatch, tmp_path):
    """GET /api/model-calls/{id}/context — available/expired/not_recorded/
    unknown-id states with the real authenticated route."""
    import datetime as _dt

    from agentos.config import settings

    monkeypatch.setattr(settings, "context_capture_retention_days", 365)
    monkeypatch.setattr(settings, "context_capture_max_bytes", 268435456)
    monkeypatch.setattr(settings, "db_path", tmp_path / "data" / "a.db")

    now = _dt.datetime.now(_dt.UTC)
    call_ok = ModelCall(
        id=str(uuid.uuid4()),
        kind="chat",
        status="ok",
    )
    call_gone = ModelCall(id=str(uuid.uuid4()), kind="chat", status="ok")
    call_na = ModelCall(id=str(uuid.uuid4()), kind="embedding", status="ok")
    db.add_all(
        [
            call_ok,
            call_gone,
            call_na,
            ModelRequestCapture(
                id=call_ok.id,
                payload='{"rendered_context":{"messages":[]},"dispatch_input":{"model":"m"}}',
                payload_bytes=64,
                state="available",
                capture_meta='{"surface":"chat","scope":{"agent_id":"cap-test"}}',
                created_at=now,
            ),
        ]
    )
    await db.commit()

    client, app = _app_client(db)
    try:
        ok = await client.get(f"/api/model-calls/{call_ok.id}/context")
        assert ok.status_code == 200
        assert ok.json()["state"] == "available"
        assert ok.json()["payload"]["dispatch_input"]["model"] == "m"
        assert ok.json()["metadata"]["agent_id"] == "cap-test"

        missing = await client.get(f"/api/model-calls/{call_gone.id}/context")
        assert missing.status_code == 200
        assert missing.json()["state"] == "not_recorded"

        na = await client.get(f"/api/model-calls/{call_na.id}/context")
        assert na.json()["state"] == "not_applicable"

        unknown = await client.get("/api/model-calls/nonexistent/context")
        assert unknown.status_code == 404
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_context_policy_get_put_pinned(db, monkeypatch, tmp_path):
    """Policy GET reflects settings; PUT persists atomically; env-pinned
    keys reject with 409."""

    from agentos.config import settings

    monkeypatch.setattr(settings, "db_path", tmp_path / "data" / "a.db")
    monkeypatch.setattr(settings, "context_capture_retention_days", 7)

    client, app = _app_client(db)
    try:
        got = await client.get("/api/context-capture-policy")
        assert got.status_code == 200
        assert got.json()["retention_days"] == 7
        assert got.json()["pinned"]["retention_days"] is False

        put = await client.put(
            "/api/context-capture-policy",
            json={"retention_days": 14, "max_bytes": 1024, "max_payload_bytes": 512},
        )
        assert put.status_code == 200
        assert settings.context_capture_retention_days == 14
        # Overlay persisted through app-settings.json.
        overlay = json.loads((settings.db_path.parent / "app-settings.json").read_text())
        assert overlay["context_capture_retention_days"] == 14

        # Env-pinned keys reject.
        monkeypatch.setenv("AGENTOS_CONTEXT_CAPTURE_RETENTION_DAYS", "30")
        pinned_put = await client.put(
            "/api/context-capture-policy",
            json={"retention_days": 30, "max_bytes": 1024, "max_payload_bytes": 512},
        )
        assert pinned_put.status_code == 409
    finally:
        app.dependency_overrides.clear()
        monkeypatch.delenv("AGENTOS_CONTEXT_CAPTURE_RETENTION_DAYS", raising=False)


@pytest.mark.asyncio
async def test_chat_rejection_falls_back_with_two_captures(db, monkeypatch, tmp_path):
    """Chat-API rejection → Responses fallback produces TWO capture rows +
    two ledger entries on the same logical dispatch — one failed, one ok."""
    from agentos.config import settings
    from agentos.config_schema import ModelConfig
    from agentos.harness.litellm_adapter import LiteLLMAdapter
    from agentos.providers.litellm_transport import LiteLLMTransport

    monkeypatch.setattr(settings, "db_path", tmp_path / "data" / "a.db")

    class RejectChatTransport(LiteLLMTransport):
        async def completion(self, **kw):
            raise RuntimeError("model requires /v1/responses")

        async def responses(self, **kw):
            # Mimic a real Responses object.
            class _Block:
                type = "output_text"
                text = "hi"

            class _Item:
                type = "message"
                content = [_Block()]

            class _Resp:
                output = [_Item()]
                usage = None

            return _Resp()

    adapter = LiteLLMAdapter(db=db, transport=RejectChatTransport())

    # Bypass the real rate snapshot (provider lookup) — only the dispatch
    # boundary matters here.
    async def _noop_snapshot(model, provider):
        return None

    monkeypatch.setattr(adapter, "_capture_rates", _noop_snapshot)
    provider = {
        "api_key": None,
        "base_url": None,
        "org_id": None,
        "extra_params": {},
        "type": "custom",
    }
    monkeypatch.setattr(adapter, "_load_provider", AsyncMock(return_value=provider))
    model = ModelConfig(provider_id="p", name="m")

    resp = await adapter.complete(
        agent_model=model,
        messages=[{"role": "user", "content": "hi"}],
        tools=None,
    )
    assert resp.content == "hi"
    assert resp.request_capture is not None

    # The caller's final ledger writer upserts on the same capture id —
    # simulate the harness receipt for the successful attempt.
    from agentos.services.model_ledger import record_system_call

    await record_system_call(
        kind="chat",
        purpose="reasoning",
        model_name="m",
        response=resp,
    )

    caps = (await db.execute(select(ModelRequestCapture))).scalars().all()
    assert len(caps) == 2
    # One failed chat attempt + one successful Responses call — two
    # capture rows AND two ledger rows, paired 1:1 by shared id, same turn.
    calls = (await db.execute(select(ModelCall).where(ModelCall.kind == "chat"))).scalars().all()
    assert len(calls) == 2
    capture_ids = {c.id for c in caps}
    call_ids = {c.id for c in calls}
    assert capture_ids == call_ids
    statuses = sorted(c.status for c in calls)
    assert statuses == ["error", "ok"]
    turns = {c.turn for c in calls}
    assert len(turns) == 1


@pytest.mark.asyncio
async def test_streaming_consumption_error_retains_ref(db, monkeypatch, tmp_path):
    """A stream that fails mid-consumption keeps the SAME capture reference
    that was allocated before the transport call."""
    from agentos.config import settings
    from agentos.services.context_capture import capture_dispatch, capture_scope

    monkeypatch.setattr(settings, "db_path", tmp_path / "data" / "a.db")

    async def bad_stream_factory(**kw):
        async def _gen():
            yield "chunk1"
            raise RuntimeError("mid-stream disconnect")

        return _gen()

    with capture_scope(purpose="reasoning", agent_id="cap-test"):
        try:
            stream, ref = await capture_dispatch("chat_stream", {"model": "m"}, bad_stream_factory)
        except RuntimeError:
            raise AssertionError("transport call itself must not fail")
        with pytest.raises(RuntimeError):
            async for _ in stream:
                pass
    # Stream consumption error happened outside capture_dispatch — the ref
    # still exists from before the transport returned.
    assert ref.id is not None
    assert ref.surface == "chat_stream"


@pytest.mark.asyncio
async def test_read_projection_strips_legacy_canaries(db, monkeypatch, tmp_path):
    """A legacy capture row seeded with raw secrets is never served to the
    operator — the read path re-applies the scrub."""
    from agentos.config import settings

    monkeypatch.setattr(settings, "context_capture_retention_days", 365)
    monkeypatch.setattr(settings, "db_path", tmp_path / "data" / "a.db")

    call = ModelCall(id=str(uuid.uuid4()), kind="chat", status="ok")
    db.add(call)
    db.add(
        ModelRequestCapture(
            id=call.id,
            payload=json.dumps(
                {
                    "rendered_context": {"messages": [], "tools": []},
                    "dispatch_input": {
                        "model": "m",
                        "api_key": "sk-canary-DEADBEEF",
                        "messages": [{"role": "user", "content": "token=abc123456789012345678"}],
                    },
                }
            ),
            payload_bytes=200,
            state="available",
            capture_meta='{"surface":"chat","scope":{"secret_field":"x"}}',
        )
    )
    await db.commit()

    client, app = _app_client(db)
    try:
        resp = await client.get(f"/api/model-calls/{call.id}/context")
        assert resp.status_code == 200
        body = resp.json()
        serialized = json.dumps(body)
        assert "sk-canary-DEADBEEF" not in serialized
        assert "abc123456789012345678" not in serialized
        assert body["metadata"].get("secret_field") is None
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_unauthenticated_context_401(db, monkeypatch, tmp_path):
    """The context endpoint is operator-only — no anonymous read."""
    import httpx

    from agentos.db import get_db
    from agentos.main import app

    monkeypatch.setattr(
        __import__("agentos.config", fromlist=["settings"]).settings,
        "db_path",
        tmp_path / "data" / "a.db",
    )

    async def override_db():
        yield db

    app.dependency_overrides[get_db] = override_db
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://t"
        ) as c:
            resp = await c.get("/api/model-calls/anything/context")
        assert resp.status_code == 401
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_context_api_malformed_meta_and_nonstring_surface(db, monkeypatch, tmp_path):
    """Malformed capture_meta / non-string surface-reason → honest failed
    or not_recorded, never a 500 and never raw meta canaries."""
    from agentos.config import settings

    monkeypatch.setattr(settings, "db_path", tmp_path / "data" / "a.db")
    call = ModelCall(id=str(uuid.uuid4()), kind="chat", status="ok")
    db.add_all(
        [
            call,
            ModelRequestCapture(
                id=call.id,
                payload=None,
                payload_bytes=0,
                state="available",  # lying state — no body
                capture_meta="{not-json at all",
            ),
        ]
    )
    await db.commit()

    client, app = _app_client(db)
    try:
        resp = await client.get(f"/api/model-calls/{call.id}/context")
        assert resp.status_code == 200
        body = resp.json()
        assert body["state"] == "failed"
        assert body["reason"] in ("malformed_body", "malformed_metadata", "no_body")
        assert body["metadata"] == {}
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_context_policy_unchanged_pinned_allowed(db, monkeypatch, tmp_path):
    """PUT with an unchanged pinned field + a changed unpinned field is
    accepted — only CHANGED pinned keys reject."""
    from agentos.config import settings

    monkeypatch.setattr(settings, "db_path", tmp_path / "data" / "a.db")
    monkeypatch.setattr(settings, "context_capture_retention_days", 7)
    monkeypatch.setenv("AGENTOS_CONTEXT_CAPTURE_RETENTION_DAYS", "7")

    client, app = _app_client(db)
    try:
        ok = await client.put(
            "/api/context-capture-policy",
            json={
                "retention_days": 7,  # pinned but unchanged
                "max_bytes": 999999,
                "max_payload_bytes": 512,
            },
        )
        assert ok.status_code == 200
        # Changing the pinned field rejects.
        bad = await client.put(
            "/api/context-capture-policy",
            json={
                "retention_days": 30,
                "max_bytes": 999999,
                "max_payload_bytes": 512,
            },
        )
        assert bad.status_code == 409
    finally:
        app.dependency_overrides.clear()
        monkeypatch.delenv("AGENTOS_CONTEXT_CAPTURE_RETENTION_DAYS", raising=False)


@pytest.mark.asyncio
async def test_context_api_malformed_meta_valid_body_still_fails(db, monkeypatch, tmp_path):
    """A corrupt capture_meta with a VALID payload must still surface
    failed/malformed_metadata — the body is never trusted under bad meta."""
    from agentos.config import settings

    monkeypatch.setattr(settings, "db_path", tmp_path / "data" / "a.db")
    call = ModelCall(id=str(uuid.uuid4()), kind="chat", status="ok")
    db.add_all(
        [
            call,
            ModelRequestCapture(
                id=call.id,
                payload='{"rendered_context":{"messages":[{"role":"user","content":"hi"}]},"dispatch_input":{"model":"m"}}',
                payload_bytes=120,
                state="available",
                capture_meta='["not", "an", "object"]',
            ),
        ]
    )
    await db.commit()

    client, app = _app_client(db)
    try:
        resp = await client.get(f"/api/model-calls/{call.id}/context")
        assert resp.status_code == 200
        body = resp.json()
        assert body["state"] == "failed"
        assert body["reason"] == "malformed_metadata"
        assert body["payload"] is None
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_context_api_nonstring_surface_reason_no_500(db, monkeypatch, tmp_path):
    """Dict/list surface+reason in meta → safe None, never a 500."""
    from agentos.config import settings

    monkeypatch.setattr(settings, "db_path", tmp_path / "data" / "a.db")
    call = ModelCall(id=str(uuid.uuid4()), kind="chat", status="ok")
    db.add_all(
        [
            call,
            ModelRequestCapture(
                id=call.id,
                payload=None,
                payload_bytes=0,
                state="expired",
                expired_at=None,
                expiry_reason="age_limit",
                capture_meta='{"surface": ["x"], "reason": {"canary": "y"}, "scope": {"agent_id": "a"}}',
            ),
        ]
    )
    await db.commit()
    client, app = _app_client(db)
    try:
        resp = await client.get(f"/api/model-calls/{call.id}/context")
        assert resp.status_code == 200
        body = resp.json()
        assert body["surface"] is None
        assert body["reason"] == "age_limit"
    finally:
        app.dependency_overrides.clear()
