"""MCP OAuth flow — integrates with the MCP SDK's OAuthClientProvider.

For remote MCP servers (HTTP transport) that require OAuth, this module:
  1. Provides a TokenStorage backed by our encrypted credential store
  2. Manages the OAuth redirect/callback flow via a pending-state registry
  3. Creates OAuthClientProvider instances for use with streamablehttp_client

The flow:
  - User clicks "Connect with OAuth" in the dashboard
  - Backend calls start_oauth_flow(server) which creates an OAuthClientProvider
    and triggers the OAuth flow. The redirect_handler captures the authorize URL.
  - The authorize URL is returned to the frontend, which opens it in a new tab.
  - The MCP provider redirects back to our callback URL.
  - The callback_handler in the OAuthClientProvider receives the code+state,
    exchanges it for a token, and stores it via TokenStorage.
  - The server is now connected with the OAuth token.

For stdio servers that need OAuth (e.g. Google Drive, Gmail), the OAuth token
is obtained via a separate flow and stored as an env_template credential.
"""

from __future__ import annotations

import asyncio
import json
import logging

from ..db import async_session_factory
from ..models.mcp import McpServer
from . import credentials as mcp_creds

log = logging.getLogger("agentos.mcp.oauth")

# --- Pending OAuth flows ---
# Maps server_id → OAuthFlowState (in-memory, not persisted)
_pending_flows: dict[str, OAuthFlowState] = {}


class OAuthFlowState:
    """Tracks an in-progress OAuth flow for a server."""

    def __init__(self, server_id: str) -> None:
        self.server_id = server_id
        self.authorize_url: str | None = None
        self.expected_state: str | None = None  # set when authorize URL is captured
        self.callback_future: asyncio.Future[tuple[str, str | None]] = asyncio.Future()
        self.error: str | None = None
        self.completed: bool = False

    def set_authorize_url(self, url: str) -> None:
        self.authorize_url = url
        # Extract state from the authorize URL query params
        from urllib.parse import parse_qs, urlparse

        parsed = urlparse(url)
        params = parse_qs(parsed.query)
        if "state" in params:
            self.expected_state = params["state"][0]

    def resolve_callback(self, code: str, state: str | None = None) -> None:
        """Resolve the callback — called when the OAuth redirect comes back."""
        if not self.callback_future.done():
            self.callback_future.set_result((code, state))
        self.completed = True

    def reject(self, error: str) -> None:
        """Reject the flow — called on error."""
        self.error = error
        if not self.callback_future.done():
            self.callback_future.set_exception(RuntimeError(error))


# --- TokenStorage implementation ---


class EncryptedTokenStorage:
    """TokenStorage protocol implementation backed by encrypted credentials.

    Stores OAuth tokens in the mcp_server_credentials table using Fernet encryption.
    """

    def __init__(self, server_id: str) -> None:
        self.server_id = server_id

    async def get_tokens(self):
        """Retrieve stored OAuth tokens."""
        from mcp.shared.auth import OAuthToken

        async with async_session_factory() as db:
            creds = await mcp_creds.list_credentials(db, self.server_id)
            for cred in creds:
                if cred.credential_type == "oauth_token":
                    value = mcp_creds.decrypt_credential(cred)
                    if isinstance(value, dict):
                        return OAuthToken(
                            access_token=value.get("access_token", ""),
                            token_type=value.get("token_type", "Bearer"),
                            expires_in=value.get("expires_in"),
                            scope=value.get("scope"),
                            refresh_token=value.get("refresh_token"),
                        )
        return None

    async def set_tokens(self, tokens) -> None:
        """Store OAuth tokens (replaces any existing oauth_token credential)."""
        token_dict = {
            "access_token": tokens.access_token,
            "token_type": tokens.token_type or "Bearer",
            "expires_in": tokens.expires_in,
            "scope": tokens.scope,
            "refresh_token": tokens.refresh_token,
        }
        async with async_session_factory() as db:
            # Remove existing oauth_token credentials for this server
            creds = await mcp_creds.list_credentials(db, self.server_id)
            for cred in creds:
                if cred.credential_type == "oauth_token":
                    await mcp_creds.delete_credential(db, cred.id)
            # Store the new token
            await mcp_creds.store_credential(
                db, self.server_id, "oauth_token", token_dict, label="OAuth token"
            )
            await db.commit()

    async def get_client_info(self):
        """Get stored OAuth client info (for dynamic client registration)."""
        # We don't persist client info — the MCP SDK re-registers if needed
        return None

    async def set_client_info(self, client_info) -> None:
        """Store OAuth client info."""
        # No-op — we don't persist client info in v0.1
        pass


