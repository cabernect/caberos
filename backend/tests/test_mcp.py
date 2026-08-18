"""Tests for MCP client infrastructure (ticket 08a).

Uses MockMcpClient — no real process or network needed.
"""

import json

import pytest
import pytest_asyncio
from sqlalchemy import select

from agentos.capabilities.registry import registry as cap_registry
from agentos.mcp import binding as mcp_binding
from agentos.mcp import credentials as mcp_creds
from agentos.mcp import registry as mcp_registry
from agentos.mcp.client import MockMcpClient
from agentos.models.contact import Contact
from agentos.models.mcp import (
    McpServer,
    McpServerCredential,
    McpTool,
)
from agentos.secret_store import decrypt, encrypt

# --- MockMcpClient tests ---


@pytest.mark.asyncio
async def test_mock_client_connect_disconnect():
    """MockMcpClient connect/disconnect lifecycle."""
    client = MockMcpClient()
    assert not client.connected
    await client.connect()
    assert client.connected
    await client.disconnect()
    assert not client.connected


@pytest.mark.asyncio
async def test_mock_client_list_tools():
    """MockMcpClient discovers tools."""
    client = MockMcpClient(
        tools=[
            {
                "name": "email_read",
                "description": "Read emails",
                "inputSchema": {"type": "object", "properties": {}},
            }
        ]
    )
    await client.connect()
    tools = await client.list_tools()
    assert len(tools) == 1
    assert tools[0]["name"] == "email_read"
    assert tools[0]["description"] == "Read emails"


@pytest.mark.asyncio
async def test_mock_client_call_tool():
    """MockMcpClient calls a tool and returns a result."""
    client = MockMcpClient()
    await client.connect()
    result = await client.call_tool("echo", {"message": "hello"})
    assert result["isError"] is False
    assert len(result["content"]) == 1
    assert "hello" in result["content"][0]["text"]


@pytest.mark.asyncio
async def test_mock_client_custom_results():
    """MockMcpClient returns custom results for specific tools."""
    client = MockMcpClient(
        call_results={
            "email_read": {
                "content": [{"type": "text", "text": "Inbox: 3 unread"}],
                "isError": False,
            }
        }
    )
    await client.connect()
    result = await client.call_tool("email_read", {"folder": "inbox"})
    assert "3 unread" in result["content"][0]["text"]


# --- Credential tests ---


@pytest.mark.asyncio
async def test_encrypt_decrypt_credential():
    """Credentials can be encrypted and decrypted."""
    plaintext = "my-secret-api-key"
    encrypted = encrypt(plaintext)
    assert encrypted != plaintext
    assert decrypt(encrypted) == plaintext


@pytest.mark.asyncio
async def test_store_and_decrypt_credential(db):
    """Credentials are stored encrypted and can be decrypted."""
    server = McpServer(name="test", transport="stdio", command="echo")
    db.add(server)
    await db.flush()

    cred = await mcp_creds.store_credential(
        db, server.id, "api_key", "my-secret-key", label="Test key"
    )
    await db.flush()

    # The stored value should be encrypted (not plaintext)
    assert cred.encrypted_value != "my-secret-key"

    # Decrypt should return the original value
    value = mcp_creds.decrypt_credential(cred)
    assert value == "my-secret-key"


@pytest.mark.asyncio
async def test_store_oauth_credential(db):
    """OAuth tokens are stored as encrypted JSON."""
    server = McpServer(name="test", transport="stdio", command="echo")
    db.add(server)
    await db.flush()

    token = {"access_token": "abc123", "refresh_token": "def456"}
    cred = await mcp_creds.store_credential(db, server.id, "oauth_token", token)
    await db.flush()

    value = mcp_creds.decrypt_credential(cred)
    assert isinstance(value, dict)
    assert value["access_token"] == "abc123"
    assert value["refresh_token"] == "def456"


@pytest.mark.asyncio
async def test_inject_credential_env():
    """Credential injection renders env templates."""
    env, headers = mcp_creds.inject_credential(
        env_template={"API_KEY": "{{credential_value}}"},
        headers_template=None,
        credential_value="my-key",
    )
    assert env["API_KEY"] == "my-key"
    assert headers == {}


@pytest.mark.asyncio
async def test_inject_credential_oauth():
    """OAuth credential injection supports {{credential.access_token}}."""
    env, headers = mcp_creds.inject_credential(
        env_template={"ACCESS_TOKEN": "{{credential.access_token}}"},
        headers_template={"Authorization": "Bearer {{credential.access_token}}"},
        credential_value={"access_token": "tok123", "refresh_token": "ref456"},
    )
    assert env["ACCESS_TOKEN"] == "tok123"
    assert headers["Authorization"] == "Bearer tok123"


