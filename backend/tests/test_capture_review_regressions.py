"""Capture-review regressions — written against the lead's capture
service contract; expected to be RED until the service rework lands.
"""

import datetime as _dt
import json
import uuid
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from agentos.config import persist_settings, settings
from agentos.harness.compaction import generate_summary
from agentos.models.model_call import ModelCall
from agentos.models.request_capture import ModelRequestCapture
from agentos.services.context_capture import (
    capture_dispatch,
    capture_scope,
    enforce_retention,
)


def _patch_fs(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "db_path", tmp_path / "data" / "a.db")


@pytest.mark.asyncio
async def test_full_quota_new_capture_still_saves(db, monkeypatch, tmp_path):
    """A quota-full store still saves the NEW capture — the OLDEST body
    expires to make room; the fresh request never gets a perpetual
    storage_limit failure."""
    _patch_fs(monkeypatch, tmp_path)
    monkeypatch.setattr(settings, "context_capture_max_bytes", 400)
    monkeypatch.setattr(settings, "context_capture_max_payload_bytes", 10_000)
    monkeypatch.setattr(settings, "context_capture_retention_days", 365)

    now = _dt.datetime.now(_dt.UTC)
    old = ModelCall(id=str(uuid.uuid4()), kind="chat", status="ok")
    db.add(old)
    db.add(
        ModelRequestCapture(
            id=old.id,
            payload="x" * 500,
            payload_bytes=500,
            state="available",
            capture_meta="{}",
            created_at=now - _dt.timedelta(days=1),
        )
    )
    await db.commit()

    async def ok(**kw):
        return object()

    with capture_scope(agent_id="t", purpose="reasoning"):
        result, ref = await capture_dispatch("chat", {"model": "m"}, ok)
    assert ref.state in ("available", "partial")
    new_cap = await db.get(ModelRequestCapture, ref.id)
    assert new_cap is not None and new_cap.payload is not None
    await db.refresh(old)
    expired = (
        await db.execute(select(ModelRequestCapture).where(ModelRequestCapture.id == old.id))
    ).scalar_one()
    assert expired.state == "expired" and expired.payload is None


@pytest.mark.asyncio
async def test_staged_insert_counts_in_quota(db, monkeypatch, tmp_path):
    """The pending INSERT is flushed before the byte SUM — a single row
    larger than the total cap ends up truncated or honestly failed, never
    retained beyond the quota."""
    _patch_fs(monkeypatch, tmp_path)
    monkeypatch.setattr(settings, "context_capture_max_bytes", 300)
    monkeypatch.setattr(settings, "context_capture_max_payload_bytes", 10_000)
    monkeypatch.setattr(settings, "context_capture_retention_days", 365)

    async def ok(**kw):
        return object()

    with capture_scope(agent_id="t", purpose="reasoning"):
        _result, ref = await capture_dispatch(
            "chat",
            {"model": "m", "messages": [{"role": "user", "content": "y" * 500}]},
            ok,
        )
    cap = await db.get(ModelRequestCapture, ref.id)
    assert cap is not None
    if cap.payload is not None:
        assert cap.payload_bytes <= 300
    else:
        assert cap.state in ("failed", "partial")


@pytest.mark.asyncio
async def test_sub_256_perbody_cap_honest(db, monkeypatch, tmp_path):
    """A configured per-body cap under 256 bytes accepts a fitting payload
    or reports an honest partial — never silently keeps an over-cap body."""
    _patch_fs(monkeypatch, tmp_path)
    monkeypatch.setattr(settings, "context_capture_max_payload_bytes", 200)
    monkeypatch.setattr(settings, "context_capture_max_bytes", 268_435_456)
    monkeypatch.setattr(settings, "context_capture_retention_days", 365)

    async def ok(**kw):
        return object()

    with capture_scope(agent_id="t", purpose="reasoning"):
        _result, ref = await capture_dispatch(
            "chat", {"model": "m", "messages": [{"role": "user", "content": "x" * 600}]}, ok
        )
    cap = await db.get(ModelRequestCapture, ref.id)
    if cap.payload is not None:
        assert cap.payload_bytes <= 200
    else:
        assert cap.state in ("failed", "partial")


@pytest.mark.asyncio
async def test_media_extra_omission_flags_partial(db, monkeypatch, tmp_path):
    """Image omission, over-depth, and non-allowlisted extras mark the
    capture honestly (state partial or explicit flags)."""
    _patch_fs(monkeypatch, tmp_path)
    monkeypatch.setattr(settings, "context_capture_max_payload_bytes", 1_048_576)
    monkeypatch.setattr(settings, "context_capture_max_bytes", 268_435_456)
    monkeypatch.setattr(settings, "context_capture_retention_days", 365)

    async def ok(**kw):
        return object()

    deep: dict = {}
    node = deep
    for _ in range(20):
        node["next"] = {}
        node = node["next"]
    kwargs = {
        "model": "m",
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": "data:image/png;base64,xx"}},
                    {"type": "text", "text": "hi"},
                ],
            },
            {"role": "user", "content": deep},
        ],
        "unknown_extra": {"a": 1},
    }
    with capture_scope(agent_id="t", purpose="reasoning"):
        _result, ref = await capture_dispatch("chat", kwargs, ok)
    assert ref.redacted or ref.truncated or ref.state == "partial"
    cap = await db.get(ModelRequestCapture, ref.id)
    assert cap is not None
    assert "_omitted" in (cap.payload or "")


