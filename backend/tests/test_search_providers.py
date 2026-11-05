"""Search uses Provider custody without model discovery, fallback, or fake tokens."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from cryptography.fernet import Fernet
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from agentos.auth import require_operator
from agentos.capabilities.bindings import resolve_binding
from agentos.capabilities.registry import registry
from agentos.capabilities.tools.web import web_search
from agentos.config import settings
from agentos.config_schema import AgentConfig, CapabilityGrant, ModelConfig
from agentos.db import get_db
from agentos.main import app
from agentos.models.model_call import ModelCall
from agentos.models.operator import Operator, OperatorAuditLog
from agentos.models.provider import Provider
from agentos.models.tool_binding import ToolBinding
from agentos.models.web_source import WebSource
from agentos.providers.registry import ProviderRegistry
from agentos.providers.search import search_provider
from agentos.secret_store import decrypt
from agentos.syscall.mediator import SyscallHandler
from agentos.syscall.protocol import ToolCall


@pytest.fixture
async def client(db, monkeypatch):
    monkeypatch.setattr("agentos.secret_store._fernet", Fernet(Fernet.generate_key()))
    app.dependency_overrides[require_operator] = lambda: Operator(
        id="operator", username="test", password_hash="x"
    )
    app.dependency_overrides[get_db] = lambda: db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client
    app.dependency_overrides.clear()


async def create_search(client):
    response = await client.post(
        "/api/providers", json={"name": "My Tavily", "type": "tavily", "api_key": "test-secret"}
    )
    assert response.status_code == 200
    return response.json()["id"]


async def bind_search(client, provider_id):
    return await client.put(
        "/api/settings/tools/search.web",
        json={"provider_id": provider_id, "options": {"backend": "tavily"}},
    )


async def test_provider_custody_scope_and_no_discovery(client, db, monkeypatch):
    refresh = []
    monkeypatch.setattr("agentos.providers.model_catalog.schedule_provider_refresh", refresh.append)
    provider_id = await create_search(client)
    row = await db.get(Provider, provider_id)
    assert row.encrypted_key != "test-secret"
    assert decrypt(row.encrypted_key) == "test-secret"
    assert (await client.get("/api/providers")).json() == []
    searches = (await client.get("/api/providers?scope=search")).json()
    assert len(searches) == 1 and searches[0]["scope"] == "search"
    assert searches[0]["has_key"]
    assert "test-secret" not in json.dumps(searches)
    assert len((await client.get("/api/providers?scope=all")).json()) == 1
    for method, path in [
        ("GET", "models"),
        ("GET", "catalog-models"),
        ("POST", "models/refresh"),
        ("POST", "validate"),
    ]:
        response = await client.request(method, f"/api/providers/{provider_id}/{path}", json={})
        assert response.status_code == 422
    with pytest.raises(ValueError, match="tool service"):
        await ProviderRegistry(db).for_model(provider_id)
    assert refresh == []


async def test_replace_preserve_remove_key_and_readiness(client, db):
    provider_id = await create_search(client)
    assert (await bind_search(client, provider_id)).json()["ready"]
    for body in ({}, {"api_key": ""}, {"api_key": "   "}):
        assert (await client.put(f"/api/providers/{provider_id}", json=body)).status_code == 200
        assert decrypt((await db.get(Provider, provider_id)).encrypted_key) == "test-secret"
    assert (
        await client.put(f"/api/providers/{provider_id}", json={"api_key": "replacement"})
    ).json()["has_key"]
    assert decrypt((await db.get(Provider, provider_id)).encrypted_key) == "replacement"
    removed = await client.put(f"/api/providers/{provider_id}", json={"remove_api_key": True})
    assert not removed.json()["has_key"]
    assert not (await resolve_binding(db, "search.web")).ready
    audits = list((await db.scalars(select(OperatorAuditLog))).all())
    assert "replacement" not in str([a.target for a in audits])
    assert (
        await client.put(
            f"/api/providers/{provider_id}",
            json={"api_key": "new", "remove_api_key": True},
        )
    ).status_code == 422


async def test_search_rejects_model_provider_custom_endpoint_and_model_binding(client):
    bad = await client.post(
        "/api/providers",
        json={
            "name": "Bad",
            "type": "tavily",
            "api_key": "secret",
            "base_url": "http://127.0.0.1",
        },
    )
    assert bad.status_code == 422
    provider_id = await create_search(client)
    assert (
        await client.put(
            "/api/settings/tools/media.image",
            json={"provider_id": provider_id, "model": "anything"},
        )
    ).status_code == 422
    assert (
        await client.put(
            "/api/settings/tools/search.web",
            json={
                "provider_id": provider_id,
                "model": "anything",
                "options": {"backend": "tavily"},
            },
        )
    ).status_code == 422
    assert (
        await client.put("/api/settings/tools/search.web", json={"options": {"backend": "tavily"}})
    ).status_code == 422


async def test_snapshot_detects_rotation_even_with_refreshed_orm_object(client, db):
    provider_id = await create_search(client)
    await bind_search(client, provider_id)
    admitted = await resolve_binding(db, "search.web")
    await client.put(f"/api/providers/{provider_id}", json={"api_key": "rotated"})
    current = await resolve_binding(db, "search.web")
    assert current.identity != admitted.identity


@pytest.mark.parametrize("stored", ["null", "[]", '""'])
async def test_corrupt_empty_options_never_silently_default(db, stored):
    db.add(ToolBinding(key="search.web", options=stored))
    await db.flush()
    assert not (await resolve_binding(db, "search.web")).ready


async def test_search_readiness_requires_the_api_key_not_unrelated_credentials(client, db):
    provider_id = await create_search(client)
    await bind_search(client, provider_id)
    provider = await db.get(Provider, provider_id)
    provider.encrypted_key = None
    provider.encrypted_credentials = "not-an-api-key"
    await db.flush()
    assert not (await resolve_binding(db, "search.web")).ready


@pytest.mark.parametrize("change", ["rotate", "reset", "delete", "deny"])
async def test_pending_search_never_executes_changed_or_denied_connection(
    client, db, workspace, monkeypatch, change
):
    provider_id = await create_search(client)
    await bind_search(client, provider_id)
    execute = AsyncMock(return_value={"results": []})
    monkeypatch.setattr(registry.get("web_search"), "execute", execute)
    monkeypatch.setattr(settings, "yolo_mode", False)

    async def approve(**kwargs):
        if change == "rotate":
            await client.put(f"/api/providers/{provider_id}", json={"api_key": "rotated"})
        elif change == "reset":
            await client.delete("/api/settings/tools/search.web")
        elif change == "delete":
            await client.delete(f"/api/providers/{provider_id}")
        return change != "deny"

    handler = SyscallHandler(db=db, workspace_path=workspace)
    monkeypatch.setattr(handler, "_await_approval", approve)
    result = await handler.mediate(
        call=ToolCall(id="call", name="web_search", args={"query": "query"}),
        session=SimpleNamespace(id="session", contact_id="contact", channel=None),
        agent_config=AgentConfig(
            id="agent",
            name="Agent",
            model=ModelConfig(provider_id="model", name="chat"),
            capabilities=[CapabilityGrant(name="web_search", require_approval=True)],
        ),
        run_id="run",
    )
    assert not result.allowed
    execute.assert_not_awaited()


def mock_search_http(monkeypatch, handler):
    original = httpx.AsyncClient
    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(
        "agentos.providers.search.httpx.AsyncClient",
        lambda **kwargs: original(transport=transport, **kwargs),
    )


async def test_mapped_search_uses_provider_key_no_model_no_visited_records(client, db, monkeypatch):
    provider_id = await create_search(client)
    await bind_search(client, provider_id)
    requests = []

    def handle(request):
        requests.append(request)
        assert str(request.url) == "https://api.tavily.com/search"
        assert request.headers["authorization"] == "Bearer test-secret"
        payload = json.loads(request.content)
        assert payload["include_answer"] is False
        assert "model" not in payload
        return httpx.Response(
            200,
            json={
                "results": [{"title": "A", "url": "https://example.org", "content": "Snippet"}],
                "usage": {"credits": 1},
            },
        )

    mock_search_http(monkeypatch, handle)
    result = await web_search(
        {"query": "Find it"}, tool_binding=await resolve_binding(db, "search.web")
    )
    assert result["results"] == [{"title": "A", "url": "https://example.org", "snippet": "Snippet"}]
    assert result["service_usage"]["credits"] == 1
    assert result["service_usage"]["cost"] is None
    assert len(requests) == 1
    assert list(await db.scalars(select(ModelCall))) == []
    assert list(await db.scalars(select(WebSource))) == []


@pytest.mark.parametrize("status", [401, 429, 302, 500])
async def test_errors_do_not_leak_echoed_key_or_fallback(client, db, monkeypatch, status):
    provider_id = await create_search(client)
    mock_search_http(monkeypatch, lambda request: httpx.Response(status, text="test-secret echoed"))
    result = await search_provider(await db.get(Provider, provider_id), "query")
    assert "error" in result
    assert "test-secret" not in json.dumps(result)
    assert result["service_usage"]["requests"] == 1


async def test_invalid_oversized_timeout_and_query_bounds(client, db, monkeypatch):
    provider_id = await create_search(client)
    provider = await db.get(Provider, provider_id)
    for response in [
        httpx.Response(200, text="not json"),
        httpx.Response(200, json={"results": None}),
        httpx.Response(200, content=b"x" * (512 * 1024 + 1)),
    ]:
        with monkeypatch.context() as patch:
            mock_search_http(patch, lambda request, response=response: response)
            assert "error" in await search_provider(provider, "query")

    def timeout(request):
        raise httpx.ReadTimeout("test-secret")

    mock_search_http(monkeypatch, timeout)
    assert (await search_provider(provider, "query"))["service_usage"]["status"] == "timeout"
    assert "service_usage" not in await search_provider(provider, "", 5)
    assert "service_usage" not in await search_provider(provider, "query", 100)


async def test_explicit_probe_consent_and_synthetic_query(client, db, monkeypatch):
    provider_id = await create_search(client)
    calls = []

    def handle(request):
        calls.append(json.loads(request.content))
        return httpx.Response(200, json={"results": []})

    mock_search_http(monkeypatch, handle)
    denied = await client.post(f"/api/providers/{provider_id}/test-search", json={})
    assert denied.status_code == 422 and calls == []
    tested = await client.post(f"/api/providers/{provider_id}/test-search", json={"consent": True})
    assert tested.json()["ok"]
    assert calls[0]["query"] == "CaberOS connection test"
    assert calls[0]["max_results"] == 1


@pytest.mark.parametrize("credits", [float("inf"), float("nan"), True, -1])
async def test_invalid_reported_units_remain_unknown(client, db, monkeypatch, credits):
    provider_id = await create_search(client)
    mock_search_http(
        monkeypatch,
        lambda request: httpx.Response(
            200, content=json.dumps({"results": [], "usage": {"credits": credits}}).encode()
        ),
    )
    result = await search_provider(await db.get(Provider, provider_id), "query")
    assert result["service_usage"]["credits"] is None
    json.dumps(result, allow_nan=False)


# ---------------------------------------------------------------------------
# Per-adapter request/response contract fixtures (Exa, Brave, Firecrawl)
# ---------------------------------------------------------------------------


async def create_service(client, name, service_type):
    response = await client.post(
        "/api/providers",
        json={"name": name, "type": service_type, "api_key": "test-secret"},
    )
    assert response.status_code == 200
    return response.json()["id"]


@pytest.mark.parametrize(
    "service,method,url,auth_header",
    [
        ("exa", "POST", "https://api.exa.ai/search", "x-api-key"),
        (
            "brave_search",
            "GET",
            "https://api.search.brave.com/res/v1/web/search",
            "x-subscription-token",
        ),
        ("firecrawl", "POST", "https://api.firecrawl.dev/v2/search", "authorization"),
    ],
)
async def test_adapter_request_shape_and_auth(
    client, db, monkeypatch, service, method, url, auth_header
):
    provider_id = await create_service(client, f"My {service}", service)
    provider = await db.get(Provider, provider_id)
    requests = []

    def handle(request):
        requests.append(request)
        return httpx.Response(200, json={"results": []})

    mock_search_http(monkeypatch, handle)
    await search_provider(provider, "find it", 3)
    assert len(requests) == 1
    request = requests[0]
    assert request.method == method
    assert str(request.url).startswith(url)
    auth = request.headers.get(auth_header)
    assert auth is not None and "test-secret" in auth


@pytest.mark.parametrize(
    "service,payload,want_results,want",
    [
        (
            "exa",
            {
                "results": [
                    {
                        "title": "A",
                        "url": "https://example.org",
                        "highlights": ["h1", "h2", "h3", "h4"],
                    }
                ],
                "costDollars": {"total": 0.005},
            },
            [{"title": "A", "url": "https://example.org", "snippet": "h1 h2 h3"}],
            {"estimated_cost": 0.005, "cost_status": "estimated"},
        ),
        (
            "brave_search",
            {
                "web": {
                    "results": [{"title": "B", "url": "https://example.org", "description": "desc"}]
                }
            },
            [{"title": "B", "url": "https://example.org", "snippet": "desc"}],
            {},
        ),
        (
            "firecrawl",
            {
                "success": True,
                "data": {
                    "web": [{"title": "F", "url": "https://example.org", "description": "fdesc"}]
                },
                "creditsUsed": 2,
            },
            [{"title": "F", "url": "https://example.org", "snippet": "fdesc"}],
            {"credits": 2},
        ),
    ],
)
async def test_adapter_success_normalization(
    client, db, monkeypatch, service, payload, want_results, want
):
    provider_id = await create_service(client, f"My {service}", service)
    provider = await db.get(Provider, provider_id)
    mock_search_http(monkeypatch, lambda request: httpx.Response(200, json=payload))
    result = await search_provider(provider, "query")
    assert result["results"] == want_results
    usage = result["service_usage"]
    assert usage["requests"] == 1 and usage["status"] == "ok"
    for key, value in want.items():
        assert usage[key] == value


@pytest.mark.parametrize(
    "service,payload",
    [
        ("exa", {"results": []}),
        ("brave_search", {}),  # Brave omits the web section when empty.
        ("firecrawl", {"success": True, "data": {"web": []}}),
    ],
)
async def test_adapter_empty_results_are_not_errors(client, db, monkeypatch, service, payload):
    provider_id = await create_service(client, f"My {service}", service)
    provider = await db.get(Provider, provider_id)
    mock_search_http(monkeypatch, lambda request: httpx.Response(200, json=payload))
    result = await search_provider(provider, "query")
    assert result.get("error") is None
    assert result["results"] == []
    assert result["service_usage"]["status"] == "ok"


@pytest.mark.parametrize(
    "service,payload",
    [
        ("exa", {"results": [{"url": "https://x", "highlights": "not-a-list"}]}),
        ("brave_search", {"web": "broken"}),
        ("firecrawl", {"success": False}),
    ],
)
async def test_adapter_malformed_payloads_fail_honestly(client, db, monkeypatch, service, payload):
    provider_id = await create_service(client, f"My {service}", service)
    provider = await db.get(Provider, provider_id)
    mock_search_http(monkeypatch, lambda request: httpx.Response(200, json=payload))
    result = await search_provider(provider, "query")
    assert "error" in result


@pytest.mark.parametrize("service", ["exa", "brave_search", "firecrawl"])
@pytest.mark.parametrize("status", [401, 429])
async def test_adapter_auth_and_rate_limit_failures(client, db, monkeypatch, service, status):
    provider_id = await create_service(client, f"My {service}", service)
    provider = await db.get(Provider, provider_id)
    mock_search_http(monkeypatch, lambda request: httpx.Response(status, text="test-secret echoed"))
    result = await search_provider(provider, "query")
    assert "error" in result
    assert "test-secret" not in json.dumps(result)
    assert result["service_usage"]["requests"] == 1
