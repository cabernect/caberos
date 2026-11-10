"""Catalog API-key connections must expose setup and retain encrypted custody."""

import json
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import select

from agentos.api.mcp import (
    CreateServerRequest,
    InstallFromCatalogRequest,
    StoreCredentialRequest,
    UpdateServerRequest,
    create_server,
    install_from_catalog,
    list_servers,
    store_server_credential,
    update_server,
)
from agentos.mcp import catalog, credentials, registry
from agentos.models.mcp import ContactMcpBinding, McpServer, McpServerCredential
from agentos.models.operator import Operator


async def test_http_header_credentials_are_classified_as_api_key(db):
    db.add(
        McpServer(
            name="Header-auth server",
            transport="http",
            url="https://mcp.example.test",
            headers=json.dumps({"Authorization": "Bearer {{credential_value}}"}),
            enabled=False,
        )
    )
    await db.flush()
    rows = await list_servers(operator=Operator(id="op"), db=db)
    assert rows[0]["auth_type"] == "api_key"


async def test_oauth_catalog_install_is_oauth_only(db):
    """Exa is OAuth-only: ?login endpoint issues the challenge, no key path."""
    result = await install_from_catalog(
        InstallFromCatalogRequest(name="Exa"),
        operator=Operator(id="op"),
        db=db,
    )
    assert result["auth_type"] == "oauth"
    assert "oauth" in result["message"].lower()
    server = await db.get(McpServer, result["id"])
    assert server.oauth_config is not None
    assert server.url == "https://mcp.exa.ai/mcp?login"
    assert server.headers is None


async def test_create_server_honors_declared_oauth(db, monkeypatch):
    connect = AsyncMock(return_value=False)
    monkeypatch.setattr(registry, "connect_server", connect)
    result = await create_server(
        CreateServerRequest(
            name="exa",
            transport="http",
            url="https://mcp.exa.ai/mcp?login",
            auth="oauth",
        ),
        operator=Operator(id="op"),
        db=db,
    )
    server = await db.get(McpServer, result["id"])
    assert server.oauth_config is not None
    assert json.loads(server.oauth_config)["redirect_uri"].endswith("/api/mcp/oauth/callback")
    rows = await list_servers(operator=Operator(id="op"), db=db)
    assert rows[0]["auth_type"] == "oauth"


async def test_create_server_rejects_bad_or_unknown_fields(db):
    with pytest.raises(HTTPException) as error:
        await create_server(
            CreateServerRequest(name="bad", transport="http", url="https://x.test", auth="bearer"),
            operator=Operator(id="op"),
            db=db,
        )
    assert error.value.status_code == 422
    with pytest.raises(HTTPException):
        await create_server(
            CreateServerRequest(name="bad", transport="stdio", command="x", auth="oauth"),
            operator=Operator(id="op"),
            db=db,
        )
    # Silently-dropped config fields caused the OAuth setup bug — forbid them.
    with pytest.raises(ValidationError):
        CreateServerRequest(name="x", transport="http", url="https://x.test", typo_field=1)


async def test_create_server_moves_literal_header_secret_to_credential(db):
    """Pasted standard configs carry raw keys — move them to encrypted storage."""
    result = await create_server(
        CreateServerRequest(
            name="exa",
            transport="http",
            url="https://mcp.exa.ai/mcp",
            headers={"x-api-key": "exa-real-key-123", "Accept": "application/json"},
            enabled=False,
        ),
        operator=Operator(id="op"),
        db=db,
    )
    server = await db.get(McpServer, result["id"])
    headers = json.loads(server.headers)
    # Secret is templated; non-secret header is left alone; plaintext is gone.
    assert headers == {
        "x-api-key": "{{credential_value}}",
        "Accept": "application/json",
    }
    assert "exa-real-key-123" not in server.headers
    rows = await credentials.list_credentials(db, server.id)
    assert len(rows) == 1
    assert rows[0].credential_type == "api_key"
    assert credentials.decrypt_credential(rows[0]) == "exa-real-key-123"
    listed = await list_servers(operator=Operator(id="op"), db=db)
    assert listed[0]["auth_type"] == "api_key"
    assert listed[0]["has_credentials"] is True


async def test_create_server_templates_placeholder_key(db):
    """Placeholder values ("YOUR_API_KEY") template but store no credential."""
    result = await create_server(
        CreateServerRequest(
            name="exa",
            transport="http",
            url="https://mcp.exa.ai/mcp",
            headers={"x-api-key": "YOUR_EXA_API_KEY"},
            enabled=False,
        ),
        operator=Operator(id="op"),
        db=db,
    )
    server = await db.get(McpServer, result["id"])
    assert json.loads(server.headers) == {"x-api-key": "{{credential_value}}"}
    assert await credentials.list_credentials(db, server.id) == []
    listed = await list_servers(operator=Operator(id="op"), db=db)
    assert listed[0]["auth_type"] == "api_key"
    assert listed[0]["has_credentials"] is False


async def test_create_server_accepts_standard_env_field(db):
    """Standard MCP format spells it "env" — accept it and secure secrets."""
    result = await create_server(
        CreateServerRequest(
            name="brave",
            transport="stdio",
            command="npx",
            args=["-y", "@brave/mcp"],
            env={"BRAVE_API_KEY": "b-key-1", "LOG_LEVEL": "debug"},
            enabled=False,
        ),
        operator=Operator(id="op"),
        db=db,
    )
    server = await db.get(McpServer, result["id"])
    env = json.loads(server.env_template)
    assert env == {"BRAVE_API_KEY": "{{credential_value}}", "LOG_LEVEL": "debug"}
    rows = await credentials.list_credentials(db, server.id)
    assert len(rows) == 1
    assert credentials.decrypt_credential(rows[0]) == "b-key-1"