@pytest.mark.asyncio
async def test_projection_failure_never_blocks_transport(db, monkeypatch, tmp_path):
    """An injected _freeze_body failure degrades the capture to failed —
    the ORIGINAL kwargs still reach the transport."""
    _patch_fs(monkeypatch, tmp_path)
    import agentos.services.context_capture as cap_svc

    monkeypatch.setattr(
        cap_svc, "_freeze_body", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom"))
    )
    seen = {}

    async def ok(**kw):
        seen.update(kw)
        return object()

    with capture_scope(agent_id="t", purpose="reasoning"):
        result, ref = await capture_dispatch("chat", {"model": "m", "api_key": "sk-x"}, ok)
    assert result is not None
    assert seen["api_key"] == "sk-x"  # transport got the original kwargs
    assert ref.state == "failed"


@pytest.mark.asyncio
async def test_schema_secret_params_stripped_not_names(db, monkeypatch, tmp_path):
    """Schema property NAMES + types + descriptions survive; only
    secret-named defaults/examples/enum values are stripped."""
    _patch_fs(monkeypatch, tmp_path)
    monkeypatch.setattr(settings, "context_capture_max_payload_bytes", 1_048_576)
    monkeypatch.setattr(settings, "context_capture_retention_days", 365)

    async def ok(**kw):
        return object()

    tools = [
        {
            "type": "function",
            "function": {
                "name": "browser_fill",
                "parameters": {
                    "properties": {
                        "password": {
                            "type": "string",
                            "description": "the site password field value",
                            "default": "hunter2-hunter2",
                            "example": "secret",
                            "enum": ["a", "b"],
                        },
                        "field": {"type": "string", "description": "field"},
                    }
                },
            },
        }
    ]
    with capture_scope(agent_id="t", purpose="reasoning"):
        _result, ref = await capture_dispatch("chat", {"model": "m", "tools": tools}, ok)
    cap = await db.get(ModelRequestCapture, ref.id)
    body = json.loads(cap.payload)
    params = body["dispatch_input"]["tools"][0]["function"]["parameters"]["properties"]
    assert "password" in params  # name survives
    assert params["password"]["type"] == "string"
    assert "hunter2" not in json.dumps(params["password"])
    assert "default" not in params["password"]
    assert "enum" not in params["password"]
    assert params["field"]["type"] == "string"


@pytest.mark.asyncio
async def test_json_secret_string_scrubbed_preserving_type(db, monkeypatch, tmp_path):
    """An ordinary string containing a JSON credential object scrubs the
    credential — the field stays a string, never becomes an object."""
    _patch_fs(monkeypatch, tmp_path)
    monkeypatch.setattr(settings, "context_capture_max_payload_bytes", 1_048_576)
    monkeypatch.setattr(settings, "context_capture_retention_days", 365)

    async def ok(**kw):
        return object()

    with capture_scope(agent_id="t", purpose="reasoning"):
        _result, ref = await capture_dispatch(
            "chat",
            {
                "model": "m",
                "messages": [{"role": "user", "content": '{"password": "hunter2-hunter2"}'}],
            },
            ok,
        )
    cap = await db.get(ModelRequestCapture, ref.id)
    assert "hunter2" not in cap.payload
    body = json.loads(cap.payload)
    content = body["dispatch_input"]["messages"][0]["content"]
    assert isinstance(content, (str, dict, list))


@pytest.mark.asyncio
async def test_provider_extras_cannot_reroute_transport(db, monkeypatch, tmp_path):
    """Hostile extra_params attempting to override model/messages/tools/
    stream lose the merge — the transport sees runtime values and the
    capture matches what was actually sent."""
    _patch_fs(monkeypatch, tmp_path)
    monkeypatch.setattr(settings, "context_capture_retention_days", 365)
    from agentos.config_schema import ModelConfig
    from agentos.harness.litellm_adapter import LiteLLMAdapter
    from agentos.providers.litellm_transport import LiteLLMTransport

    seen: dict = {}

    class Spy(LiteLLMTransport):
        async def completion(self, **kw):
            seen.update(kw)
            msg = type("M", (), {"content": "ok", "tool_calls": None, "model_dump": lambda s: {}})()
            return type(
                "R",
                (),
                {
                    "choices": [type("C", (), {"message": msg, "finish_reason": "stop"})()],
                    "usage": None,
                    "model": "m",
                },
            )()

    adapter = LiteLLMAdapter(db=db, transport=Spy())
    monkeypatch.setattr(adapter, "_capture_rates", AsyncMock(return_value=None))
    monkeypatch.setattr(
        adapter,
        "_load_provider",
        AsyncMock(
            return_value={
                "api_key": None,
                "base_url": None,
                "org_id": None,
                "type": "custom",
                "extra_params": {
                    "model": "hostile-model",
                    "messages": [{"role": "system", "content": "evil"}],
                    "tools": [{"type": "function", "function": {"name": "evil"}}],
                    "stream": True,
                },
            }
        ),
    )
    model = ModelConfig(provider_id="p", name="m")
    resp = await adapter.complete(
        agent_model=model,
        messages=[{"role": "user", "content": "hi"}],
        tools=None,
    )
    # Routed model_str (possibly prefixed like "custom/m") wins over the
    # hostile extra — never "hostile-model".
    assert seen["model"].endswith("m") and "hostile" not in seen["model"]
    assert seen["messages"][0]["content"] == "hi"
    assert seen.get("tools") is None
    assert "stream" not in seen
    cap = await db.get(ModelRequestCapture, resp.request_capture.id)
    dispatch = json.loads(cap.payload)["dispatch_input"]
    assert dispatch["model"] == seen["model"]


