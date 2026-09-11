"""Regression tests for MCP OAuth automatic token refresh.

These tests exercise CaberOSOAuthProvider against mocked HTTP responses to
ensure an expired access token is refreshed without forcing the operator
through a full interactive re-authorization.
"""

from __future__ import annotations

import httpx2
import pytest

from agentos.mcp.oauth import CaberOSOAuthProvider, EncryptedTokenStorage
from agentos.models.mcp import McpServer


def _make_memory_storage(
    tokens=None, client_info=None, oauth_metadata=None, protected_resource_metadata=None
):
    """Return a minimal in-memory TokenStorage for isolated OAuth tests."""

    class _MemoryStorage:
        def __init__(self):
            self.tokens = tokens
            self.client_info = client_info
            self.oauth_metadata = oauth_metadata
            self.protected_resource_metadata = protected_resource_metadata

        async def get_tokens(self):
            return self.tokens

        async def set_tokens(self, tokens) -> None:
            self.tokens = tokens

        async def get_client_info(self):
            return self.client_info

        async def set_client_info(self, client_info) -> None:
            self.client_info = client_info

        async def get_oauth_metadata(self):
            return self.oauth_metadata

        async def set_oauth_metadata(self, metadata) -> None:
            self.oauth_metadata = metadata

        async def get_protected_resource_metadata(self):
            return self.protected_resource_metadata

        async def set_protected_resource_metadata(self, metadata) -> None:
            self.protected_resource_metadata = metadata

    return _MemoryStorage()


@pytest.mark.asyncio
async def test_oauth_refresh_window_forces_refresh():
    """CaberOSOAuthProvider marks an expired token invalid so refresh runs."""
    from mcp.shared.auth import OAuthClientInformationFull, OAuthClientMetadata, OAuthToken

    storage = _make_memory_storage(
        tokens=OAuthToken(
            access_token="old",
            token_type="Bearer",
            expires_in=0,
            refresh_token="rt",
            scope="read",
        ),
        client_info=OAuthClientInformationFull(
            client_id="client-123",
            token_endpoint_auth_method="none",
            redirect_uris=["http://localhost:8081/api/mcp/oauth/callback"],
            grant_types=["authorization_code", "refresh_token"],
            response_types=["code"],
        ),
    )

    auth = CaberOSOAuthProvider(
        server_url="http://example.com/mcp",
        client_metadata=OAuthClientMetadata(
            redirect_uris=["http://localhost:8081/api/mcp/oauth/callback"],
            token_endpoint_auth_method="none",
            grant_types=["authorization_code", "refresh_token"],
            response_types=["code"],
            client_name="CaberOS",
            scope="read",
        ),
        storage=storage,
        redirect_handler=lambda url: None,
        callback_handler=lambda: None,
    )

    await auth._initialize()

    assert auth.context.token_expiry_time != 0
    assert not auth.context.is_token_valid()
    assert auth.context.can_refresh_token()


@pytest.mark.asyncio
async def test_oauth_refresh_with_stored_metadata():
    """CaberOSOAuthProvider refreshes using the stored token endpoint."""
    from mcp.shared.auth import (
        OAuthClientInformationFull,
        OAuthClientMetadata,
        OAuthMetadata,
        OAuthToken,
        ProtectedResourceMetadata,
    )

    server_url = "http://example.com/mcp"
    token_url = "http://example.com/auth/token"

    oauth_metadata = OAuthMetadata(
        issuer="http://example.com/auth",
        authorization_endpoint="http://example.com/auth/authorize",
        token_endpoint=token_url,
        scopes_supported=["read"],
        response_types_supported=["code"],
        grant_types_supported=["authorization_code", "refresh_token"],
        token_endpoint_auth_methods_supported=["none"],
        code_challenge_methods_supported=["S256"],
    )
    protected_resource_metadata = ProtectedResourceMetadata(
        resource=server_url,
        authorization_servers=["http://example.com/auth"],
    )
    client_info = OAuthClientInformationFull(
        client_id="client-123",
        token_endpoint_auth_method="none",
        redirect_uris=["http://localhost:8081/api/mcp/oauth/callback"],
        grant_types=["authorization_code", "refresh_token"],
        response_types=["code"],
    )

    storage = _make_memory_storage(
        tokens=OAuthToken(
            access_token="old-expired-token",
            token_type="Bearer",
            expires_in=0,
            refresh_token="refresh-456",
            scope="read",
        ),
        client_info=client_info,
        oauth_metadata=oauth_metadata,
        protected_resource_metadata=protected_resource_metadata,
    )

    auth = CaberOSOAuthProvider(
        server_url=server_url,
        client_metadata=OAuthClientMetadata(
            redirect_uris=["http://localhost:8081/api/mcp/oauth/callback"],
            token_endpoint_auth_method="none",
            grant_types=["authorization_code", "refresh_token"],
            response_types=["code"],
            client_name="CaberOS",
            scope="read",
        ),
        storage=storage,
        redirect_handler=lambda url: None,
        callback_handler=lambda: None,
    )

    def handler(request: httpx2.Request) -> httpx2.Response:
        url = str(request.url)

        if url == token_url:
            return httpx2.Response(
                200,
                json={
                    "access_token": "new-access-token-12345",
                    "token_type": "Bearer",
                    "expires_in": 3600,
                    "refresh_token": "refresh-999",
                    "scope": "read",
                },
            )

        if url == server_url:
            auth_header = request.headers.get("Authorization", "")
            if auth_header == "Bearer new-access-token-12345":
                return httpx2.Response(
                    200,
                    json={
                        "jsonrpc": "2.0",
                        "id": 1,
                        "result": {"protocolVersion": "2024-11-05", "capabilities": {}},
                    },
                )
            return httpx2.Response(
                401,
                headers={
                    "WWW-Authenticate": (
                        'Bearer error="invalid_token", '
                        'resource_metadata="http://example.com/.well-known/oauth-protected-resource/mcp"'
                    )
                },
            )

        return httpx2.Response(404, text="not found")

    transport = httpx2.MockTransport(handler)
    async with httpx2.AsyncClient(auth=auth, transport=transport) as client:
        response = await client.post(
            server_url,
            json={"jsonrpc": "2.0", "method": "initialize", "id": 1},
            headers={"Content-Type": "application/json"},
        )

    assert response.status_code == 200
    assert storage.tokens is not None
    assert storage.tokens.access_token == "new-access-token-12345"


