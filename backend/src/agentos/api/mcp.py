"""MCP API routes — manage MCP servers, tools, credentials, and bindings.

Endpoints:
  GET    /api/mcp/servers              — list all MCP servers
  POST   /api/mcp/servers              — add an MCP server config
  DELETE /api/mcp/servers/{id}         — remove an MCP server (disconnects, unregisters)
  GET    /api/mcp/servers/{id}/tools   — list tools exposed by this server
  GET    /api/mcp/servers/{id}/agents  — which agents use this server (blast radius)
  POST   /api/mcp/servers/{id}/connect — manually connect/reconnect to the server
  POST   /api/mcp/servers/{id}/credentials — store a credential for the server
  GET    /api/mcp/servers/{id}/credentials — list credentials (without values)
  POST   /api/mcp/bindings             — bind a Contact to an MCP server
  GET    /api/mcp/bindings             — list bindings
  DELETE /api/mcp/bindings/{id}        — unbind
  GET    /api/mcp/catalog              — list catalog entries (browse marketplace)
  GET    /api/mcp/catalog/categories   — list categories with counts
  POST   /api/mcp/catalog/install      — install a server from the catalog by name
"""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import require_operator
from ..db import get_db
from ..mcp import binding as mcp_binding
from ..mcp import catalog as mcp_catalog
from ..mcp import credentials as mcp_creds
from ..capabilities.registry import registry as cap_registry
from ..mcp import registry as mcp_registry
from ..models.contact import Contact
from ..models.mcp import McpServer
from ..models.operator import Operator

router = APIRouter(prefix="/api/mcp", tags=["mcp"])


# --- Request models ---


class CreateServerRequest(BaseModel):
    name: str
    transport: str = "stdio"  # "stdio" or "http"
    command: str | None = None
    args: list[str] | None = None
    url: str | None = None
    headers: dict[str, str] | None = None
    env_template: dict[str, str] | None = None
    tool_filter: list[str] | None = None
    enabled: bool = True


class StoreCredentialRequest(BaseModel):
    credential_type: str  # "api_key", "bearer", "oauth_token"
    value: dict[str, Any] | str
    label: str | None = None


class CreateBindingRequest(BaseModel):
    contact_id: str
    mcp_server_id: str
    credential_id: str


class InstallFromCatalogRequest(BaseModel):
    name: str  # catalog entry name
    enabled: bool = True


# --- Server CRUD ---