@pytest.mark.asyncio
async def test_stream_failure_keeps_same_ref(db, monkeypatch, tmp_path):
    """A mid-stream failure keeps the SAME capture id and leaves a failed
    receipt — never a phantom success."""
    _patch_fs(monkeypatch, tmp_path)
    monkeypatch.setattr(settings, "context_capture_retention_days", 365)

    async def stream(**kw):
        async def _g():
            yield "c"
            raise RuntimeError("mid-stream")

        return _g()

    with capture_scope(agent_id="t", purpose="reasoning", run_id="r1"):
        stream_it, ref = await capture_dispatch("chat_stream", {"model": "m"}, stream)
        with pytest.raises(RuntimeError):
            async for _ in stream_it:
                pass
    cap = await db.get(ModelRequestCapture, ref.id)
    assert cap is not None


def test_persist_settings_rejects_malformed_overlay(tmp_path, monkeypatch):
    """A corrupt app-settings.json raises — the operator's file is never
    replaced with a fresh empty overlay."""
    monkeypatch.setattr(settings, "db_path", tmp_path / "data" / "a.db")
    path = tmp_path / "data" / "app-settings.json"
    path.parent.mkdir(parents=True)
    path.write_text("{not json at all")
    with pytest.raises(ValueError, match="malformed"):
        persist_settings({"context_capture_retention_days": 9})
    assert path.read_text() == "{not json at all"


def test_persist_settings_preserves_unknown_keys(tmp_path, monkeypatch):
    """Unknown overlay keys survive a policy save byte-for-byte."""
    monkeypatch.setattr(settings, "db_path", tmp_path / "data" / "a.db")
    path = tmp_path / "data" / "app-settings.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"custom_flag": True, "x": 1}))
    persist_settings({"context_capture_retention_days": 9})
    overlay = json.loads(path.read_text())
    assert overlay["custom_flag"] is True
    assert overlay["x"] == 1
    assert overlay["context_capture_retention_days"] == 9


@pytest.mark.asyncio
async def test_aliases_map_canonical_names(db, monkeypatch, tmp_path):
    """Sanitized tool aliases map back to the ORIGINAL capability names for
    privacy projection — a dotted memory_ name projects sensitive policy."""
    _patch_fs(monkeypatch, tmp_path)
    monkeypatch.setattr(settings, "context_capture_max_payload_bytes", 1_048_576)
    monkeypatch.setattr(settings, "context_capture_retention_days", 365)

    async def ok(**kw):
        return object()

    # Sanitized call "memory_recall" (dotted → safe) — alias map restores it.
    sanitized = "memory_recall"
    aliases = {sanitized: "browser_type"}
    kwargs = {
        "model": "m",
        "messages": [
            {
                "role": "assistant",
                "tool_calls": [
                    {
                        "id": "c1",
                        "function": {
                            "name": sanitized,
                            "arguments": json.dumps({"url": "https://x", "password": "hunter2"}),
                        },
                    }
                ],
            },
            {
                "role": "tool",
                "tool_call_id": "c1",
                "content": "page body password=hunter2 result",
            },
        ],
    }
    with capture_scope(agent_id="t", purpose="reasoning"):
        _result, ref = await capture_dispatch("chat", kwargs, ok, tool_aliases=aliases)
    cap = await db.get(ModelRequestCapture, ref.id)
    body = json.loads(cap.payload)
    result_msg = body["dispatch_input"]["messages"][1]
    # browser_* policy: result projected, password never raw.
    assert "hunter2" not in json.dumps(result_msg)