async def test_create_server_leaves_plain_configs_alone(db):
    """No secret-named fields → config stored verbatim, auth stays none."""
    result = await create_server(
        CreateServerRequest(
            name="ctx7",
            transport="http",
            url="https://mcp.context7.com/mcp",
            headers={"Accept": "application/json"},
            enabled=False,
        ),
        operator=Operator(id="op"),
        db=db,
    )
    server = await db.get(McpServer, result["id"])
    assert json.loads(server.headers) == {"Accept": "application/json"}
    assert await credentials.list_credentials(db, server.id) == []
    listed = await list_servers(operator=Operator(id="op"), db=db)
    assert listed[0]["auth_type"] == "none"


async def test_update_server_switches_auth(db):
    server = McpServer(name="exa", transport="http", url="https://mcp.exa.ai/mcp", enabled=False)
    db.add(server)
    await db.flush()
    await update_server(
        server.id, UpdateServerRequest(auth="oauth"), operator=Operator(id="op"), db=db
    )
    assert server.oauth_config is not None
    await update_server(
        server.id, UpdateServerRequest(auth="api_key"), operator=Operator(id="op"), db=db
    )
    assert server.oauth_config is None


@pytest.mark.parametrize(
    "name",
    [
        "Brave Search",
        "Tavily",
        "Context7",
        "Perplexity",
        "Firecrawl",
    ],
)
async def test_catalog_install_stores_key_encrypted_before_connect(db, monkeypatch, name):
    key = "synthetic-mcp-secret"

    async def connect(server):
        rows = await credentials.list_credentials(db, server.id)
        assert len(rows) == 1
        assert rows[0].encrypted_value != key
        assert credentials.decrypt_credential(rows[0]) == key
        env, headers = credentials.inject_credential(
            json.loads(server.env_template or "{}"),
            json.loads(server.headers or "{}"),
            key,
        )
        assert key in " ".join([*env.values(), *headers.values()])
        return False  # Failed connection must not discard the saved key.

    connect_mock = AsyncMock(side_effect=connect)
    monkeypatch.setattr(registry, "connect_server", connect_mock)
    req = InstallFromCatalogRequest(name=name, api_key=key)
    assert key not in repr(req)
    result = await install_from_catalog(req, operator=Operator(id="op"), db=db)
    connect_mock.assert_awaited_once()
    server = await db.get(McpServer, result["id"])
    assert key not in json.dumps(result)
    assert key not in (server.headers or "") + (server.env_template or "") + (server.url or "")
    assert not result["connected"]
    assert "failed" in result["message"].lower()
    assert await db.scalar(select(ContactMcpBinding)) is None


async def test_setup_later_never_connects_without_a_key(db, monkeypatch):
    connect = AsyncMock()
    monkeypatch.setattr(registry, "connect_server", connect)
    await install_from_catalog(
        InstallFromCatalogRequest(name="Tavily"),
        operator=Operator(id="op"),
        db=db,
    )
    connect.assert_not_awaited()
    assert await db.scalar(select(McpServerCredential)) is None


@pytest.mark.parametrize(
    "name,key",
    [
        ("Fetch", "secret"),
        ("Exa", "perfectly-fine-key"),  # OAuth-only: keys are not accepted.
        ("Exa", " "),
        ("Exa", "key\ninjection"),
    ],
)
async def test_invalid_key_install_has_no_partial_server(db, name, key):
    with pytest.raises(HTTPException) as error:
        await install_from_catalog(
            InstallFromCatalogRequest(name=name, api_key=key),
            operator=Operator(id="op"),
            db=db,
        )
    assert error.value.status_code == 422
    assert await db.scalar(select(McpServer)) is None
    assert await db.scalar(select(McpServerCredential)) is None


@pytest.mark.parametrize(
    "name,url,expected_auth",
    [
        ("Tavily", "https://mcp.tavily.com/mcp/", "api_key"),
        ("Tavily", "https://custom.example.test/mcp", "none"),
        # OAuth-only catalog entry: no template recovery on either URL variant.
        ("Exa", "https://mcp.exa.ai/mcp", "none"),
        ("Exa", "https://mcp.exa.ai/mcp?login", "none"),
    ],
)
async def test_legacy_install_key_setup_repairs_only_the_exact_catalog_endpoint(
    db,
    name,
    url,
    expected_auth,
):
    server = McpServer(name=name, transport="http", url=url, enabled=False)
    db.add(server)
    await db.flush()
    rows = await list_servers(operator=Operator(id="op"), db=db)
    assert rows[0]["auth_type"] == expected_auth
    assert server.headers is None  # Listing must not mutate configuration.
    await store_server_credential(
        server.id,
        StoreCredentialRequest(credential_type="api_key", value="synthetic-key"),
        operator=Operator(id="op"),
        db=db,
    )
    assert bool(server.headers) == (expected_auth == "api_key")


def test_every_keyed_catalog_entry_declares_runtime_injection():
    for entry in catalog.list_catalog_entries():
        if entry.get("auth_type") == "api_key":
            templates = (
                entry.get("headers") if entry["transport"] == "http" else entry.get("env_template")
            )
            assert templates and "{{credential_value}}" in json.dumps(templates), entry["name"]
