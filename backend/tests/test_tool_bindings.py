"""W5 — global tool bindings: persistence, resolver, settings API,
catalog gating, and mediation of bound tools."""

import json
import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from agentos.auth import require_operator
from agentos.capabilities.bindings import (
    BINDING_SPECS,
    capability_ready,
    resolve_binding,
    spec_for,
    validate_options,
)
from agentos.db import get_db
from agentos.main import app
from agentos.models.operator import Operator, OperatorAuditLog
from agentos.models.provider import Provider
from agentos.models.tool_binding import ToolBinding


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


async def _provider(db, name="TestProv", type_="openai", with_key=True) -> Provider:
    p = Provider(
        id=str(uuid.uuid4()),
        name=name,
        type=type_,
        encrypted_key="enc:fake" if with_key else None,
        base_url=None,
        org_id=None,
        extra_params="{}",
        custom_models="[]",
    )
    db.add(p)
    await db.flush()
    return p


# --- spec validation ---


def test_spec_registry_covers_known_keys():
    keys = {s.key for s in BINDING_SPECS}
    assert "search.web" in keys
    engine = spec_for("search.web")
    assert engine and engine.kind == "engine" and engine.implemented


def test_validate_options_normalizes_and_rejects():
    spec = spec_for("search.web")
    out = validate_options(spec, {"engines": ["brave", "duckduckgo"], "region": " us-en "})
    assert out["engines"] == ["brave", "duckduckgo"]
    assert out["region"] == "us-en"
    assert out["safesearch"] == "moderate"  # default filled

    with pytest.raises(ValueError, match="unknown option"):
        validate_options(spec, {"bogus": 1})
    with pytest.raises(ValueError):
        validate_options(spec, {"engines": ["not-an-engine"]})
    with pytest.raises(ValueError):
        validate_options(spec, {"engines": ["brave", "brave"]})
    with pytest.raises(ValueError):
        validate_options(spec, {"safesearch": "bogus"})


# --- resolver ---


async def test_engine_unconfigured_is_usable(db):
    resolution = await resolve_binding(db, "search.web")
    assert resolution.state == "unconfigured"
    assert resolution.ready is True  # engine defaults remain usable
    assert resolution.options["engines"][0] == "duckduckgo"


async def test_unimplemented_spec_resolves_unready(db):
    resolution = await resolve_binding(db, "media.tts")
    assert resolution.state == "unimplemented"
    assert resolution.ready is False


async def test_model_binding_states(db):
    # unconfigured
    r = await resolve_binding(db, "media.image")
    assert r.state == "unimplemented"

    provider = await _provider(db, name="VoiceProv")

    # model-backed spec is unimplemented → stays unready regardless of rows
    db.add(
        ToolBinding(
            id=str(uuid.uuid4()),
            key="media.image",
            provider_id=provider.id,
            model="dall-e-3",
            options="{}",
        )
    )
    await db.flush()
    r = await resolve_binding(db, "media.image")
    assert r.state == "unimplemented"  # spec gate wins


async def test_capability_ready_reflects_binding(db):
    # Engine tool — usable unconfigured.
    assert await capability_ready(db, "web_search") is True
    # Model-backed planned tool — never ready while spec unimplemented.
    assert await capability_ready(db, "media_speak") is False


# --- settings API ---


async def test_list_tools_endpoint(client):
    r = await client.get("/api/settings/tools")
    assert r.status_code == 200
    tools = {t["key"]: t for t in r.json()["tools"]}
    search = tools["search.web"]
    assert search["implemented"] is True
    assert search["kind"] == "engine"
    assert search["ready"] is True
    assert search["options_schema"]
    tts = tools["media.tts"]
    assert tts["implemented"] is False
    assert tts["planned_note"]