@router.get("/servers")
async def list_servers(
    operator: Operator = Depends(require_operator),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """List all configured MCP servers with connection status and tool count."""
    result = await db.execute(select(McpServer).order_by(McpServer.name))
    servers = result.scalars().all()

    out = []
    for s in servers:
        tools = await mcp_registry.get_server_tools(db, s.id)
        env_template = json.loads(s.env_template) if s.env_template else None
        oauth_config = json.loads(s.oauth_config) if s.oauth_config else None
        creds = await mcp_creds.list_credentials(db, s.id)
        # Determine auth type for the frontend
        if oauth_config:
            auth_type = "oauth"
        elif env_template and any(
            "{{credential_value}}" in v for v in env_template.values()
        ):
            auth_type = "api_key"
        else:
            auth_type = "none"
        out.append(
            {
                "id": s.id,
                "name": s.name,
                "transport": s.transport,
                "command": s.command,
                "args": json.loads(s.args) if s.args else None,
                "url": s.url,
                "enabled": s.enabled,
                "connected": mcp_registry.is_server_connected(s.id),
                "tool_count": len(tools),
                "tool_filter": json.loads(s.tool_filter) if s.tool_filter else None,
                "require_approval": s.require_approval,
                "env_template": env_template,
                "oauth_config": oauth_config,
                "auth_type": auth_type,
                "has_credentials": len(creds) > 0,
                "created_at": s.created_at.isoformat() if s.created_at else None,
            }
        )
    return out


@router.post("/servers")
async def create_server(
    req: CreateServerRequest,
    operator: Operator = Depends(require_operator),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Add a new MCP server config and attempt to connect."""
    if req.transport == "stdio" and not req.command:
        raise HTTPException(status_code=400, detail="stdio transport requires a command")
    if req.transport == "http" and not req.url:
        raise HTTPException(status_code=400, detail="http transport requires a url")

    server = McpServer(
        name=req.name,
        transport=req.transport,
        command=req.command,
        args=json.dumps(req.args) if req.args else None,
        url=req.url,
        headers=json.dumps(req.headers) if req.headers else None,
        env_template=json.dumps(req.env_template) if req.env_template else None,
        tool_filter=json.dumps(req.tool_filter) if req.tool_filter else None,
        enabled=req.enabled,
    )
    db.add(server)
    await db.commit()
    await db.refresh(server)

    # Attempt to connect immediately
    if req.enabled:
        await mcp_registry.connect_server(server)

    return {
        "id": server.id,
        "name": server.name,
        "transport": server.transport,
        "connected": mcp_registry.is_server_connected(server.id),
    }


@router.delete("/servers/{server_id}")
async def delete_server(
    server_id: str,
    operator: Operator = Depends(require_operator),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Remove an MCP server — disconnects, unregisters tools, deletes credentials."""
    result = await db.execute(select(McpServer).where(McpServer.id == server_id))
    server = result.scalar_one_or_none()
    if server is None:
        raise HTTPException(status_code=404, detail="MCP server not found")

    # Disconnect and unregister tools
    await mcp_registry.disconnect_server(server_id)

    # Delete all credentials
    await mcp_creds.delete_server_credentials(db, server_id)

    # Delete the server
    await db.delete(server)
    await db.commit()

    return {"id": server_id, "deleted": True}


class UpdateServerRequest(BaseModel):
    require_approval: bool | None = None
    enabled: bool | None = None


@router.patch("/servers/{server_id}")
async def update_server(
    server_id: str,
    req: UpdateServerRequest,
    operator: Operator = Depends(require_operator),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Update an MCP server config (require_approval, enabled)."""
    result = await db.execute(select(McpServer).where(McpServer.id == server_id))
    server = result.scalar_one_or_none()
    if server is None:
        raise HTTPException(status_code=404, detail="MCP server not found")

    reconnect_needed = False

    if req.require_approval is not None:
        server.require_approval = req.require_approval
        # Update all registered tools' require_approval flag
        from ..models.mcp import McpTool

        tool_result = await db.execute(
            select(McpTool).where(McpTool.mcp_server_id == server_id)
        )
        tools = tool_result.scalars().all()
        for tool in tools:
            tool.require_approval = req.require_approval
            # Update the in-memory capability registry
            cap = cap_registry._caps.get(tool.capability_name)
            if cap:
                cap.require_approval = req.require_approval

    if req.enabled is not None and req.enabled != server.enabled:
        server.enabled = req.enabled
        reconnect_needed = True

    await db.commit()

    # Reconnect/disconnect if enabled state changed
    if reconnect_needed:
        if req.enabled:
            await mcp_registry.connect_server(server)
        else:
            await mcp_registry.disconnect_server(server_id)

    return {
        "id": server.id,
        "require_approval": server.require_approval,
        "enabled": server.enabled,
        "connected": mcp_registry.is_server_connected(server.id),
    }


@router.get("/servers/{server_id}/tools")
async def list_server_tools(
    server_id: str,
    operator: Operator = Depends(require_operator),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """List tools exposed by an MCP server."""
    tools = await mcp_registry.get_server_tools(db, server_id)
    return [
        {
            "id": t.id,
            "tool_name": t.tool_name,
            "capability_name": t.capability_name,
            "description": t.description,
            "parameters_schema": json.loads(t.parameters_schema),
            "egress": t.egress,
            "require_approval": t.require_approval,
            "subject_scoped": t.subject_scoped,
        }
        for t in tools
    ]


@router.get("/servers/{server_id}/agents")
async def server_blast_radius(
    server_id: str,
    operator: Operator = Depends(require_operator),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """Which agents use this MCP server (blast radius, story 17)."""
    return await mcp_registry.get_server_blast_radius(db, server_id)


@router.post("/servers/{server_id}/connect")
async def connect_server(
    server_id: str,
    operator: Operator = Depends(require_operator),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Manually connect (or reconnect) to an MCP server."""
    result = await db.execute(select(McpServer).where(McpServer.id == server_id))
    server = result.scalar_one_or_none()
    if server is None:
        raise HTTPException(status_code=404, detail="MCP server not found")

    # Disconnect first if already connected
    if mcp_registry.is_server_connected(server_id):
        await mcp_registry.disconnect_server(server_id)

    success = await mcp_registry.connect_server(server)
    return {"id": server_id, "connected": success}


# --- Credentials ---


@router.post("/servers/{server_id}/credentials")
async def store_server_credential(
    server_id: str,
    req: StoreCredentialRequest,
    operator: Operator = Depends(require_operator),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Store an encrypted credential for an MCP server.

    If reconnect=true (default), attempts to reconnect the server after
    storing the credential. Returns the connection status.
    """
    result = await db.execute(select(McpServer).where(McpServer.id == server_id))
    server = result.scalar_one_or_none()
    if server is None:
        raise HTTPException(status_code=404, detail="MCP server not found")

    cred = await mcp_creds.store_credential(
        db, server_id, req.credential_type, req.value, req.label
    )
    await db.commit()

    # Attempt reconnect with the new credential
    connected = False
    if server.enabled:
        # Disconnect first if currently connected (to restart with new cred)
        if mcp_registry.is_server_connected(server_id):
            await mcp_registry.disconnect_server(server_id)
        await mcp_registry.connect_server(server)
        connected = mcp_registry.is_server_connected(server_id)

    return {
        "id": cred.id,
        "credential_type": cred.credential_type,
        "label": cred.label,
        "connected": connected,
    }


@router.get("/servers/{server_id}/credentials")
async def list_server_credentials(
    server_id: str,
    operator: Operator = Depends(require_operator),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """List credentials for a server (without the encrypted values)."""
    creds = await mcp_creds.list_credentials(db, server_id)
    return [
        {
            "id": c.id,
            "credential_type": c.credential_type,
            "label": c.label,
            "created_at": c.created_at.isoformat() if c.created_at else None,
        }
        for c in creds
    ]


@router.delete("/servers/{server_id}/credentials/{credential_id}")
async def delete_server_credential(
    server_id: str,
    credential_id: str,
    operator: Operator = Depends(require_operator),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Delete a credential from an MCP server."""
    deleted = await mcp_creds.delete_credential(db, credential_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Credential not found")
    await db.commit()
    return {"deleted": True}


# --- OAuth ---


@router.post("/servers/{server_id}/oauth/start")
async def start_oauth(
    server_id: str,
    operator: Operator = Depends(require_operator),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Start an OAuth flow for an MCP server.

    Returns the authorize URL that the user should visit in their browser.
    """
    from ..mcp.oauth import start_oauth_flow

    result = await db.execute(select(McpServer).where(McpServer.id == server_id))
    server = result.scalar_one_or_none()
    if server is None:
        raise HTTPException(status_code=404, detail="MCP server not found")

    try:
        authorize_url = await start_oauth_flow(server)
        return {"authorize_url": authorize_url}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.get("/oauth/callback")
async def oauth_callback(
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
):
    """Handle the OAuth callback redirect.

    This endpoint is called by the OAuth provider after the user authorizes.
    It resolves the pending OAuth flow and redirects back to the MCPs page.
    """
    from fastapi.responses import RedirectResponse

    from ..mcp.oauth import handle_oauth_callback

    redirect_path = handle_oauth_callback(code=code or "", state=state, error=error)
    return RedirectResponse(url=redirect_path, status_code=302)


@router.get("/servers/{server_id}/oauth/status")
async def oauth_status(
    server_id: str,
    operator: Operator = Depends(require_operator),
) -> dict:
    """Check the status of an OAuth flow for a server."""
    from ..mcp.oauth import get_pending_flow

    flow = get_pending_flow(server_id)
    if flow is None:
        return {"status": "none"}
    if flow.error:
        return {"status": "error", "error": flow.error}
    if flow.completed:
        return {"status": "completed"}
    return {"status": "pending", "authorize_url": flow.authorize_url}


# --- Bindings ---


@router.get("/bindings")
async def list_bindings(
    operator: Operator = Depends(require_operator),
    db: AsyncSession = Depends(get_db),
    server_id: str | None = None,
) -> list[dict]:
    """List Contact → MCP server bindings."""
    bindings = await mcp_binding.list_bindings(db, server_id)
    # Enrich with contact and server names
    out = []
    for b in bindings:
        contact_result = await db.execute(select(Contact).where(Contact.id == b["contact_id"]))
        contact = contact_result.scalar_one_or_none()
        server_result = await db.execute(select(McpServer).where(McpServer.id == b["mcp_server_id"]))
        server = server_result.scalar_one_or_none()
        out.append(
            {
                **b,
                "contact_name": contact.name if contact else "unknown",
                "server_name": server.name if server else "unknown",
            }
        )
    return out


@router.post("/bindings")
async def create_binding(
    req: CreateBindingRequest,
    operator: Operator = Depends(require_operator),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Bind a Contact to an MCP server with a specific credential."""
    # Verify the contact exists
    contact_result = await db.execute(select(Contact).where(Contact.id == req.contact_id))
    if contact_result.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="Contact not found")

    # Verify the server exists
    server_result = await db.execute(select(McpServer).where(McpServer.id == req.mcp_server_id))
    if server_result.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="MCP server not found")

    # Verify the credential exists
    cred = await mcp_creds.get_credential(db, req.credential_id)
    if cred is None:
        raise HTTPException(status_code=404, detail="Credential not found")

    binding = await mcp_binding.create_binding(
        db, req.contact_id, req.mcp_server_id, req.credential_id
    )
    await db.commit()
    return {
        "id": binding.id,
        "contact_id": binding.contact_id,
        "mcp_server_id": binding.mcp_server_id,
        "credential_id": binding.credential_id,
    }


@router.delete("/bindings/{binding_id}")
async def delete_binding(
    binding_id: str,
    operator: Operator = Depends(require_operator),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Unbind a Contact from an MCP server."""
    deleted = await mcp_binding.delete_binding(db, binding_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Binding not found")
    await db.commit()
    return {"id": binding_id, "deleted": True}


# --- Catalog (marketplace) ---


@router.get("/catalog")
async def list_catalog(
    operator: Operator = Depends(require_operator),
    category: str | None = None,
    q: str | None = None,
) -> list[dict]:
    """Browse the MCP server catalog (static curated list)."""
    return mcp_catalog.list_catalog_entries(category=category, query=q)


@router.get("/catalog/categories")
async def list_catalog_categories(
    operator: Operator = Depends(require_operator),
) -> list[dict]:
    """List catalog categories with server counts."""
    return mcp_catalog.list_categories()


@router.post("/catalog/install")
async def install_from_catalog(
    req: InstallFromCatalogRequest,
    operator: Operator = Depends(require_operator),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Install a server from the catalog by name (one-click install)."""
    entry = mcp_catalog.get_catalog_entry(req.name)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"Catalog entry '{req.name}' not found")

    # Check if a server with this name already exists
    result = await db.execute(select(McpServer).where(McpServer.name == req.name))
    if result.scalar_one_or_none() is not None:
        raise HTTPException(status_code=409, detail=f"Server '{req.name}' is already configured")

    # Create the server config from the catalog entry
    args_json = json.dumps(entry.get("args")) if entry.get("args") else None
    env_json = json.dumps(entry.get("env_template")) if entry.get("env_template") else None

    # Build oauth_config for OAuth servers
    oauth_config_json = None
    if entry.get("auth_type") == "oauth":
        oauth_config_json = json.dumps({
            "scope": entry.get("oauth_scope", ""),
            "redirect_uri": "http://localhost:8081/api/mcp/oauth/callback",
        })

    server = McpServer(
        name=entry["name"],
        transport=entry["transport"],
        command=entry.get("command"),
        args=args_json,
        url=entry.get("url"),
        env_template=env_json,
        oauth_config=oauth_config_json,
        enabled=req.enabled,
    )
    db.add(server)
    await db.commit()
    await db.refresh(server)

    # Attempt to connect (will fail gracefully if credentials are needed but not set)
    connect_msg = None
    if req.enabled:
        if entry.get("auth_type") == "api_key":
            connect_msg = "Server added. Configure API key to connect."
        elif entry.get("auth_type") == "oauth":
            connect_msg = "Server added. Click 'Connect with OAuth' to authorize."
        else:
            await mcp_registry.connect_server(server)
            if mcp_registry.is_server_connected(server.id):
                connect_msg = "Connected successfully."
            else:
                connect_msg = "Server added but connection failed."

    return {
        "id": server.id,
        "name": server.name,
        "connected": mcp_registry.is_server_connected(server.id),
        "auth_type": entry.get("auth_type"),
        "message": connect_msg,
    }
