# 08 — Connectors (MCP — Outlook email)

**What to build:** The operator connects an Outlook account by configuring an MCP server (e.g. `outlook-graph-mcp`) and running the OAuth loopback flow. CaberOS stores the credential encrypted (Fernet). The MCP server's tools are discovered and registered as capabilities of kind `mcp_tool`. The agent can now read email, send email (with approval), and read the calendar. MCP servers are shared across agents — one Outlook connection serves any agent granted the `mcp.outlook.email_read` capability. The connectors page shows connected MCP servers, their tools, and which agents use them (blast radius).

**Blocked by:** 04 — Approval flow (email.send requires approval — the operator approves before an email is sent).

**Status:** ready-for-agent

**Spec references:** D9 (revised — `mcp_tool` kind), D13 (revised — CaberOS owns credential custody), D38 (revised — MCP in v0.1), plan 10 (MCP-first design)

- [ ] MCP client: thin wrapper around the `mcp` Python package. Supports stdio (spawn process) and HTTP transports. `connect()`, `list_tools()`, `call_tool()`, `disconnect()`.
- [ ] MCP server registry: manages MCP server configs in the DB. On startup, connects to each server, discovers tools, registers them as capabilities of kind `mcp_tool`. Tool names namespaced as `mcp.{server_name}.{tool_name}`.
- [ ] Credential management: OAuth tokens and API keys encrypted (Fernet, same secret store as provider keys — D13/D39). CaberOS runs the OAuth loopback redirect itself (`http://localhost:8081/api/mcp/oauth/callback`), stores the token encrypted. Token refresh handled by CaberOS. Credentials injected as env vars or headers at call time — the MCP server holds them in memory, CaberOS owns them at rest.
- [ ] DB models: `mcp_servers`, `mcp_server_credentials`, `contact_mcp_bindings`, `mcp_tools` (replaces the original `connectors` and `connector_capabilities` tables).
- [ ] Outlook MCP server config: uses an existing community MCP server (e.g. `k100shn/outlook-graph-mcp` or `jspv/msgraph-email-calendar-mcp`). Config is YAML — command, args, env template. No Outlook API code written in CaberOS.
- [ ] Subject binding: a Contact is bound to an MCP server instance (one instance per Contact, authenticated to their mailbox). The tool schema has no `account_id` parameter — D10 enforced by architecture. Unbound Contact → denied audit record (D8).
- [ ] Syscall layer: for `mcp_tool` capabilities, resolves subject binding → gets MCP server instance → decrypts credential → injects via env/headers → forwards call via MCP client → writes audit record.
- [ ] API routes: `GET /api/mcp/servers`, `POST /api/mcp/servers`, `DELETE /api/mcp/servers/{id}`, `GET /api/mcp/servers/{id}/tools`, `POST /api/mcp/servers/{id}/connect` (OAuth), `GET /api/mcp/oauth/callback`, `GET /api/mcp/servers/{id}/agents` (blast radius), `POST /api/mcp/bindings`, `DELETE /api/mcp/bindings/{id}`.
- [ ] Connectors page: list connected MCP servers (name, type, tools, connected status). Connect button → starts OAuth flow. Revoke button → confirms, revokes. Per-server: list of agents using it (blast radius).
- [ ] Agent settings: capabilities list includes MCP tools (grouped under "MCP Servers"). Granting `mcp.outlook.email_read` to an agent with no connected Outlook → validation error or clear warning.
- [ ] Audit: MCP tool calls audited like all syscalls. The audit record shows which MCP server was used, which tool, and whose data was accessed.
- [ ] Tests: mock MCP server (stdio) + mock OAuth. Verify: connect → discover tools → register → call with injected credential → audit. Verify: unbound Contact → denied. Verify: revoke → credentials deleted, capabilities unregistered.