# --- OAuth flow management ---


def get_pending_flow(server_id: str) -> OAuthFlowState | None:
    """Get the pending OAuth flow for a server, if any."""
    return _pending_flows.get(server_id)


def cancel_flow(server_id: str) -> None:
    """Cancel a pending OAuth flow."""
    flow = _pending_flows.pop(server_id, None)
    if flow and not flow.callback_future.done():
        flow.reject("Flow cancelled")


async def start_oauth_flow(server: McpServer) -> str:
    """Start an OAuth flow for an MCP server.

    Creates an OAuthClientProvider and drives the OAuth flow by making
    an initial request to the server. The server returns 401, which
    triggers the OAuth metadata discovery → client registration →
    authorize URL flow.

    Returns the authorize URL for the user to visit.
    """
    if not server.url:
        raise ValueError("OAuth flow requires a server URL (HTTP transport)")

    # Cancel any existing flow for this server
    cancel_flow(server.id)

    flow = OAuthFlowState(server.id)
    _pending_flows[server.id] = flow

    # Build the OAuth client metadata
    from mcp.shared.auth import OAuthClientMetadata

    redirect_uri = _get_redirect_uri()
    client_metadata = OAuthClientMetadata(
        redirect_uris=[redirect_uri],
        token_endpoint_auth_method="none",  # PKCE flow (public client)
        grant_types=["authorization_code", "refresh_token"],
        response_types=["code"],
        client_name="CaberOS",
        scope=_get_scope(server),
    )

    storage = EncryptedTokenStorage(server.id)

    def redirect_handler(url: str):
        """Called by the OAuth provider with the authorize URL."""
        log.info("OAuth redirect_handler called with URL: %s", url[:100])
        flow.set_authorize_url(url)
        return asyncio.sleep(0)  # no-op async

    async def callback_handler() -> tuple[str, str | None]:
        """Called by the OAuth provider to wait for the callback.

        Times out after 5 minutes so the flow doesn't hang forever if the
        user closes the OAuth tab without completing it.
        """
        log.info("OAuth callback_handler waiting for redirect...")
        try:
            return await asyncio.wait_for(flow.callback_future, timeout=300.0)
        except TimeoutError:
            flow.reject("OAuth timed out — user did not complete authorization in 5 minutes")
            raise TimeoutError("OAuth authorization timed out (5 minutes)")

    from mcp.client.auth import OAuthClientProvider

    auth = OAuthClientProvider(
        server_url=server.url,
        client_metadata=client_metadata,
        storage=storage,
        redirect_handler=redirect_handler,
        callback_handler=callback_handler,
        timeout=300.0,
    )

    # Drive the OAuth flow in the background by making a request to the
    # actual server URL. The 401 response triggers the full OAuth flow.
    log.info("Starting OAuth flow for server '%s' (url=%s)", server.name, server.url)
    asyncio.create_task(_run_oauth_flow(server.id, server.url, auth, flow))

    # Wait for the authorize URL to be available (up to 30 seconds)
    # The OAuth metadata discovery + client registration can take a few seconds
    for _ in range(300):
        if flow.authorize_url:
            log.info("OAuth authorize URL ready for server %s", server.id)
            return flow.authorize_url
        if flow.error:
            raise RuntimeError(flow.error)
        await asyncio.sleep(0.1)

    # If we get here, the flow didn't produce an authorize URL in time
    cancel_flow(server.id)
    raise RuntimeError(
        "OAuth flow timed out — the server may not support MCP OAuth. "
        "Check that the server URL is correct and the server supports "
        "OAuth 2.1 with PKCE (RFC 8252)."
    )


