"""Subject binding — links a Contact to an MCP server instance (D8).

When a subject-scoped mcp_tool is called, the syscall layer resolves the
Contact's binding to find which MCP server + credential to use. Unbound
Contacts are denied (fail closed).
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.mcp import ContactMcpBinding, McpServer, McpServerCredential


async def create_binding(
    db: AsyncSession,
    contact_id: str,
    mcp_server_id: str,
    credential_id: str,
) -> ContactMcpBinding:
    """Bind a Contact to an MCP server with a specific credential."""
    binding = ContactMcpBinding(
        contact_id=contact_id,
        mcp_server_id=mcp_server_id,
        credential_id=credential_id,
    )
    db.add(binding)
    await db.flush()
    return binding


async def get_binding(
    db: AsyncSession,
    contact_id: str,
    mcp_server_id: str,
) -> ContactMcpBinding | None:
    """Get the binding for a Contact + MCP server pair."""
    result = await db.execute(
        select(ContactMcpBinding).where(
            ContactMcpBinding.contact_id == contact_id,
            ContactMcpBinding.mcp_server_id == mcp_server_id,
        )
    )
    return result.scalar_one_or_none()


async def list_bindings(db: AsyncSession, mcp_server_id: str | None = None) -> list[dict]:
    """List bindings, optionally filtered by server."""
    query = select(ContactMcpBinding)
    if mcp_server_id:
        query = query.where(ContactMcpBinding.mcp_server_id == mcp_server_id)
    result = await db.execute(query)
    bindings = []
    for b in result.scalars().all():
        bindings.append(
            {
                "id": b.id,
                "contact_id": b.contact_id,
                "mcp_server_id": b.mcp_server_id,
                "credential_id": b.credential_id,
                "created_at": b.created_at.isoformat() if b.created_at else None,
            }
        )
    return bindings


async def delete_binding(db: AsyncSession, binding_id: str) -> bool:
    """Delete a binding. Returns True if deleted."""
    result = await db.execute(
        select(ContactMcpBinding).where(ContactMcpBinding.id == binding_id)
    )
    binding = result.scalar_one_or_none()
    if binding is None:
        return False
    await db.delete(binding)
    await db.flush()
    return True


async def resolve_binding(
    db: AsyncSession,
    contact_id: str,
    mcp_server_id: str,
) -> tuple[ContactMcpBinding, McpServer, McpServerCredential] | None:
    """Resolve a Contact's binding to an MCP server.

    Returns (binding, server, credential) or None if unbound.
    """
    binding = await get_binding(db, contact_id, mcp_server_id)
    if binding is None:
        return None

    server_result = await db.execute(
        select(McpServer).where(McpServer.id == mcp_server_id)
    )
    server = server_result.scalar_one_or_none()
    if server is None:
        return None

    cred_result = await db.execute(
        select(McpServerCredential).where(McpServerCredential.id == binding.credential_id)
    )
    cred = cred_result.scalar_one_or_none()
    if cred is None:
        return None

    return binding, server, cred