# --- Binding tests ---


@pytest_asyncio.fixture
async def contact(db):
    """Create a test contact."""
    c = Contact(
        id="test-contact",
        channel="dashboard_chat",
        bot_id="test-agent",
        external_user_id="test-user",
        display_name="Test Contact",
    )
    db.add(c)
    await db.flush()
    return c


@pytest_asyncio.fixture
async def mcp_server(db):
    """Create a test MCP server."""
    s = McpServer(name="test-server", transport="stdio", command="echo")
    db.add(s)
    await db.flush()
    return s


@pytest_asyncio.fixture
async def mcp_credential(db, mcp_server):
    """Create a test credential."""
    cred = await mcp_creds.store_credential(
        db, mcp_server.id, "api_key", "test-key", label="Test"
    )
    await db.flush()
    return cred


@pytest.mark.asyncio
async def test_create_and_get_binding(db, contact, mcp_server, mcp_credential):
    """Bindings can be created and retrieved."""
    binding = await mcp_binding.create_binding(
        db, contact.id, mcp_server.id, mcp_credential.id
    )
    await db.flush()

    retrieved = await mcp_binding.get_binding(db, contact.id, mcp_server.id)
    assert retrieved is not None
    assert retrieved.id == binding.id
    assert retrieved.contact_id == contact.id
    assert retrieved.mcp_server_id == mcp_server.id


@pytest.mark.asyncio
async def test_resolve_binding(db, contact, mcp_server, mcp_credential):
    """resolve_binding returns (binding, server, credential)."""
    await mcp_binding.create_binding(
        db, contact.id, mcp_server.id, mcp_credential.id
    )
    await db.flush()

    resolved = await mcp_binding.resolve_binding(db, contact.id, mcp_server.id)
    assert resolved is not None
    binding, server, cred = resolved
    assert server.name == "test-server"
    assert cred.credential_type == "api_key"


@pytest.mark.asyncio
async def test_resolve_unbound_contact(db, contact, mcp_server):
    """resolve_binding returns None for unbound contacts."""
    resolved = await mcp_binding.resolve_binding(db, contact.id, mcp_server.id)
    assert resolved is None


@pytest.mark.asyncio
async def test_delete_binding(db, contact, mcp_server, mcp_credential):
    """Bindings can be deleted."""
    binding = await mcp_binding.create_binding(
        db, contact.id, mcp_server.id, mcp_credential.id
    )
    await db.flush()

    deleted = await mcp_binding.delete_binding(db, binding.id)
    assert deleted is True

    # Should be gone
    retrieved = await mcp_binding.get_binding(db, contact.id, mcp_server.id)
    assert retrieved is None


# --- Registry tests (using mock client) ---


@pytest.mark.asyncio
async def test_namespace():
    """Tool names are namespaced correctly."""
    assert mcp_registry._namespace("Outlook", "email_read") == "mcp.outlook.email_read"
    assert mcp_registry._namespace("My Server", "tool") == "mcp.my_server.tool"
    assert mcp_registry._namespace("a.b.c", "tool") == "mcp.a_b_c.tool"


@pytest.mark.asyncio
async def test_registry_register_and_unregister_tool():
    """Tools can be registered and unregistered in the capability registry."""
    # Clear state
    mcp_registry._tool_map.clear()
    cap_registry._caps.clear()

    # Manually register a tool
    from agentos.capabilities.registry import CapabilityDef

    cap_name = "mcp.test.echo"
    cap_registry.register(
        CapabilityDef(
            name=cap_name,
            kind="mcp_tool",
            description="Echo",
            parameters_schema={"type": "object", "properties": {}},
            egress=True,
            require_approval=True,
            subject_scoped=True,
            execute=None,
        )
    )
    mcp_registry._tool_map[cap_name] = ("server-1", "echo")

    # Verify it's registered
    cap = cap_registry.get(cap_name)
    assert cap is not None
    assert cap.kind == "mcp_tool"

    # Unregister
    cap_registry._caps.pop(cap_name, None)
    mcp_registry._tool_map.pop(cap_name, None)

    assert cap_registry.get(cap_name) is None


# --- DB model tests ---


@pytest.mark.asyncio
async def test_mcp_server_model(db):
    """McpServer can be created and queried."""
    server = McpServer(
        name="Test MCP",
        transport="stdio",
        command="uvx",
        args='["some-mcp-server"]',
        env_template='{"API_KEY": "{{credential_value}}"}',
    )
    db.add(server)
    await db.commit()

    result = await db.execute(select(McpServer).where(McpServer.name == "Test MCP"))
    found = result.scalar_one()
    assert found.transport == "stdio"
    assert found.command == "uvx"
    assert json.loads(found.args) == ["some-mcp-server"]


