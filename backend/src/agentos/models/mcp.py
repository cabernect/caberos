"""MCP server models — replaces the original connector models (D38 revised)."""

from sqlalchemy import Boolean, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, IdMixin, TimestampMixin


class McpServer(Base, IdMixin, TimestampMixin):
    """A configured MCP server (stdio or HTTP transport)."""

    __tablename__ = "mcp_servers"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    transport: Mapped[str] = mapped_column(String(20), nullable=False)  # "stdio" or "http"
    command: Mapped[str | None] = mapped_column(String(1024), nullable=True)  # stdio
    args: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON array (stdio)
    url: Mapped[str | None] = mapped_column(String(2048), nullable=True)  # http
    headers: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON of headers (http)
    env_template: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON of env var templates
    oauth_config: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON: OAuth client config
    tool_filter: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON array of allowed tool names
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    require_approval: Mapped[bool] = mapped_column(Boolean, default=True)  # per-server approval gate


class McpServerCredential(Base, IdMixin, TimestampMixin):
    """Encrypted credential for an MCP server (Fernet)."""

    __tablename__ = "mcp_server_credentials"

    mcp_server_id: Mapped[str] = mapped_column(String(36), ForeignKey("mcp_servers.id"), nullable=False)
    credential_type: Mapped[str] = mapped_column(String(50), nullable=False)  # oauth_token, api_key, bearer
    encrypted_value: Mapped[str] = mapped_column(Text, nullable=False)  # Fernet-encrypted JSON
    label: Mapped[str | None] = mapped_column(String(255), nullable=True)  # human-readable label


class ContactMcpBinding(Base, IdMixin, TimestampMixin):
    """Binds a Contact to an MCP server instance (subject binding, D8)."""

    __tablename__ = "contact_mcp_bindings"

    contact_id: Mapped[str] = mapped_column(String(36), ForeignKey("contacts.id"), nullable=False)
    mcp_server_id: Mapped[str] = mapped_column(String(36), ForeignKey("mcp_servers.id"), nullable=False)
    credential_id: Mapped[str] = mapped_column(String(36), ForeignKey("mcp_server_credentials.id"), nullable=False)


class McpTool(Base, IdMixin, TimestampMixin):
    """A tool discovered from an MCP server, registered as a capability."""

    __tablename__ = "mcp_tools"

    mcp_server_id: Mapped[str] = mapped_column(String(36), ForeignKey("mcp_servers.id"), nullable=False)
    tool_name: Mapped[str] = mapped_column(String(255), nullable=False)  # MCP server's tool name
    capability_name: Mapped[str] = mapped_column(String(255), nullable=False)  # mcp.{server}.{tool}
    parameters_schema: Mapped[str] = mapped_column(Text, nullable=False)  # JSON schema
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    egress: Mapped[bool] = mapped_column(Boolean, default=False)
    require_approval: Mapped[bool] = mapped_column(Boolean, default=False)
    subject_scoped: Mapped[bool] = mapped_column(Boolean, default=True)
