"""MCP credential management — encrypted storage and runtime injection.

Credentials are stored encrypted (Fernet) in the DB. At call time, the
syscall layer decrypts the credential and injects it as env vars or
headers into the MCP server process.

Credential types:
  - api_key: a single key string, injected as an env var
  - bearer: a token string, injected as a header (Authorization: Bearer ...)
  - oauth_token: JSON with access_token + refresh_token, injected as env var

The env_template on the MCP server config specifies how to inject the
credential. It's a JSON dict of {ENV_VAR_NAME: "{{credential_value}}"} or
{HEADER_NAME: "{{credential_value}}"}.
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.mcp import McpServerCredential
from ..secret_store import decrypt, encrypt


async def store_credential(
    db: AsyncSession,
    mcp_server_id: str,
    credential_type: str,
    value: dict[str, Any] | str,
    label: str | None = None,
) -> McpServerCredential:
    """Encrypt and store a credential for an MCP server.

    Args:
        mcp_server_id: The MCP server this credential is for
        credential_type: "api_key", "bearer", or "oauth_token"
        value: The credential value (dict for oauth_token, str for others)
        label: Optional human-readable label

    Returns:
        The created McpServerCredential row
    """
    if isinstance(value, dict):
        plaintext = json.dumps(value)
    else:
        plaintext = str(value)

    encrypted = encrypt(plaintext)

    cred = McpServerCredential(
        mcp_server_id=mcp_server_id,
        credential_type=credential_type,
        encrypted_value=encrypted,
        label=label,
    )
    db.add(cred)
    await db.flush()
    return cred


async def get_credential(db: AsyncSession, credential_id: str) -> McpServerCredential | None:
    """Get a credential by ID."""
    result = await db.execute(
        select(McpServerCredential).where(McpServerCredential.id == credential_id)
    )
    return result.scalar_one_or_none()


async def list_credentials(db: AsyncSession, mcp_server_id: str) -> list[McpServerCredential]:
    """List all credentials for an MCP server."""
    result = await db.execute(
        select(McpServerCredential)
        .where(McpServerCredential.mcp_server_id == mcp_server_id)
        .order_by(McpServerCredential.created_at)
    )
    return list(result.scalars().all())


async def delete_credential(db: AsyncSession, credential_id: str) -> bool:
    """Delete a credential. Returns True if deleted."""
    result = await db.execute(
        select(McpServerCredential).where(McpServerCredential.id == credential_id)
    )
    cred = result.scalar_one_or_none()
    if cred is None:
        return False
    await db.delete(cred)
    await db.flush()
    return True


async def delete_server_credentials(db: AsyncSession, mcp_server_id: str) -> int:
    """Delete all credentials for an MCP server. Returns count deleted."""
    creds = await list_credentials(db, mcp_server_id)
    count = 0
    for cred in creds:
        await db.delete(cred)
        count += 1
    if count:
        await db.flush()
    return count


def decrypt_credential(cred: McpServerCredential) -> dict[str, Any] | str:
    """Decrypt a credential and return its value.

    For oauth_token: returns the dict {access_token, refresh_token, ...}
    For api_key/bearer: returns the string value
    """
    plaintext = decrypt(cred.encrypted_value)
    if cred.credential_type == "oauth_token":
        return json.loads(plaintext)
    return plaintext


def inject_credential(
    env_template: dict[str, str] | None,
    headers_template: dict[str, str] | None,
    credential_value: dict[str, Any] | str,
) -> tuple[dict[str, str], dict[str, str]]:
    """Render env and header templates with the credential value.

    Templates use {{credential_value}} or {{credential.access_token}} placeholders.

    Returns (env_dict, headers_dict) ready to pass to the MCP client.
    """
    env: dict[str, str] = {}
    headers: dict[str, str] = {}

    def render(template: str) -> str:
        if isinstance(credential_value, dict):
            # Support {{credential.access_token}} style
            for key, val in credential_value.items():
                template = template.replace(f"{{{{credential.{key}}}}}", str(val))
            # Also support {{credential_value}} with the whole dict as JSON
            if "{{credential_value}}" in template:
                template = template.replace(
                    "{{credential_value}}", json.dumps(credential_value)
                )
        else:
            template = template.replace("{{credential_value}}", str(credential_value))
        return template

    if env_template:
        for k, v in env_template.items():
            env[k] = render(v)

    if headers_template:
        for k, v in headers_template.items():
            headers[k] = render(v)

    return env, headers