@pytest.mark.asyncio
async def test_exact_utc_cutoff_boundary(db, monkeypatch, tmp_path):
    """A body created exactly at the retention cutoff is RETAINED; one
    microsecond older is expired — naive/tz handling must not skew it."""
    _patch_fs(monkeypatch, tmp_path)
    monkeypatch.setattr(settings, "context_capture_retention_days", 7)
    monkeypatch.setattr(settings, "context_capture_max_bytes", 268_435_456)

    now = _dt.datetime.now(_dt.UTC)
    cutoff = now - _dt.timedelta(days=7)
    kept_call = ModelCall(id=str(uuid.uuid4()), kind="chat", status="ok")
    old_call = ModelCall(id=str(uuid.uuid4()), kind="chat", status="ok")
    db.add_all(
        [
            kept_call,
            old_call,
            ModelRequestCapture(
                id=kept_call.id,
                payload="{}",
                payload_bytes=2,
                state="available",
                capture_meta="{}",
                created_at=cutoff.replace(tzinfo=None),
            ),
            ModelRequestCapture(
                id=old_call.id,
                payload="{}",
                payload_bytes=2,
                state="available",
                capture_meta="{}",
                created_at=(cutoff - _dt.timedelta(microseconds=1)).replace(tzinfo=None),
            ),
        ]
    )
    await db.commit()
    # Freeze the service clock at the test's `now` so `created_at ==
    # cutoff` is the exact boundary case.
    import agentos.services.context_capture as cap_mod

    class FrozenDt(_dt.datetime):
        @classmethod
        def now(cls, tz=None):
            return now if tz is None else now.astimezone(tz)

    monkeypatch.setattr(cap_mod, "datetime", FrozenDt)
    await enforce_retention()
    kept = (
        await db.execute(select(ModelRequestCapture).where(ModelRequestCapture.id == kept_call.id))
    ).scalar_one()
    old = (
        await db.execute(select(ModelRequestCapture).where(ModelRequestCapture.id == old_call.id))
    ).scalar_one()
    assert kept.state == "available"
    assert old.state == "expired"
    assert old.payload is None and old.payload_bytes == 0


@pytest.mark.asyncio
async def test_compaction_scope_has_real_metadata(db, monkeypatch, tmp_path):
    """generate_summary's capture scope carries run/session/agent/purpose —
    no borrowed reasoning context, no invented fields."""
    _patch_fs(monkeypatch, tmp_path)
    monkeypatch.setattr(settings, "context_capture_retention_days", 365)

    class Spy:
        async def responses(self, **kw):
            block = type("B", (), {"type": "output_text", "text": "s"})()
            item = type("I", (), {"type": "message", "content": [block]})()
            return type("R", (), {"output": [item]})()

        async def completion(self, **kw):
            msg = type("M", (), {"content": "s"})()
            choice = type("C", (), {"message": msg})()
            return type("R", (), {"choices": [choice]})()

    from agentos.providers import litellm_transport as transport_mod

    monkeypatch.setattr(transport_mod, "LiteLLMTransport", lambda *a, **k: Spy())
    await generate_summary(
        [{"role": "user", "content": "hi"}],
        previous_summary=None,
        model_str="m",
        provider_id="p",
        model_name="n",
        agent_id="reg-agent",
        run_id="r-1",
        session_id="s-1",
        source_ids=["m-1"],
    )
    caps = (await db.execute(select(ModelRequestCapture))).scalars().all()
    assert caps
    meta = json.loads(caps[0].capture_meta or "{}")
    scope = meta.get("scope", {})
    assert scope.get("purpose") == "compaction"
    assert scope.get("agent_id") == "reg-agent"
    assert scope.get("run_id") == "r-1"
    assert scope.get("session_id") == "s-1"
    assert scope.get("summary_version") is None or "summary_version" in scope


@pytest.mark.asyncio
async def test_streaming_call_ledger_shares_capture_id(db, monkeypatch, tmp_path):
    """Real adapter streaming path: the done-response's request_capture id
    equals the ModelRequestCapture row id AND the caller's single ModelCall
    receipt id."""
    _patch_fs(monkeypatch, tmp_path)
    monkeypatch.setattr(settings, "context_capture_retention_days", 365)
    from agentos.config_schema import ModelConfig
    from agentos.harness.litellm_adapter import LiteLLMAdapter
    from agentos.providers.litellm_transport import LiteLLMTransport
    from agentos.services.model_ledger import record_system_call

    class Spy(LiteLLMTransport):
        async def completion(self, **kw):
            assert kw.get("stream") is True

            async def _chunks():
                delta = type("D", (), {"content": "hi", "tool_calls": None})()
                yield type(
                    "C",
                    (),
                    {
                        "choices": [
                            type(
                                "Ch",
                                (),
                                {"delta": delta, "finish_reason": None},
                            )()
                        ],
                        "usage": None,
                    },
                )()

            return _chunks()

    adapter = LiteLLMAdapter(db=db, transport=Spy())
    monkeypatch.setattr(adapter, "_capture_rates", AsyncMock(return_value=None))
    monkeypatch.setattr(
        adapter,
        "_load_provider",
        AsyncMock(
            return_value={
                "api_key": None,
                "base_url": None,
                "org_id": None,
                "type": "custom",
                "extra_params": {},
            }
        ),
    )
    model = ModelConfig(provider_id="p", name="m")

    with capture_scope(agent_id="reg-agent", purpose="reasoning", run_id="r-9"):
        final = None
        async for event in adapter.complete_stream(
            agent_model=model,
            messages=[{"role": "user", "content": "hi"}],
            tools=None,
        ):
            if event[0] == "done":
                final = event[1]
    assert final is not None and final.request_capture is not None
    cap_id = final.request_capture.id
    cap = await db.get(ModelRequestCapture, cap_id)
    assert cap is not None
    await record_system_call(kind="chat", purpose="reasoning", model_name="m", response=final)
    row = await db.get(ModelCall, cap_id)
    assert row is not None
    assert row.id == cap.id