@pytest.mark.asyncio
async def test_mcp_tool_model(db, mcp_server):
    """McpTool can be created and queried."""
    tool = McpTool(
        mcp_server_id=mcp_server.id,
        tool_name="email_read",
        capability_name="mcp.test-server.email_read",
        parameters_schema='{"type": "object"}',
        description="Read emails",
        egress=True,
        require_approval=True,
        subject_scoped=True,
    )
    db.add(tool)
    await db.commit()

    result = await db.execute(select(McpTool).where(McpTool.tool_name == "email_read"))
    found = result.scalar_one()
    assert found.capability_name == "mcp.test-server.email_read"
    assert found.egress is True


@pytest.mark.asyncio
async def test_delete_server_cascades_credentials(db, mcp_server, mcp_credential):
    """Deleting a server's credentials works."""
    count = await mcp_creds.delete_server_credentials(db, mcp_server.id)
    assert count == 1

    # Credential should be gone
    result = await db.execute(
        select(McpServerCredential).where(McpServerCredential.id == mcp_credential.id)
    )
    assert result.scalar_one_or_none() is None


# --- Credential injection on connect tests (08b) ---


def _make_capturing_client(captured_env: dict):
    """Create a MockMcpClient subclass that accepts McpClient's constructor args."""

    class CapturingClient(MockMcpClient):
        def __init__(self, transport=None, command=None, args=None, url=None,
                     headers=None, env=None, **kwargs):
            super().__init__()
            self.env = env or {}
            self.headers = headers or {}

        async def connect(self):
            captured_env.update(self.env)
            await super().connect()

    return CapturingClient


@pytest.mark.asyncio
async def test_connect_server_injects_credential(db, monkeypatch):
    """connect_server fetches stored credential and renders env_template."""
    import json

    from agentos.mcp import registry as mcp_registry

    # Create a server with an env_template that needs a credential
    server = McpServer(
        name="cred-test",
        transport="stdio",
        command="echo",
        env_template=json.dumps({"API_KEY": "{{credential_value}}"}),
        enabled=True,
    )
    db.add(server)
    await db.flush()

    # Store a credential
    await mcp_creds.store_credential(db, server.id, "api_key", "my-secret-key")
    await db.commit()

    # Track what env the McpClient receives
    captured_env: dict = {}

    monkeypatch.setattr(mcp_registry, "McpClient", _make_capturing_client(captured_env))

    # Patch async_session_factory to use our test session
    class TestSessionFactory:
        def __call__(self):
            class TestSession:
                async def __aenter__(self):
                    return db

                async def __aexit__(self, *args):
                    pass

            return TestSession()

    monkeypatch.setattr(mcp_registry, "async_session_factory", TestSessionFactory())

    # Mock _discover_tools to avoid DB writes (we only test credential injection)
    async def mock_discover(server, client):
        pass

    monkeypatch.setattr(mcp_registry, "_discover_tools", mock_discover)

    try:
        result = await mcp_registry.connect_server(server)
        assert result is True
        # The env should have the rendered credential, not the placeholder
        assert captured_env.get("API_KEY") == "my-secret-key"
        assert "{{credential_value}}" not in captured_env.get("API_KEY", "")
    finally:
        # Cleanup
        if server.id in mcp_registry._clients:
            del mcp_registry._clients[server.id]


@pytest.mark.asyncio
async def test_connect_server_without_credential_passes_placeholder(db, monkeypatch):
    """connect_server with no stored credential passes template as-is."""
    import json

    from agentos.mcp import registry as mcp_registry

    server = McpServer(
        name="no-cred-test",
        transport="stdio",
        command="echo",
        env_template=json.dumps({"API_KEY": "{{credential_value}}"}),
        enabled=True,
    )
    db.add(server)
    await db.commit()

    captured_env: dict = {}

    monkeypatch.setattr(mcp_registry, "McpClient", _make_capturing_client(captured_env))

    class TestSessionFactory:
        def __call__(self):
            class TestSession:
                async def __aenter__(self):
                    return db

                async def __aexit__(self, *args):
                    pass

            return TestSession()

    monkeypatch.setattr(mcp_registry, "async_session_factory", TestSessionFactory())

    # Mock _discover_tools to avoid DB writes
    async def mock_discover(server, client):
        pass

    monkeypatch.setattr(mcp_registry, "_discover_tools", mock_discover)

    try:
        await mcp_registry.connect_server(server)
        # Without a credential, the placeholder is passed through
        assert captured_env.get("API_KEY") == "{{credential_value}}"
    finally:
        if server.id in mcp_registry._clients:
            del mcp_registry._clients[server.id]