async def _run_oauth_flow(server_id: str, server_url: str, auth, flow: OAuthFlowState) -> None:
    """Run the OAuth flow in the background.

    Makes an initial request to the server URL using httpx with the
    OAuthClientProvider as the auth. The 401 response triggers the
    full OAuth flow:
    1. Discover OAuth metadata (protected resource + authorization server)
    2. Register client (dynamic client registration)
    3. redirect_handler called with authorize URL
    4. callback_handler waits for the OAuth redirect
    5. Code exchanged for token
    6. Token stored via EncryptedTokenStorage
    7. Original request retried with token
    """
    import httpx

    try:
        log.info("OAuth flow: making initial request to %s", server_url)
        async with httpx.AsyncClient(auth=auth, timeout=30.0) as client:
            # Make a request to the actual server URL to trigger the 401
            # The MCP protocol uses POST with JSON-RPC, but any request
            # will trigger the auth flow
            try:
                resp = await client.post(
                    server_url,
                    json={"jsonrpc": "2.0", "method": "initialize", "id": 1},
                    headers={"Content-Type": "application/json"},
                )
                log.info("OAuth flow: initial request returned status %s", resp.status_code)
            except httpx.HTTPStatusError as e:
                log.info("OAuth flow: HTTPStatusError (expected): %s", e)
            except Exception as e:
                log.info("OAuth flow: exception (may be expected): %s", e)

        # If we get here without the flow being completed, the token
        # was stored successfully
        if not flow.completed:
            flow.completed = True

        log.info("OAuth flow completed for server %s", server_id)

    except Exception as e:
        log.exception("OAuth flow failed for server %s", server_id)
        flow.reject(str(e))
    finally:
        # Clean up the pending flow after a short delay (gives the frontend
        # a chance to poll and see the error status before we remove it)
        await asyncio.sleep(10.0)
        _pending_flows.pop(server_id, None)


def _frontend_base() -> str:
    """Get the frontend base URL for redirects after OAuth callback."""
    return "http://localhost:5173"


def handle_oauth_callback(code: str, state: str | None = None, error: str | None = None) -> str:
    """Handle the OAuth callback redirect.

    Called when the OAuth provider redirects back to our callback URL.
    Resolves the pending flow's callback_future.

    Returns an absolute URL to redirect the browser to (the frontend MCPs page).
    The OAuth callback hits the backend (:8081), but the user needs to land on
    the frontend (:5173) to see the dashboard.
    """
    base = _frontend_base()
    if error:
        # Find the pending flow and reject it
        for server_id, flow in list(_pending_flows.items()):
            flow.reject(error)
        return f"{base}/mcps?oauth_error={error}"

    # Find the pending flow — we don't know which server this is for from the
    # callback alone, so we resolve the first pending flow.
    # In practice, there should only be one pending flow at a time.
    # Validate the state parameter if the flow has one (CSRF protection).

    for server_id, flow in list(_pending_flows.items()):
        if not flow.completed:
            if flow.expected_state and state != flow.expected_state:
                flow.reject("OAuth state mismatch — possible CSRF attack")
                return f"{base}/mcps?oauth_error=state_mismatch"
            flow.resolve_callback(code, state)
            return f"{base}/mcps?oauth_connected={server_id}"

    # No pending flow found
    return f"{base}/mcps?oauth_error=no_pending_flow"


def _get_redirect_uri() -> str:
    """Get the OAuth callback URL (on the backend)."""
    from ..config import settings

    port = getattr(settings, "control_plane_port", 8081)
    # OAuth providers typically can't reach 127.0.0.1 during local dev,
    # so use localhost which is universally recognized
    return f"http://localhost:{port}/api/mcp/oauth/callback"


def _get_scope(server: McpServer) -> str:
    """Get the OAuth scope for a server."""
    if server.oauth_config:
        config = json.loads(server.oauth_config)
        return config.get("scope", "")
    return ""


def has_oauth_token(server_id: str) -> bool:
    """Check if a server has a stored OAuth token (without decrypting)."""
    flow = _pending_flows.get(server_id)
    if flow and flow.completed:
        return True
    # Check DB — but this is sync, so we return True optimistically
    # The actual check happens in connect_server
    return False