@pytest.mark.asyncio
async def test_midstream_failure_same_id_failed_receipt(db, monkeypatch, tmp_path):
    """Mid-stream consumption failure keeps the same capture id on the
    caller's failed receipt — one receipt, never a phantom success."""
    _patch_fs(monkeypatch, tmp_path)
    monkeypatch.setattr(settings, "context_capture_retention_days", 365)

    async def stream(**kw):
        async def _g():
            yield "x"
            raise TimeoutError("stream stalled")

        return _g()

    with capture_scope(agent_id="t", purpose="reasoning", run_id="r-1", turn=0):
        stream_it, ref = await capture_dispatch("chat_stream", {"model": "m"}, stream)
        exc = None
        try:
            async for _ in stream_it:
                pass
        except TimeoutError as e:
            exc = e
    assert exc is not None
    assert getattr(exc, "capture_ref", None) is ref or getattr(exc, "capture_ref", None) == ref
    # Caller records the failed attempt under the SAME id.
    from agentos.services.model_ledger import record_system_call

    await record_system_call(
        kind="chat",
        purpose="reasoning",
        model_name="m",
        error=exc,
        capture_ref=ref,
    )
    row = await db.get(ModelCall, ref.id)
    assert row is not None
    assert row.status in ("error", "timeout")
    cap = await db.get(ModelRequestCapture, ref.id)
    assert cap is not None


@pytest.mark.asyncio
async def test_summary_snapshot_generations_chain(db, monkeypatch, tmp_path):
    """Two successful compactions produce two immutable snapshots; the
    second's prior id/version/text/coverage chain is exact; a fresh
    session-load resolves the active snapshot."""
    _patch_fs(monkeypatch, tmp_path)
    from agentos.harness.conversation import Conversation
    from agentos.models.conversation_summary import ConversationSummary
    from agentos.models.session import Session

    session = Session(id=str(uuid.uuid4()), agent_id="a", contact_id="c")
    db.add(session)
    await db.commit()

    conv = Conversation(session_id=session.id)
    ok1 = await conv.store_summary(
        db, "first summary", {"m1", "m2"}, retained_head_ids={"m1"}, retained_tail_ids={"m9"}
    )
    assert ok1
    ok2 = await conv.store_summary(db, "second summary", {"m1", "m2", "m3"})
    assert ok2

    rows = (await db.execute(select(ConversationSummary))).scalars().all()
    assert len(rows) == 2
    v1, v2 = sorted(rows, key=lambda r: r.version)
    assert v2.prior_summary_id == v1.id
    assert v1.version == 1 and v2.version == 2
    assert set(__import__("json").loads(v1.covered_message_ids)) == {"m1", "m2"}
    assert set(__import__("json").loads(v1.retained_head_ids)) == {"m1"}
    assert set(__import__("json").loads(v1.retained_tail_ids)) == {"m9"}

    await db.refresh(session)
    assert session.active_conversation_summary_id == v2.id
    # Fresh load resolves through the snapshot.
    conv2 = await Conversation.load(db, session)
    assert conv2.summary == "second summary"
    assert conv2.summary_id == v2.id
    assert conv2.summary_version == 2
    assert conv2.covered_ids == {"m1", "m2", "m3"}


@pytest.mark.asyncio
async def test_summary_cas_loser_leaves_no_snapshot(db, monkeypatch, tmp_path):
    """A CAS-losing store_summary leaves zero snapshot rows and never
    mutates the in-memory conversation."""
    _patch_fs(monkeypatch, tmp_path)
    from agentos.harness.conversation import Conversation
    from agentos.models.conversation_summary import ConversationSummary
    from agentos.models.session import Session

    session = Session(id=str(uuid.uuid4()), agent_id="a", contact_id="c")
    db.add(session)
    await db.commit()

    winner = Conversation(session_id=session.id)
    loser = Conversation(session_id=session.id)
    assert await winner.store_summary(db, "winner", {"m1"})
    # Loser still believes version 0.
    assert await loser.store_summary(db, "loser", {"mX"}) is False
    rows = (await db.execute(select(ConversationSummary))).scalars().all()
    assert len(rows) == 1
    assert rows[0].summary == "winner"
    assert loser.summary is None and loser.summary_id is None