async def test_put_engine_binding_and_conflict(client, db):
    r = await client.put(
        "/api/settings/tools/search.web",
        json={"options": {"engines": ["brave", "duckduckgo"], "region": "de-de"}},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["options"]["engines"] == ["brave", "duckduckgo"]
    rev = body["binding"]["revision"]

    # stale revision → 409
    r2 = await client.put(
        "/api/settings/tools/search.web",
        json={"options": {"engines": ["brave"]}, "expected_revision": rev + 5},
    )
    assert r2.status_code == 409

    # correct revision → ok
    r3 = await client.put(
        "/api/settings/tools/search.web",
        json={"options": {"engines": ["brave"]}, "expected_revision": rev},
    )
    assert r3.status_code == 200

    # audit row written
    audits = (await db.execute(select(OperatorAuditLog))).scalars().all()
    assert any(a.action == "tool_binding.update" for a in audits)


async def test_put_engine_rejects_provider_and_bad_options(client):
    r = await client.put(
        "/api/settings/tools/search.web",
        json={"provider_id": "p1", "options": {}},
    )
    assert r.status_code == 422
    r = await client.put(
        "/api/settings/tools/search.web",
        json={"options": {"engines": ["duckduckgo", "fake"]}},
    )
    assert r.status_code == 422


async def test_put_unimplemented_is_refused(client):
    r = await client.put(
        "/api/settings/tools/media.tts",
        json={"provider_id": "p", "model": "tts-1"},
    )
    assert r.status_code == 422


async def test_unknown_key_404_and_reset(client, db):
    r = await client.put("/api/settings/tools/nope", json={})
    assert r.status_code == 404
    r = await client.delete("/api/settings/tools/nope")
    assert r.status_code == 404

    db.add(
        ToolBinding(
            id=str(uuid.uuid4()), key="search.web", options=json.dumps({"engines": ["brave"]})
        )
    )
    await db.flush()
    r = await client.delete("/api/settings/tools/search.web")
    assert r.status_code == 200
    assert r.json()["binding"] is None


# --- catalog gate ---


async def test_catalog_hides_unready_binding_tools(db):
    from agentos.capabilities.catalog import CapabilityRunCatalog
    from agentos.capabilities.registry import CapabilityDef, registry
    from agentos.config_schema import AgentConfig

    # A test model-backed capability gated by an unimplemented spec.
    registry.register(
        CapabilityDef(
            name="media_speak",
            kind="tool",
            description="test tts",
            parameters_schema={"type": "object", "properties": {}},
            execute=lambda **k: {},
        )
    )
    config = AgentConfig(id="a", name="A", model={"provider_id": "p", "name": "m"})
    catalog = CapabilityRunCatalog(agent_config=config, db=db)
    names = [m["name"] for m in await catalog._metadata()]
    assert "media_speak" not in names

    # load() rejects with the not-configured reason
    out = await catalog.load(["media_speak"])
    assert out["rejected"][0]["reason"].startswith("Tool is not configured")

    # web_search remains available (engine defaults)
    assert "web_search" in names


# --- mediation ---


def _agent_with(caps: list[str]):
    from agentos.config_schema import AgentConfig, CapabilityGrant, ModelConfig

    return AgentConfig(
        id="a",
        name="A",
        model=ModelConfig(provider_id="p", name="m"),
        capabilities=[CapabilityGrant(name=c, require_approval=False) for c in caps],
    )


def _session():
    from types import SimpleNamespace

    return SimpleNamespace(contact_id="c1", id="s1", channel=None)


async def test_mediator_denies_invalid_engine_binding(db, workspace):
    """A stored binding whose options fail validation must fail through
    mediation — never silently fall back to defaults at execution time."""
    from agentos.capabilities.builtin import register_builtin_capabilities
    from agentos.capabilities.registry import registry
    from agentos.syscall.mediator import SyscallHandler
    from agentos.syscall.protocol import ToolCall

    registry._caps.clear()
    register_builtin_capabilities()
    try:
        db.add(
            ToolBinding(
                id=str(uuid.uuid4()),
                key="search.web",
                options=json.dumps({"engines": ["not-an-engine"]}),
            )
        )
        await db.flush()

        handler = SyscallHandler(db=db, workspace_path=workspace)
        result = await handler.mediate(
            call=ToolCall(id="1", name="web_search", args={"query": "x"}),
            session=_session(),
            agent_config=_agent_with(["web_search"]),
            run_id="r1",
        )
        assert result.allowed is False
        assert "not ready" in result.denied_reason
    finally:
        registry._caps.clear()


async def test_binding_does_not_grant_capability_authority(db, workspace):
    """A valid binding changes HOW a tool runs — it never changes WHO may
    run it. An agent without the grant is still denied at step 2."""
    from agentos.capabilities.builtin import register_builtin_capabilities
    from agentos.capabilities.registry import registry
    from agentos.syscall.mediator import SyscallHandler
    from agentos.syscall.protocol import ToolCall

    registry._caps.clear()
    register_builtin_capabilities()
    try:
        db.add(
            ToolBinding(
                id=str(uuid.uuid4()),
                key="search.web",
                options=json.dumps({"engines": ["brave"]}),
            )
        )
        await db.flush()

        handler = SyscallHandler(db=db, workspace_path=workspace)
        result = await handler.mediate(
            call=ToolCall(id="1", name="web_search", args={"query": "x"}),
            session=_session(),
            agent_config=_agent_with([]),  # no grant at all
            run_id="r1",
        )
        assert result.allowed is False
        assert result.denied_reason == "not granted"
    finally:
        registry._caps.clear()


async def test_mediator_injects_frozen_binding_options(db, workspace, monkeypatch):
    """The admission-time resolution rides into the tool as frozen options —
    the tool never re-reads the settings table mid-execution."""
    from agentos.capabilities.builtin import register_builtin_capabilities
    from agentos.capabilities.registry import registry
    from agentos.syscall.mediator import SyscallHandler
    from agentos.syscall.protocol import ToolCall

    registry._caps.clear()
    register_builtin_capabilities()
    captured: dict = {}

    async def fake_search(**kwargs):
        captured.update(kwargs)
        return {"results": []}

    monkeypatch.setattr(registry.get("web_search"), "execute", fake_search)
    try:
        db.add(
            ToolBinding(
                id=str(uuid.uuid4()),
                key="search.web",
                options=json.dumps({"engines": ["brave"], "region": "de-de"}),
            )
        )
        await db.flush()

        handler = SyscallHandler(db=db, workspace_path=workspace)
        result = await handler.mediate(
            call=ToolCall(id="1", name="web_search", args={"query": "x"}),
            session=_session(),
            agent_config=_agent_with(["web_search"]),
            run_id="r1",
        )
        assert result.allowed is True
        assert captured["tool_options"]["engines"] == ["brave"]
        assert captured["tool_options"]["region"] == "de-de"
        assert captured["tool_binding"].binding.key == "search.web"
    finally:
        registry._caps.clear()


# --- honest settings surface ---


async def test_settings_endpoints_make_no_provider_calls(client, monkeypatch):
    """Opening or saving tool settings must never reach a provider — any
    attempt is a bug, not a network flake."""
    import litellm

    def _boom(*a, **k):
        raise AssertionError("provider call during settings operation")

    monkeypatch.setattr(litellm, "acompletion", _boom)
    monkeypatch.setattr(litellm, "aembedding", _boom)

    r = await client.get("/api/settings/tools")
    assert r.status_code == 200
    r = await client.put(
        "/api/settings/tools/search.web",
        json={"options": {"safesearch": "off"}},
    )
    assert r.status_code == 200
    r = await client.delete("/api/settings/tools/search.web")
    assert r.status_code == 200


async def test_settings_response_never_includes_secrets(client, db):
    """Provider references are id/name/type only — encrypted key material
    never leaves through the bindings surface."""
    secret_marker = "sk-test-SECRET-000111"
    provider = await _provider(db, name="SecretProv")
    provider.encrypted_key = f"enc:{secret_marker}"
    db.add(
        ToolBinding(
            id=str(uuid.uuid4()),
            key="search.web",
            provider_id=provider.id,
            options=json.dumps({"engines": ["brave"]}),
        )
    )
    await db.flush()

    r = await client.get("/api/settings/tools")
    assert r.status_code == 200
    assert secret_marker not in r.text
    assert "encrypted" not in r.text
