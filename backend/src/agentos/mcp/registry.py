"""MCP server registry — manages connections, tool discovery, and capability registration.

On startup, the registry loads tool definitions from the DB into memory
(lazy mode). Servers are NOT auto-connected — they connect on first tool
call or when the user explicitly clicks "Connect" in the dashboard.

When a server connects (lazily or manually):
  1. Connects to the MCP server (stdio or HTTP)
  2. Discovers tools via list_tools()
  3. Registers each tool as a capability of kind "mcp_tool"
  4. Stores the tool metadata in the mcp_tools table

Tool names are namespaced: mcp.{server_name}.{tool_name}

The registry maintains a pool of McpClient instances (one per server config).
The syscall mediator calls execute_mcp_tool() to forward calls through the
appropriate client.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..capabilities.registry import CapabilityDef
from ..capabilities.registry import registry as cap_registry
from ..db import async_session_factory
from ..models.mcp import McpServer, McpTool
from . import credentials as mcp_creds
from .client import McpClient

log = logging.getLogger("agentos.mcp.registry")

# Process-global pool of connected MCP clients: {server_id: McpClient}
_clients: dict[str, McpClient] = {}

# Process-global map: {capability_name: (server_id, tool_name)}
_tool_map: dict[str, tuple[str, str]] = {}

# Process-global map: {server_id: error_message} for last connection error
_connect_errors: dict[str, str] = {}


def _namespace(server_name: str, tool_name: str) -> str:
    """Generate the capability name: mcp.{server_name}.{tool_name}"""
    # Sanitize server_name for namespace (lowercase, replace spaces/dots with _)
    safe = server_name.lower().replace(" ", "_").replace(".", "_")
    return f"mcp.{safe}.{tool_name}"


async def connect_server(server: McpServer) -> bool:
    """Connect to an MCP server and register its tools.

    Fetches stored credentials and renders env_template/header placeholders
    before connecting. For HTTP servers with OAuth, creates an OAuthClientProvider
    that uses stored OAuth tokens (refreshing if needed).

    Returns True on success, False on failure.
    NEVER raises — all errors are caught and logged so one server's failure
    doesn't affect others or crash the process.
    """
    # Clear previous error
    _connect_errors.pop(server.id, None)

    if server.id in _clients and _clients[server.id].connected:
        return True

    try:
        args = json.loads(server.args) if server.args else []
        env_template = json.loads(server.env_template) if server.env_template else {}
        headers = json.loads(server.headers) if server.headers else {}
        oauth_config = json.loads(server.oauth_config) if server.oauth_config else None

        # Fetch stored credential and render templates
        env: dict[str, str] = {}
        rendered_headers: dict[str, str] = headers.copy()
        auth = None

        if env_template or headers:
            async with async_session_factory() as db:
                creds = await mcp_creds.list_credentials(db, server.id)
                if creds:
                    # Use the most recent credential
                    cred_value = mcp_creds.decrypt_credential(creds[-1])
                    rendered_env, rendered_hdr = mcp_creds.inject_credential(
                        env_template if env_template else None,
                        headers if headers else None,
                        cred_value,
                    )
                    env = rendered_env
                    rendered_headers.update(rendered_hdr)
                else:
                    # No credential stored — pass template as-is (will likely fail)
                    env = env_template

        # For HTTP servers with OAuth config, set up the OAuthClientProvider
        if server.transport == "http" and oauth_config:
            from .oauth import EncryptedTokenStorage

            storage = EncryptedTokenStorage(server.id)

            # Check if we have a stored OAuth token
            tokens = await storage.get_tokens()
            if tokens:
                # We have a token — create the OAuth provider for auto-refresh
                from mcp.shared.auth import OAuthClientMetadata

                from .oauth import CaberOSOAuthProvider

                redirect_uri = oauth_config.get(
                    "redirect_uri",
                    "http://localhost:8081/api/mcp/oauth/callback",
                )
                client_metadata = OAuthClientMetadata(
                    redirect_uris=[redirect_uri],
                    token_endpoint_auth_method="none",
                    grant_types=["authorization_code", "refresh_token"],
                    response_types=["code"],
                    client_name="CaberOS",
                    scope=oauth_config.get("scope", ""),
                )

                # Provide no-op redirect/callback handlers so that if the
                # refresh token is expired, the provider logs a warning
                # instead of crashing with "No redirect handler provided".
                # The user will need to re-authenticate via the dashboard.
                async def _noop_redirect_handler(url: str):
                    log.warning(
                        "MCP server '%s' OAuth token expired and refresh failed. "
                        "Re-authenticate via the dashboard.",
                        server.name,
                    )
                    # Don't open a browser during auto-reconnect — just return.
                    # The MCP SDK expects this to be awaitable and return None.
                    return None

                async def _noop_callback_handler():
                    log.warning(
                        "MCP server '%s' OAuth callback requested during reconnect. "
                        "Re-authenticate via the dashboard.",
                        server.name,
                    )
                    # Raise a clean, identifiable error so the connection loop
                    # can catch it and log a single warning instead of a
                    # full traceback cascade through the exit stack.
                    raise ConnectionError(
                        f"MCP server '{server.name}' OAuth re-authentication required "
                        "— use the dashboard"
                    )

                auth = CaberOSOAuthProvider(
                    server_url=server.url,
                    client_metadata=client_metadata,
                    storage=storage,
                    redirect_handler=_noop_redirect_handler,
                    callback_handler=_noop_callback_handler,
                )
            else:
                # No OAuth token — the user needs to go through the OAuth flow
                log.info(
                    "MCP server '%s' requires OAuth — no token stored. "
                    "Use the 'Connect with OAuth' button in the dashboard.",
                    server.name,
                )
                return False

        client = McpClient(
            transport=server.transport,
            command=server.command,
            args=args,
            url=server.url,
            headers=rendered_headers,
            env=env,
            auth=auth,
        )
        await client.connect()
        _clients[server.id] = client

        # Discover and register tools
        await _discover_tools(server, client)
        log.info("Connected to MCP server '%s' (%s)", server.name, server.id)
        return True

    except ConnectionError as e:
        _connect_errors[server.id] = str(e)
        log.warning("Failed to connect to MCP server '%s': %s", server.name, e)
        # Clean up partial connection
        if server.id in _clients:
            try:
                await _clients[server.id].disconnect()
            except Exception:
                log.debug("Error cleaning up failed MCP connection for '%s'", server.name)
            del _clients[server.id]
        return False
    except Exception as e:
        _connect_errors[server.id] = str(e)
        log.exception("Failed to connect to MCP server '%s'", server.name)
        # Clean up partial connection
        if server.id in _clients:
            try:
                await _clients[server.id].disconnect()
            except Exception:
                log.exception("Error cleaning up failed MCP connection for '%s'", server.name)
            del _clients[server.id]
        return False


async def _discover_tools(server: McpServer, client: McpClient) -> None:
    """Discover tools from the MCP server and register them as capabilities."""
    tools = await client.list_tools()

    # Apply tool filter if set
    tool_filter = json.loads(server.tool_filter) if server.tool_filter else None
    if tool_filter:
        tools = [t for t in tools if t["name"] in tool_filter]

    async with async_session_factory() as db:
        # Clear old tool registrations for this server
        await db.execute(delete(McpTool).where(McpTool.mcp_server_id == server.id))

        for tool in tools:
            cap_name = _namespace(server.name, tool["name"])
            schema_json = json.dumps(tool["inputSchema"])

            # Store in DB
            mcp_tool = McpTool(
                mcp_server_id=server.id,
                tool_name=tool["name"],
                capability_name=cap_name,
                parameters_schema=schema_json,
                description=tool["description"],
                egress=True,  # MCP tools are external by default
                require_approval=server.require_approval,  # per-server setting
                subject_scoped=True,
            )
            db.add(mcp_tool)

            # Register in the capability registry
            cap_registry.register(
                CapabilityDef(
                    name=cap_name,
                    kind="mcp_tool",
                    description=tool["description"],
                    parameters_schema=tool["inputSchema"],
                    egress=True,
                    require_approval=server.require_approval,  # per-server setting
                    subject_scoped=True,
                    execute=None,  # Handled by the syscall mediator via execute_mcp_tool
                )
            )

            # Track in the tool map
            _tool_map[cap_name] = (server.id, tool["name"])

        await db.commit()

    # Auto-enable new MCP tools for all agents that have an explicit
    # capability list. Agents with capabilities=None already get all
    # tools (including new MCP ones) implicitly.
    await _auto_enable_mcp_tools(server, [t["name"] for t in tools])

    log.info("Discovered %d tools from '%s'", len(tools), server.name)


async def _auto_enable_mcp_tools(server: McpServer, tool_names: list[str]) -> None:
    """Add newly discovered MCP tools to agents with explicit capability lists.

    Agents with capabilities=None already get all tools implicitly, so we
    skip them. For agents with an explicit list, we append the new MCP
    capability names so they're available without manual enabling in
    Settings → Capabilities.
    """
    from ..agent_service import get_active_config, save_agent
    from ..config_schema import CapabilityGrant
    from ..models.agent import Agent

    cap_names = {_namespace(server.name, t) for t in tool_names}
    if not cap_names:
        return

    async with async_session_factory() as db:
        result = await db.execute(select(Agent))
        for agent in result.scalars().all():
            config = await get_active_config(db, agent.id)
            if config is None or config.capabilities is None:
                continue  # null = all tools, no action needed

            existing = {c.name for c in config.capabilities}
            new_caps = [
                CapabilityGrant(
                    name=name,
                    subject="none",
                    require_approval=server.require_approval,
                )
                for name in cap_names
                if name not in existing
            ]
            if new_caps:
                config.capabilities = list(config.capabilities) + new_caps
                await save_agent(db, config)
                log.info(
                    "Auto-enabled %d MCP tools from '%s' for agent '%s'",
                    len(new_caps),
                    server.name,
                    agent.id,
                )


async def disconnect_server(server_id: str) -> None:
    """Disconnect from an MCP server and unregister its tools from memory.

    Does NOT delete tool rows from the DB — they are persistent data that
    should survive restarts. On next startup, _discover_tools will refresh
    them for servers that connect successfully. Servers that fail to connect
    (e.g. expired OAuth) keep their stale tool definitions so they're not
    lost forever.

    NEVER raises — all errors are caught so a failed disconnect doesn't
    crash the process (e.g. during shutdown).
    """
    client = _clients.pop(server_id, None)
    if client:
        try:
            await client.disconnect()
        except Exception:
            log.exception("Error disconnecting from MCP server %s", server_id)

    # Unregister capabilities from the in-memory registry only.
    # Do NOT delete tool rows from the DB — they persist across restarts.
    async with async_session_factory() as db:
        result = await db.execute(select(McpTool).where(McpTool.mcp_server_id == server_id))
        tools = result.scalars().all()
        for tool in tools:
            cap_registry._caps.pop(tool.capability_name, None)
            _tool_map.pop(tool.capability_name, None)

    log.info("Disconnected from MCP server %s", server_id)


async def load_tools_from_db() -> None:
    """Load tool definitions from the DB into the in-memory capability registry.

    This is the lazy-load startup path: instead of connecting to every MCP
    server on startup (which causes OAuth errors, network timeouts, and
    slow startup), we just load the tool metadata that was previously
    discovered. Servers connect on demand when a tool is called, or when
    the user clicks "Connect" in the dashboard.
    """
    async with async_session_factory() as db:
        result = await db.execute(select(McpTool))
        tools = result.scalars().all()

    for tool in tools:
        _tool_map[tool.capability_name] = (tool.mcp_server_id, tool.tool_name)
        cap_registry.register(
            CapabilityDef(
                name=tool.capability_name,
                kind="mcp_tool",
                description=tool.description,
                parameters_schema=json.loads(tool.parameters_schema),
                egress=tool.egress,
                require_approval=tool.require_approval,
                subject_scoped=tool.subject_scoped,
            )
        )

    log.info("Loaded %d MCP tool definitions from DB (lazy mode)", len(tools))


async def connect_all() -> None:
    """Connect to all enabled MCP servers.

    Kept for backwards compatibility but no longer called at startup.
    Use load_tools_from_db() for the lazy startup path, and
    connect_server() for on-demand connections.
    """
    async with async_session_factory() as db:
        result = await db.execute(select(McpServer).where(McpServer.enabled))
        servers = result.scalars().all()

        # Check which servers have credentials
        server_creds: dict[str, bool] = {}
        for s in servers:
            env_template = json.loads(s.env_template) if s.env_template else {}
            headers = json.loads(s.headers) if s.headers else {}
            oauth_config = json.loads(s.oauth_config) if s.oauth_config else None
            needs_cred = any(
                "{{credential_value}}" in v or "{{credential." in v
                for v in list(env_template.values()) + list(headers.values())
            )
            if needs_cred or (s.transport == "http" and oauth_config):
                creds = await mcp_creds.list_credentials(db, s.id)
                server_creds[s.id] = len(creds) > 0
            else:
                server_creds[s.id] = True  # No credential needed

    for server in servers:
        if not server_creds.get(server.id, False):
            log.info("Skipping MCP server '%s' — no credentials configured", server.name)
            continue
        try:
            await connect_server(server)
        except ConnectionError as e:
            log.warning("MCP server '%s' skipped during startup: %s", server.name, e)
            continue
        except Exception:
            log.exception("Failed to connect to MCP server '%s' during startup", server.name)
            continue


async def disconnect_all() -> None:
    """Disconnect from all MCP servers on shutdown.

    NEVER raises — each disconnect is isolated.
    """
    for server_id in list(_clients.keys()):
        try:
            await disconnect_server(server_id)
        except Exception:
            log.exception("Error disconnecting MCP server %s during shutdown", server_id)


async def execute_mcp_tool(
    capability_name: str,
    args: dict[str, Any],
    env: dict[str, str] | None = None,
    headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Execute an MCP tool call through the appropriate client.

    Called by the syscall mediator after resolving the subject binding and
    injecting credentials. The env/headers here are the rendered credential
    values (already decrypted and templated).

    If the server is not connected, attempts a lazy connect first.

    Returns the MCP call result: {"content": [...], "isError": bool}
    """
    mapping = _tool_map.get(capability_name)
    if mapping is None:
        raise ValueError(f"MCP tool not found: {capability_name}")

    server_id, tool_name = mapping

    client = _clients.get(server_id)
    if client is None or not client.connected:
        # Lazy connect: load the server config and connect on demand
        async with async_session_factory() as db:
            result = await db.execute(select(McpServer).where(McpServer.id == server_id))
            server = result.scalar_one_or_none()
        if server is None:
            raise RuntimeError(f"MCP server not found: {server_id}")
        if not server.enabled:
            raise RuntimeError(f"MCP server '{server.name}' is disabled")
        success = await connect_server(server)
        if not success:
            err = _connect_errors.get(server_id, "unknown error")
            raise RuntimeError(
                f"MCP server '{server.name}' is not connected: {err}. Reconnect from the dashboard."
            )
        client = _clients.get(server_id)
        if client is None or not client.connected:
            raise RuntimeError(f"MCP server '{server.name}' failed to connect")

    # Note: env/headers injection for stdio requires restarting the process.
    # For v0.1, credentials are injected at server startup (env_template on
    # the server config). Per-call credential injection via headers is
    # supported for HTTP transport.
    return await client.call_tool(tool_name, args)