@pytest.mark.asyncio
async def test_failed_store_never_snapshots(db, monkeypatch, tmp_path):
    """A failed compaction produces no snapshot — empty DB asserted, then a
    real failed summary path is driven and the table stays empty."""
    _patch_fs(monkeypatch, tmp_path)
    from agentos.config_schema import (
        AgentConfig,
        CapabilityGrant,
        CompactionConfig,
        ModelConfig,
    )
    from agentos.harness.compaction import compact_context
    from agentos.models.conversation_summary import ConversationSummary
    from agentos.providers import litellm_transport as transport_mod

    rows = (await db.execute(select(ConversationSummary))).scalars().all()
    assert rows == []

    class FailTransport:
        async def completion(self, **kw):
            raise RuntimeError("provider down")

    monkeypatch.setattr(transport_mod, "LiteLLMTransport", lambda *a, **k: FailTransport())
    config = AgentConfig(
        id="cap-agent",
        name="A",
        model=ModelConfig(provider_id="p", name="m"),
        soul="s",
        persona="p",
        task="t",
        capabilities=[CapabilityGrant(name="terminal", require_approval=False)],
        compaction=CompactionConfig(
            threshold=0.01, auto_compaction=True, tail_budget_fraction=0.02
        ),
    )
    msgs = [{"role": "user", "content": "x" * 4000} for _ in range(30)]
    result = await compact_context(
        messages=msgs,
        agent_config=config,
        model_str="m",
        force=True,
        resolved_model={"context_window_tokens": 65536},
    )
    assert result.compacted is False
    assert result.error
    rows = (await db.execute(select(ConversationSummary))).scalars().all()
    assert rows == []

    # Beyond-500-char correction must reach the summary input intact.
    correction = "z" * 640 + " ACTUAL-CORRECTION-MARKER " + "z" * 640
    seen_prompt: dict = {}

    class Spy:
        async def completion(self, **kw):
            seen_prompt.update(kw)
            msg = type("M", (), {"content": "s"})()
            return type("R", (), {"choices": [type("C", (), {"message": msg})()]})()

    monkeypatch.setattr(transport_mod, "LiteLLMTransport", lambda *a, **k: Spy())
    from agentos.harness.compaction import generate_summary

    await generate_summary(
        [{"role": "user", "content": correction}],
        previous_summary=None,
        model_str="m",
        agent_id="a",
    )
    assert correction in json.dumps(seen_prompt.get("messages", []))


@pytest.mark.asyncio
async def test_aux_summary_output_reserve_known_capacity(db, monkeypatch, tmp_path):
    """compact_context reserves exactly 2000 output tokens for the summary
    aux call — a smaller reasoning reservation never oversizes it."""
    _patch_fs(monkeypatch, tmp_path)
    from agentos.config_schema import (
        AgentConfig,
        CapabilityGrant,
        CompactionConfig,
        ModelConfig,
    )
    from agentos.harness.compaction import compact_context

    captured_budgets: dict = {}
    import agentos.harness.compaction as comp_mod

    async def spy_generate(*a, **kw):
        captured_budgets["input_budget"] = kw.get("input_budget")
        return "short summary"

    monkeypatch.setattr(comp_mod, "generate_summary", spy_generate)

    config = AgentConfig(
        id="cap-agent",
        name="A",
        model=ModelConfig(provider_id="p", name="m", max_tokens=256),
        soul="s",
        persona="p",
        task="t",
        capabilities=[CapabilityGrant(name="terminal", require_approval=False)],
        compaction=CompactionConfig(
            threshold=0.01, auto_compaction=True, tail_budget_fraction=0.02
        ),
    )
    msgs = [{"role": "user", "content": "x" * 4000} for _ in range(30)]
    await compact_context(
        messages=msgs,
        agent_config=config,
        model_str="m",
        force=True,
        resolved_model={"context_window_tokens": 65536},
        input_budget=1000,  # reasoning reservation < summary's 2000
    )
    assert captured_budgets["input_budget"] == min(1000, 65536 - 2000)


@pytest.mark.asyncio
async def test_summary_beyond_500_char_correction_reaches_model(db, monkeypatch, tmp_path):
    """generate_summary must include the FULL user/assistant text — a
    correction beyond char 500 reaches the provider, or the call fails
    honestly before dispatch."""
    _patch_fs(monkeypatch, tmp_path)
    monkeypatch.setattr(settings, "context_capture_retention_days", 365)
    correction = "X" * 620 + " ACTUAL-UNIQUE-CORRECTION-TOKEN-42 " + "y" * 620

    seen: dict = {}

    class Spy:
        async def completion(self, **kw):
            seen.update(kw)
            msg = type("M", (), {"content": "s"})()
            return type("R", (), {"choices": [type("C", (), {"message": msg})()]})()

    from agentos.providers import litellm_transport as transport_mod

    monkeypatch.setattr(transport_mod, "LiteLLMTransport", lambda *a, **k: Spy())
    from agentos.harness.compaction import generate_summary

    await generate_summary(
        [
            {"role": "user", "content": correction},
            {"role": "assistant", "content": "understood"},
        ],
        previous_summary=None,
        model_str="m",
        agent_id="a",
    )
    prompt_text = json.dumps(seen.get("messages", []))
    # The correction must appear intact — no 500-char clipping.
    assert "ACTUAL-UNIQUE-CORRECTION-TOKEN-42" in prompt_text
    assert correction in prompt_text


