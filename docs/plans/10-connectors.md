# 10 — Connectors (MCP-first)

> **Revision note.** This plan replaces the original native-connector design. The original plan built a parallel integration abstraction (Connector base class, OAuth handler, per-service implementations) and deferred MCP to v0.2. The MCP ecosystem has since matured — as of mid-2026 there are 32,600+ MCP servers and 8+ production-grade Outlook/email servers. OpenClaw and Hermes Agent both ship MCP as their sole integration path with no native connector layer. This revision adopts MCP as the integration layer for v0.1 and removes the native connector abstraction.
>
> **What changed from the original:**
> - D9: `connector_action` kind replaced by `mcp_tool` kind (the four kinds are now `tool`, `sub_agent`, `memory`, `mcp_tool`)
> - D13: rewritten — CaberOS owns credential custody at rest; MCP servers receive credentials via env/headers at runtime
> - D38: MCP moved from v0.2 to v0.1; native `connector_action` kind removed
> - D8 (subject binding): unchanged in principle, but now resolved by running one MCP server instance per Contact rather than by a native connector resolving the mailbox
> - Stories 15–18: unchanged in intent (connect once, encrypted, blast radius, revoke), fulfilled by MCP server management instead of a native connector registry

## Goal

Build the MCP integration layer: connect external MCP servers (email, Notion, GitHub, databases, anything), manage their credentials (encrypted at rest, injected at runtime), and expose their tools to agents through the syscall layer. The first concrete use case is email (Outlook/Gmail) — but the architecture is MCP-generic from day one.

## Spec references

- **D9 (revised)** — One capability concept, four kinds: `tool`, `sub_agent`, `memory`, `mcp_tool`
- **D13 (revised)** — CaberOS owns credential custody at rest; MCP servers receive credentials via env vars or headers at runtime. Secrets are referenced, never inlined in agent config or model context.
- **D8** — Subject binding: a Contact is linked to an MCP server instance (e.g. their Outlook mailbox). Subject-scoped tools resolve to that instance.
- **D10** — The syscall layer injects the subject; the agent cannot name it. Enforced by running one MCP server instance per Contact — the tool schema has no `account_id` parameter because the server is already authenticated to one mailbox.
- **D38 (revised)** — MCP is in v0.1. The `mcp_tool` capability kind is live. No native `connector_action` kind.
- **Stories 15–18** — connect service, encrypted token, see which agents use an MCP server, revoke

## Dependencies

- [01-database-layer.md](01-database-layer.md) — needs McpServer, McpServerCredential tables
- [04-syscall-layer.md](04-syscall-layer.md) — syscall layer injects credentials and resolves subject before forwarding to MCP server
- [05-capabilities.md](05-capabilities.md) — MCP tools are registered as capabilities of kind `mcp_tool`
- [07-pipeline.md](07-pipeline.md) — MCP tools are invoked through the execution pipeline

## Architecture

```
Agent (model)
  ↓ tool_call("email.read", {})
Syscall layer
  ↓ resolve subject (Contact → McpServer instance)
  ↓ inject credentials (decrypt from DB, pass as env/headers)
  ↓ audit record (before call)
MCP client (CaberOS)
  ↓ JSON-RPC over stdio or HTTP
MCP server (e.g. outlook-graph-mcp)
  ↓ Microsoft Graph API
External service (Outlook)
```