def get_connected_servers() -> dict[str, McpClient]:
    """Return the pool of connected clients (for status reporting)."""
    return _clients


def is_server_connected(server_id: str) -> bool:
    """Check if a server is currently connected."""
    client = _clients.get(server_id)
    return client is not None and client.connected


def get_connect_error(server_id: str) -> str | None:
    """Return the last connection error for a server, if any."""
    return _connect_errors.get(server_id)


async def get_server_tools(db: AsyncSession, server_id: str) -> list[McpTool]:
    """List tools registered for a server."""
    result = await db.execute(select(McpTool).where(McpTool.mcp_server_id == server_id))
    return list(result.scalars().all())


async def get_server_blast_radius(db: AsyncSession, server_id: str) -> list[dict]:
    """Get the list of agents that have capabilities from this server.

    Returns a list of {agent_id, agent_name, capabilities: [...]}.
    """
    from ..agent_service import get_active_config
    from ..models.agent import Agent

    # Get all capability names from this server
    result = await db.execute(select(McpTool).where(McpTool.mcp_server_id == server_id))
    tools = result.scalars().all()
    cap_names = {t.capability_name for t in tools}

    if not cap_names:
        return []

    # Find all agents that have any of these capabilities granted
    result = await db.execute(select(Agent).where(Agent.enabled))
    agents = result.scalars().all()

    blast = []
    for agent in agents:
        config = await get_active_config(db, agent.id)
        if config is None or config.capabilities is None:
            continue
        granted = {g.name for g in config.capabilities}
        used = cap_names & granted
        if used:
            blast.append(
                {
                    "agent_id": agent.id,
                    "agent_name": config.name,
                    "capabilities": sorted(used),
                }
            )
    return blast