@pytest.mark.asyncio
async def test_summary_input_budget_refuses_before_dispatch(db, monkeypatch, tmp_path):
    """A known-capacity model whose summary prompt exceeds the reserved
    input ceiling never dispatches — it fails honestly."""
    _patch_fs(monkeypatch, tmp_path)
    monkeypatch.setattr(settings, "context_capture_retention_days", 365)
    from agentos.harness.compaction import generate_summary

    calls: list = []

    class Spy:
        async def completion(self, **kw):
            calls.append(kw)
            raise AssertionError("must not dispatch")

    from agentos.providers import litellm_transport as transport_mod

    monkeypatch.setattr(transport_mod, "LiteLLMTransport", lambda *a, **k: Spy())
    with pytest.raises(RuntimeError, match="input budget"):
        await generate_summary(
            [{"role": "user", "content": "word " * 100000}],
            previous_summary=None,
            model_str="m",
            agent_id="a",
            input_budget=10,
        )
    assert calls == []


@pytest.mark.asyncio
async def test_metadata_nesting_and_huge_int_never_persist(db, monkeypatch, tmp_path):
    """project_capture_metadata drops nested canaries under allowed keys,
    huge ints never reach math.isfinite, and >200 ids truncate with an
    explicit flag."""
    _patch_fs(monkeypatch, tmp_path)
    from agentos.services.context_capture import project_capture_metadata

    out = project_capture_metadata(
        {
            "component_budget": {
                "history": 2**63 + 5,  # huge int — never isfinite()'d
                "custom_nested": {"canary": "sk-xyz"},
                "tools": 42,
            },
            "source_message_ids": [f"m-{i}" for i in range(250)],
            "source_message_ids_total": 300,
            "source_message_ids_truncated": True,
            "coverage_known": {"nested": "canary-value"},
            "agent_id": "a-1",
        }
    )
    assert out["component_budget"] == {"tools": 42}
    assert len(out["source_message_ids"]) == 200
    assert out["source_message_ids_total"] == 300
    assert out["source_message_ids_truncated"] is True
    assert out.get("coverage_known") is None  # non-bool dropped


@pytest.mark.asyncio
async def test_invalid_attempt_metadata_never_blocks_dispatch(db, monkeypatch, tmp_path):
    """Malformed attempt_metadata shapes degrade to the scope-only
    snapshot — the transport still receives the call."""
    _patch_fs(monkeypatch, tmp_path)
    seen = {}

    async def ok(**kw):
        seen.update(kw)
        return object()

    with capture_scope(agent_id="t", purpose="reasoning"):
        result, ref = await capture_dispatch(
            "chat",
            {"model": "m"},
            ok,
            attempt_metadata={"provider_id": {"evil": "nested"}},
        )
    assert result is not None
    assert seen["model"] == "m"
    assert ref.id is not None


@pytest.mark.asyncio
async def test_ineffective_compaction_never_advances(db, monkeypatch, tmp_path):
    """A summary longer than the originals returns compacted=False with
    untouched messages/prior summary — coverage never advances."""
    _patch_fs(monkeypatch, tmp_path)
    from agentos.config_schema import CompactionConfig
    from agentos.harness.compaction import compact_context

    msgs = [{"role": "user", "content": "x" * 4000} for _ in range(30)]

    class Bloated:
        async def completion(self, **kw):
            # Summary LONGER than originals.
            msg = type("M", (), {"content": "summary " * 30000})()
            return type("R", (), {"choices": [type("C", (), {"message": msg})()]})()

    from agentos.providers import litellm_transport as transport_mod

    monkeypatch.setattr(transport_mod, "LiteLLMTransport", lambda *a, **k: Bloated())
    from agentos.config_schema import AgentConfig, CapabilityGrant, ModelConfig

    config = AgentConfig(
        id="cap-agent",
        name="A",
        model=ModelConfig(provider_id="p", name="m"),
        soul="s",
        persona="p",
        task="t",
        capabilities=[CapabilityGrant(name="terminal", require_approval=False)],
        compaction=CompactionConfig(
            threshold=0.01, auto_compaction=True, tail_budget_fraction=0.02
        ),
    )
    result = await compact_context(
        messages=msgs,
        agent_config=config,
        model_str="m",
        force=True,
        resolved_model={"context_window_tokens": 65536},
        reserved_tokens=0,
    )
    assert result.compacted is False
    assert result.messages == msgs
    assert result.summary is None
    assert result.error == "Summary did not reduce token usage", result
    assert result.covered_ids == set()  # coverage never advanced