@pytest.mark.asyncio
async def test_oauth_token_expiry_not_treated_as_no_expiry():
    """The token_expiry_time sentinel must not be 0/falsy."""
    from mcp.client.auth.oauth2 import OAuthContext
    from mcp.shared.auth import OAuthClientMetadata, OAuthToken

    context = OAuthContext(
        server_url="http://example.com/mcp",
        client_metadata=OAuthClientMetadata(
            redirect_uris=["http://localhost:8081/api/mcp/oauth/callback"],
            token_endpoint_auth_method="none",
            grant_types=["authorization_code", "refresh_token"],
            response_types=["code"],
            client_name="CaberOS",
            scope="read",
        ),
        storage=_make_memory_storage(),
        redirect_handler=lambda url: None,
        callback_handler=lambda: None,
    )
    context.current_tokens = OAuthToken(
        access_token="old",
        token_type="Bearer",
        expires_in=0,
        refresh_token="rt",
        scope="read",
    )

    # This is the old (broken) behavior: token_expiry_time=0 is falsy,
    # so is_token_valid() returns True even though the token has expired.
    context.token_expiry_time = 0
    assert context.is_token_valid() is True

    # A non-zero past timestamp is correctly treated as expired.
    import time

    context.token_expiry_time = time.time() - 1
    assert context.is_token_valid() is False


@pytest.mark.asyncio
async def test_oauth_metadata_storage_roundtrip(db, monkeypatch):
    """EncryptedTokenStorage can persist and reload OAuth metadata."""
    from mcp.shared.auth import OAuthMetadata, ProtectedResourceMetadata

    server = McpServer(
        name="oauth-metadata-test",
        transport="http",
        url="http://example.com/mcp",
    )
    db.add(server)
    await db.commit()

    class TestSessionFactory:
        def __call__(self):
            class TestSession:
                async def __aenter__(self):
                    return db

                async def __aexit__(self, *args):
                    pass

            return TestSession()

    import agentos.mcp.oauth

    monkeypatch.setattr(agentos.mcp.oauth, "async_session_factory", TestSessionFactory())

    storage = EncryptedTokenStorage(server.id)

    oauth_metadata = OAuthMetadata(
        issuer="http://example.com/auth",
        authorization_endpoint="http://example.com/auth/authorize",
        token_endpoint="http://example.com/auth/token",
        scopes_supported=["read"],
    )
    protected_resource_metadata = ProtectedResourceMetadata(
        resource=server.url,
        authorization_servers=["http://example.com/auth"],
    )

    await storage.set_oauth_metadata(oauth_metadata)
    await storage.set_protected_resource_metadata(protected_resource_metadata)

    loaded_oauth = await storage.get_oauth_metadata()
    loaded_prm = await storage.get_protected_resource_metadata()

    assert loaded_oauth is not None
    assert str(loaded_oauth.issuer).rstrip("/") == "http://example.com/auth"
    assert str(loaded_oauth.token_endpoint).rstrip("/") == "http://example.com/auth/token"
    assert loaded_prm is not None
    assert str(loaded_prm.resource).rstrip("/") == "http://example.com/mcp"