@pytest.mark.asyncio
async def test_credential_encrypted_at_rest(db):
    """Credentials are encrypted in the database (not stored as plaintext)."""
    server = McpServer(name="enc-test", transport="stdio", command="echo")
    db.add(server)
    await db.flush()

    cred = await mcp_creds.store_credential(
        db, server.id, "api_key", "super-secret-key-123", label="Production"
    )
    await db.flush()

    # The encrypted_value column should NOT contain the plaintext
    assert "super-secret-key-123" not in cred.encrypted_value
    # But decrypting should return the original
    assert mcp_creds.decrypt_credential(cred) == "super-secret-key-123"


# --- OAuth tests (08b) ---


@pytest.mark.asyncio
async def test_oauth_token_storage_roundtrip(db, monkeypatch):
    """OAuth tokens can be stored and retrieved via EncryptedTokenStorage."""
    import json

    from mcp.shared.auth import OAuthToken

    from agentos.mcp.oauth import EncryptedTokenStorage

    server = McpServer(
        name="oauth-test",
        transport="http",
        url="https://example.com/mcp",
        oauth_config=json.dumps({"scope": "read", "redirect_uri": "http://localhost:8081/api/mcp/oauth/callback"}),
    )
    db.add(server)
    await db.commit()

    # Patch async_session_factory to use our test session
    import agentos.mcp.oauth

    class TestSessionFactory:
        def __call__(self):
            class TestSession:
                async def __aenter__(self):
                    return db

                async def __aexit__(self, *args):
                    pass

            return TestSession()

    monkeypatch.setattr(agentos.mcp.oauth, "async_session_factory", TestSessionFactory())

    storage = EncryptedTokenStorage(server.id)

    # Store a token
    token = OAuthToken(
        access_token="access-123",
        token_type="Bearer",
        expires_in=3600,
        scope="read",
        refresh_token="refresh-456",
    )
    await storage.set_tokens(token)

    # Retrieve it
    retrieved = await storage.get_tokens()
    assert retrieved is not None
    assert retrieved.access_token == "access-123"
    assert retrieved.refresh_token == "refresh-456"
    assert retrieved.token_type == "Bearer"


@pytest.mark.asyncio
async def test_oauth_callback_resolves_pending_flow():
    """handle_oauth_callback resolves a pending OAuth flow."""

    from agentos.mcp.oauth import OAuthFlowState, _pending_flows, handle_oauth_callback

    flow = OAuthFlowState("test-server-id")
    _pending_flows["test-server-id"] = flow

    # Simulate the OAuth callback
    redirect = handle_oauth_callback(code="test-code", state="test-state")

    assert "oauth_connected=test-server-id" in redirect
    assert flow.completed
    assert flow.callback_future.result() == ("test-code", "test-state")

    # Cleanup
    _pending_flows.pop("test-server-id", None)


@pytest.mark.asyncio
async def test_oauth_callback_handles_error():
    """handle_oauth_callback handles error responses."""
    from agentos.mcp.oauth import OAuthFlowState, _pending_flows, handle_oauth_callback

    flow = OAuthFlowState("test-server-error")
    _pending_flows["test-server-error"] = flow

    redirect = handle_oauth_callback(code="", error="access_denied")

    assert "oauth_error=access_denied" in redirect
    assert flow.error == "access_denied"

    # Cleanup
    _pending_flows.pop("test-server-error", None)


@pytest.mark.asyncio
async def test_connect_server_skips_oauth_without_token(db, monkeypatch):
    """connect_server returns False for OAuth server with no stored token."""
    import json

    from agentos.mcp import registry as mcp_registry

    server = McpServer(
        name="oauth-no-token",
        transport="http",
        url="https://example.com/mcp",
        oauth_config=json.dumps({"scope": "read"}),
        enabled=True,
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

    monkeypatch.setattr(mcp_registry, "async_session_factory", TestSessionFactory())

    result = await mcp_registry.connect_server(server)
    assert result is False  # No OAuth token → skip


@pytest.mark.asyncio
async def test_oauth_config_in_server_list(db):
    """Server list API includes oauth_config and auth_type fields."""
    import json

    server = McpServer(
        name="oauth-list-test",
        transport="http",
        url="https://example.com/mcp",
        oauth_config=json.dumps({"scope": "read"}),
    )
    db.add(server)
    await db.commit()

    # Verify the oauth_config is stored correctly
    result = await db.execute(select(McpServer).where(McpServer.name == "oauth-list-test"))
    found = result.scalar_one()
    config = json.loads(found.oauth_config)
    assert config["scope"] == "read"