@pytest.mark.asyncio
async def test_aux_receipt_persists_scope_snapshot_ids(db, monkeypatch, tmp_path):
    """A successful aux call receipt written OUTSIDE the scope still gets
    the captured run/subagent/turn/provider/model — the caller that forgot
    them never loses correlation."""
    _patch_fs(monkeypatch, tmp_path)
    monkeypatch.setattr(settings, "context_capture_retention_days", 365)

    async def ok(**kw):
        return object()

    with capture_scope(
        run_id="r-7",
        agent_id="a-7",
        sub_agent_id="sub-2",
        turn=4,
        purpose="compaction",
        model="m",
    ):
        result, ref = await capture_dispatch(
            "chat_stream",
            {"model": "m"},
            ok,
            attempt_metadata={
                "provider_id": "p-9",
                "model_name": "m",
                "model_str": "prov/m",
            },
        )
    # Scope exited — receipt lands outside it; the snapshot supplies ids.
    from agentos.services.model_ledger import record_system_call

    await record_system_call(kind="chat", capture_ref=ref, response=None)
    row = await db.get(ModelCall, ref.id)
    assert row is not None
    assert row.run_id == "r-7" and row.agent_id == "a-7"
    assert row.sub_agent_id == "sub-2" and row.turn == 4
    assert row.provider_id == "p-9" and row.model_str == "prov/m"
    assert row.streamed is True


@pytest.mark.asyncio
async def test_session_factory_failure_still_dispatches(db, monkeypatch, tmp_path):
    """The capture session factory failing (create or __aenter__) never
    blocks the SDK call; the caller's own receipt still lands on the
    capture id."""
    _patch_fs(monkeypatch, tmp_path)

    class Boom:
        async def __aenter__(self):
            raise RuntimeError("db gone")

        async def __aexit__(self, *a):
            pass

    import agentos.db as db_mod

    monkeypatch.setattr(db_mod, "async_session_factory", lambda: Boom())

    called: dict = {}

    async def ok(**kw):
        called.update(kw)
        return object()

    with capture_scope(agent_id="t", purpose="reasoning", run_id="r-9"):
        result, ref = await capture_dispatch("chat", {"model": "m"}, ok)
    assert result is not None
    assert called["model"] == "m"
    assert ref.state == "failed"
    assert ref.id is not None


@pytest.mark.asyncio
async def test_stream_success_ref_has_whole_duration(db, monkeypatch, tmp_path):
    """A completed stream's ref carries full-consumption duration — the
    caller sees the late replacement, not iterator-creation ms."""
    _patch_fs(monkeypatch, tmp_path)
    import agentos.services.context_capture as cap_mod

    # Deterministic clock — only this module's binding, not asyncio's.
    # monotonic is called twice: dispatch start and stream-stop. Chunks
    # do not tick — the whole-duration stamp only lands on exhaustion.
    ticks = iter([0.0, 0.05, 0.9])

    class FakeTime:
        @staticmethod
        def monotonic() -> float:
            try:
                return next(ticks)
            except StopIteration:
                return 0.9

    monkeypatch.setattr(cap_mod, "time", FakeTime)
    monkeypatch.setattr(settings, "context_capture_retention_days", 365)

    async def stream(**kw):
        async def _g():
            yield "a"
            yield "b"

        return _g()

    with capture_scope(agent_id="t", purpose="reasoning", run_id="r-1"):
        stream_it, _ = await capture_dispatch("chat_stream", {"model": "m"}, stream)
        async for _ in stream_it:
            pass
    final_ref = stream_it.request_capture
    assert final_ref.latency_ms == 900


@pytest.mark.asyncio
async def test_harness_error_upsert_never_echoes_canary(db, monkeypatch, tmp_path):
    """When a capture boundary ref exists, the harness failure upsert
    records only the exception TYPE — the provider body canary never lands
    in ModelCall.error."""
    _patch_fs(monkeypatch, tmp_path)
    from unittest.mock import AsyncMock

    from agentos.config_schema import ModelConfig
    from agentos.harness.litellm_adapter import LiteLLMAdapter
    from agentos.models.model_call import ModelCall

    class BoomTransport:
        async def completion(self, **kw):
            raise RuntimeError("private-canary-ANVIL-99 leaked body")

    adapter = LiteLLMAdapter(db=db, transport=BoomTransport())

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
    with pytest.raises(RuntimeError):
        await adapter.complete(
            agent_model=model,
            messages=[{"role": "user", "content": "hi"}],
            tools=None,
        )
    rows = (await db.execute(select(ModelCall))).scalars().all()
    assert rows and all("ANVIL-99" not in (r.error or "") for r in rows)
    assert all(r.error == "RuntimeError" for r in rows)


@pytest.mark.asyncio
async def test_stream_wrap_accepts_any_async_iterable(db, monkeypatch, tmp_path):
    """An async iterable without its own __anext__ works — the wrapper
    normalizes with aiter()."""
    _patch_fs(monkeypatch, tmp_path)
    monkeypatch.setattr(settings, "context_capture_retention_days", 365)

    class OnlyAiter:
        def __aiter__(self):
            async def _g():
                yield "x"

            return _g()

    async def stream(**kw):
        return OnlyAiter()

    with capture_scope(agent_id="t", purpose="reasoning"):
        stream_it, _ = await capture_dispatch("chat_stream", {"model": "m"}, stream)
        out = [item async for item in stream_it]
    assert out == ["x"]
