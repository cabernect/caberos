# 08a — MCP client infrastructure

**What to build:** The generic plumbing for Model Context Protocol servers, proven against a simple/local MCP server first (no OAuth, no Outlook). CaberOS can connect to an MCP server (stdio or HTTP transport), discover its tools, register them as capabilities of kind `mcp_tool`, and route syscalls through them with subject binding and audit records — the same mediation every other capability kind gets.

**Blocked by:** 04 — Approval flow (MCP tools that require approval go through the same gate).

**Status:** ready-for-agent

**Spec references:** D9 (revised — `mcp_tool` kind), D13 (revised — CaberOS owns credential custody), D38 (revised — MCP in v0.1), plan 10 (MCP-first design)

- [ ] MCP client: thin wrapper around the `mcp` Python package. Supports stdio (spawn process) and HTTP transports. `connect()`, `list_tools()`, `call_tool()`, `disconnect()`.
- [ ] MCP server registry: manages MCP server configs in the DB. On startup, connects to each configured server, discovers tools, registers them as capabilities of kind `mcp_tool`. Tool names namespaced as `mcp.{server_name}.{tool_name}`.
- [ ] Credential management: generic API keys/tokens encrypted (Fernet, same secret store as provider keys — D13/D39). Credentials injected as env vars or headers at call time — the MCP server holds them in memory, CaberOS owns them at rest. (OAuth loopback flow is deferred to 08b — test this with a static API key or no-auth MCP server first.)
- [ ] DB models: `mcp_servers`, `mcp_server_credentials`, `contact_mcp_bindings`, `mcp_tools` (replaces the original `connectors` and `connector_capabilities` tables).
- [ ] Subject binding: a Contact is bound to an MCP server instance. The tool schema has no `account_id` parameter — D10 enforced by architecture. Unbound Contact → denied audit record (D8).
- [ ] Syscall layer: for `mcp_tool` capabilities, resolves subject binding → gets MCP server instance → decrypts credential → injects via env/headers → forwards call via MCP client → writes audit record.
- [ ] API routes: `GET /api/mcp/servers`, `POST /api/mcp/servers`, `DELETE /api/mcp/servers/{id}`, `GET /api/mcp/servers/{id}/tools`, `GET /api/mcp/servers/{id}/agents` (blast radius), `POST /api/mcp/bindings`, `DELETE /api/mcp/bindings/{id}`.
- [ ] Connectors page: list connected MCP servers (name, type, tools, connected status). Per-server: list of agents using it (blast radius).
- [ ] Agent settings: capabilities list includes MCP tools (grouped under "MCP Servers").
- [ ] Audit: MCP tool calls audited like all syscalls. The audit record shows which MCP server was used, which tool, and whose data was accessed.
- [ ] Tests: mock MCP server (stdio) — verify connect → discover tools → register → call with injected credential → audit. Verify: unbound Contact → denied. Verify: revoke → credentials deleted, capabilities unregistered.
