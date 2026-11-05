"""Cached OAuth binding checks through the auth flow, without network access."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx2
import pytest
from mcp.client.auth.exceptions import OAuthFlowError
from mcp.shared.auth import (
    OAuthClientInformationFull,
    OAuthClientMetadata,
    OAuthMetadata,
    OAuthToken,
    ProtectedResourceMetadata,
)

from agentos.mcp.oauth import CaberOSOAuthProvider

SERVER = "https://resource.example/mcp"
ISSUER = "https://auth.example/issuer"
CALLBACK = "http://localhost:8081/api/mcp/oauth/callback"


def provider(*, resource=SERVER, issuer=ISSUER, client_issuer=ISSUER, metadata=True):
    storage = SimpleNamespace(
        get_tokens=AsyncMock(
            return_value=OAuthToken(
                access_token="dummy-access",
                refresh_token="dummy-refresh",
                token_type="Bearer",
                expires_in=0,
            )
        ),
        get_client_info=AsyncMock(
            return_value=OAuthClientInformationFull(
                client_id="dummy-client",
                issuer=client_issuer,
                redirect_uris=[CALLBACK],
                token_endpoint_auth_method="none",
            )
        ),
        get_oauth_metadata=AsyncMock(
            return_value=OAuthMetadata(
                issuer=issuer,
                authorization_endpoint=f"{issuer.rstrip('/')}/authorize",
                token_endpoint=f"{issuer.rstrip('/')}/token",
                response_types_supported=["code"],
            )
            if metadata
            else None
        ),
        get_protected_resource_metadata=AsyncMock(
            return_value=ProtectedResourceMetadata(
                resource=resource, authorization_servers=[ISSUER]
            )
            if metadata
            else None
        ),
    )
    return CaberOSOAuthProvider(
        server_url=SERVER,
        client_metadata=OAuthClientMetadata(
            redirect_uris=[CALLBACK], token_endpoint_auth_method="none"
        ),
        storage=storage,
        redirect_handler=AsyncMock(),
        callback_handler=AsyncMock(),
    )


@pytest.mark.parametrize(
    "kwargs",
    [
        {"resource": "https://other-resource.example/mcp"},
        {"issuer": "https://other-issuer.example/issuer"},
        {"client_issuer": "https://other-issuer.example/issuer"},
        {"client_issuer": ISSUER, "metadata": False},
    ],
)
async def test_cached_binding_mismatch_fails_before_any_request_and_on_retry(kwargs):
    auth = provider(**kwargs)
    requests = []

    def handle(request):
        requests.append(request)
        raise AssertionError("binding failure must precede every network request")

    async with httpx2.AsyncClient(auth=auth, transport=httpx2.MockTransport(handle)) as client:
        for _ in range(2):
            with pytest.raises(OAuthFlowError, match="binding validation") as error:
                await client.post(SERVER, json={"id": 1})
            assert "dummy-refresh" not in str(error.value)
            assert auth._initialized is False
            assert auth.context.current_tokens is None
    assert requests == []


async def test_bound_cross_origin_authorization_server_is_preserved():
    auth = provider()
    await auth._initialize()
    assert auth._initialized is True
    assert auth.context.auth_server_url == ISSUER
    assert str(auth.context.oauth_metadata.token_endpoint) == f"{ISSUER}/token"


async def test_legacy_root_issuer_trailing_slash_matches_sdk_rules():
    auth = provider(
        issuer="https://resource.example/",
        client_issuer="https://resource.example",
    )
    auth.context.storage.get_protected_resource_metadata.return_value = None
    await auth._initialize()
    assert auth._initialized is True