Key properties:
- **The agent never sees credentials.** The model calls `email.read({})`. The syscall layer resolves which MCP server instance to call (based on the Contact's binding), injects the credential, and forwards.
- **The agent never sees the subject.** There is no `account_id` parameter in the tool schema. The MCP server is already authenticated to one mailbox. D10 is enforced by architecture, not by convention.
- **Every call is still a syscall.** Mediated, audited, subject to approval. The MCP server is a capability implementation, not a side door.
- **CaberOS owns credentials at rest.** OAuth tokens and API keys are encrypted (Fernet) in the DB. At call time, the syscall layer decrypts and injects them as env vars or headers into the MCP server process. The MCP server holds the credential in memory for the duration of the call; CaberOS owns it at rest.

## Subject binding via instance-per-Contact

The original design had a native connector resolve `email.read()` → "this Contact's mailbox" at call time. With MCP, the same result is achieved differently:

- **Each Contact can be bound to an MCP server instance.** An MCP server instance is a running process (stdio) or a configured endpoint (HTTP) authenticated to one account.
- **The tool schema has no `account_id`.** The MCP server is already authenticated to one mailbox. The model has no parameter to abuse. D10 is enforced by the tool schema, not by the syscall layer rewriting args.
- **Unbound Contact → denied.** If a Contact has no MCP server instance bound for a given tool, the syscall fails closed with a denied audit record (same as D8).

This is simpler than the native design: no arg rewriting, no "the model sees a parameter it can't use" hack. The MCP server's own tool schema enforces D10.

For MCP servers that *do* expose `account_id` in their schema (multi-account servers), the syscall layer can either:
1. Reject them at registration time (enforce D10 strictly), or
2. Strip the `account_id` parameter from the schema before showing it to the model, and inject it at call time.

v0.1 uses option 1 (strict) — only single-account MCP servers are supported. Multi-account support is a v0.2 concern.

## Tasks

### 1. MCP client

`backend/src/agentos/mcp/client.py`:
- Thin wrapper around the `mcp` Python package (official MCP SDK)
- Supports stdio transport (spawn a local process) and HTTP/Streamable HTTP transport (connect to a remote server)
- `connect()`, `list_tools()`, `call_tool(name, args)`, `disconnect()`
- Per-server config: command + args (stdio) or url + headers (HTTP), env vars, timeout
- Graceful degradation: if `mcp` package not installed, MCP tools are unavailable but the rest of the system works

### 2. MCP server registry

`backend/src/agentos/mcp/registry.py`:
- Manages MCP server instances: one entry per (server_config, Contact binding)
- On startup: reads `mcp_servers` config, connects to each, discovers tools, registers them as capabilities of kind `mcp_tool`
- On Contact binding: spawns (or connects to) an MCP server instance authenticated to that Contact's account
- Tool names are namespaced: `mcp.{server_name}.{tool_name}` (e.g. `mcp.outlook.email_read`)
- Per-server tool filtering: operator can expose only a subset of an MCP server's tools

### 3. Credential management

`backend/src/agentos/mcp/credentials.py`:
- Credentials stored encrypted in the DB (Fernet, same secret store as provider keys — D13, D39)
- Credential types: OAuth token (access + refresh), API key, bearer token
- **OAuth flow:** CaberOS runs the OAuth loopback redirect itself (`http://localhost:51718/api/mcp/oauth/callback` in the desktop app; `http://localhost:8081/api/mcp/oauth/callback` in development), exchanges the auth code, stores the token encrypted. The MCP server never sees the OAuth flow — it receives the access token via env var or header at call time.
- **Token refresh:** CaberOS refreshes expired tokens using the stored refresh token, updates the encrypted value in the DB, and injects the fresh token on the next call.
- **Never returned to dashboard or logs.** Same rule as D13.

### 4. Subject binding

`backend/src/agentos/mcp/binding.py`:
- A Contact can be bound to an MCP server instance (stored in the `contact_mcp_bindings` table)
- Binding stores: contact_id, mcp_server_config_id, credential_id
- When a subject-scoped `mcp_tool` is called, the syscall layer resolves the binding, gets the MCP server instance, and forwards the call
- Unbound Contact → denied audit record (D8)

### 5. API routes

`backend/src/agentos/api/mcp.py`:
- `GET /api/mcp/servers` — list all configured MCP servers (name, type, tools, connected)
- `POST /api/mcp/servers` — add an MCP server config (command/url, env, headers, tool filter)
- `DELETE /api/mcp/servers/{id}` — remove an MCP server config (disconnects, unregisters tools)
- `GET /api/mcp/servers/{id}/tools` — list tools exposed by this server
- `POST /api/mcp/servers/{id}/connect` — start OAuth flow (for servers that need it)
- `GET /api/mcp/oauth/callback` — OAuth callback handler
- `GET /api/mcp/servers/{id}/agents` — which agents use this server (blast radius, story 17)
- `POST /api/mcp/bindings` — bind a Contact to an MCP server instance (subject binding, D8)
- `DELETE /api/mcp/bindings/{id}` — unbind

### 6. Syscall layer integration

`backend/src/agentos/syscall/mediator.py` (updated):
- For `mcp_tool` capabilities: resolve subject binding → get MCP server instance → inject credentials → forward call via MCP client → audit
- Credential injection: decrypt credential from DB, pass as env var or header to the MCP server process
- The model never sees the credential, the account_id, or the MCP server's internal state

### 7. First MCP server: email (Outlook)

`backend/src/agentos/mcp/servers/outlook.yaml` (config, not code):
- Uses an existing community MCP server (e.g. `k100shn/outlook-graph-mcp` or `jspv/msgraph-email-calendar-mcp`)
- Config: command (e.g. `uvx outlook-graph-mcp`), env vars (client_id, tenant_id from Azure app registration)
- OAuth: CaberOS runs the loopback redirect, stores the token encrypted, injects `OUTLOOK_ACCESS_TOKEN` env var at call time
- Tools: `email.read`, `email.send`, `calendar.read`, `calendar.create` (filtered from the server's full tool set)

No Outlook API code is written in CaberOS. The MCP server handles the Graph API; CaberOS handles auth, credential custody, subject binding, and audit.

## Database changes

New tables (replacing the original `connectors` and `connector_capabilities` tables):

### `mcp_servers`
| Column | Type | Description |
|---|---|---|
| id | str (UUID) | PK |
| name | str | Human-readable name (e.g. "Outlook") |
| transport | str | `stdio` or `http` |
| command | str \| null | Command to spawn (stdio) |
| args | str \| null | JSON array of args (stdio) |
| url | str \| null | Server URL (http) |
| headers | str \| null | JSON of headers (http) |
| env_template | str | JSON of env var templates (with `{{credential_key}}` placeholders) |
| tool_filter | str \| null | JSON array of allowed tool names (null = all) |
| connected | bool | Whether the server is currently connected |
| created_at | datetime | |
| updated_at | datetime | |

### `mcp_server_credentials`
| Column | Type | Description |
|---|---|---|
| id | str (UUID) | PK |
| mcp_server_id | str (FK) | Which MCP server this credential is for |
| credential_type | str | `oauth_token`, `api_key`, `bearer` |
| encrypted_value | str | Fernet-encrypted JSON (access_token, refresh_token, etc.) |
| created_at | datetime | |
| updated_at | datetime | |

### `contact_mcp_bindings`
| Column | Type | Description |
|---|---|---|
| id | str (UUID) | PK |
| contact_id | str (FK) | The Contact |
| mcp_server_id | str (FK) | The MCP server config |
| credential_id | str (FK) | The credential to inject |
| created_at | datetime | |

### `mcp_tools` (registered capabilities)
| Column | Type | Description |
|---|---|---|
| id | str (UUID) | PK |
| mcp_server_id | str (FK) | Which server exposes this tool |
| tool_name | str | The MCP server's tool name (e.g. `email_read`) |
| capability_name | str | The registered capability name (e.g. `mcp.outlook.email_read`) |
| parameters_schema | str | JSON schema (from MCP server's `list_tools`) |
| description | str | Tool description |
| egress | bool | Whether this tool leaves the machine |
| require_approval | bool | Default approval requirement |
| subject_scoped | bool | Whether this tool is subject-scoped (no `account_id` in schema) |
| created_at | datetime | |

## Files to create

- `backend/src/agentos/mcp/__init__.py`
- `backend/src/agentos/mcp/client.py` — MCP client wrapper (stdio + HTTP)
- `backend/src/agentos/mcp/registry.py` — MCP server registry, tool discovery, capability registration
- `backend/src/agentos/mcp/credentials.py` — encrypted credential storage, OAuth flow, token refresh
- `backend/src/agentos/mcp/binding.py` — Contact → MCP server instance binding
- `backend/src/agentos/mcp/oauth.py` — loopback OAuth redirect handler
- `backend/src/agentos/api/mcp.py` — REST API routes
- `backend/src/agentos/mcp/servers/outlook.yaml` — Outlook MCP server config
- `backend/tests/test_mcp.py` — tests (mock MCP server + mock OAuth)

## Files to modify

- `backend/src/agentos/models/__init__.py` — add MCP models, remove connector models
- `backend/src/agentos/models/connector.py` → `backend/src/agentos/models/mcp.py` — rename and rewrite
- `backend/src/agentos/syscall/mediator.py` — add `mcp_tool` handling (subject resolution, credential injection, MCP forwarding)
- `backend/src/agentos/capabilities/registry.py` — accept `mcp_tool` kind
- `backend/src/agentos/config_schema.py` — update capability grant to accept `mcp_tool` kind
- `backend/src/agentos/seed.py` — remove connector seed, add MCP server seed
- `docs/spec-v0.1.md` — update D9, D13, D38, bindings table, tech stack

## Verification

- MCP client connects to a mock MCP server (stdio) → discovers tools → registers as capabilities
- Encrypted credential → decrypt → matches original
- Encrypted credential never appears in API responses or logs
- OAuth flow: redirect → callback → token stored encrypted
- `email.read()` with bound Contact → forwards to MCP server with injected credential → returns emails
- `email.read()` with unbound Contact → denied, reason "no subject binding"
- `email.send()` with `require_approval` → ApprovalRequest created
- Revoke MCP server → credentials deleted, capabilities unregistered, agents that used it lose access
- `GET /api/mcp/servers/{id}/agents` → lists agents using this server
- `uv run pytest tests/test_mcp.py` passes (mock MCP server + mock OAuth)

## What we don't build

- **No native connector code.** No `Connector` base class, no `outlook.py` with Graph API calls, no `gmail.py`. The MCP server handles the external API.
- **No multi-account MCP servers in v0.1.** Only single-account servers (one instance per Contact). Multi-account (one server, `account_id` in tool args) is v0.2.
- **No MCP server discovery protocol.** v0.1 uses explicit config (command/url in DB). Dynamic discovery from a registry is v0.2.
- **No MCP server-as-server.** CaberOS is an MCP *client* only. It does not expose itself as an MCP server (that's a v0.2+ option, like OpenClaw's `mcp serve`).

## Open questions

1. **Which Outlook MCP server to recommend?** The config should default to one, but the operator can swap it. Candidates: `k100shn/outlook-graph-mcp` (device flow, no client secret), `jspv/msgraph-email-calendar-mcp` (framework mode, pre-authenticated tokens). The framework-mode server is a better fit for CaberOS's credential-custody model — CaberOS owns the token, passes it via env var.

2. **Token refresh for framework-mode servers.** If the MCP server expects the token in an env var at startup, refreshing requires restarting the process. Options: (a) restart the MCP server process on refresh, (b) use a server that accepts tokens per-call via headers, (c) use a server that does its own refresh from a refresh token we provide. This needs to be resolved during implementation — it's a per-server-config question, not an architecture question.

3. **Gmail.** The same architecture works for Gmail (community Gmail MCP servers exist). v0.1 ships Outlook as the first connector; Gmail is a config addition, not a code change.
