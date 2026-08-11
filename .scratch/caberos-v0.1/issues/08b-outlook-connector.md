# 08b — MCP credentials (API key + OAuth)

**What to build:** Complete the credential lifecycle for all MCP servers. Two flows:

1. **API key flow** (simple — no redirect): user enters a key string in the dashboard, CaberOS stores it encrypted (Fernet), injects it into the server's `env_template` at connect time. Covers Brave Search, GitHub, Slack, Stripe, PostgreSQL, Exa, Tavily, and any future `api_key` server.

2. **OAuth flow** (redirect-based): CaberOS runs the OAuth loopback itself (`http://localhost:8081/api/mcp/oauth/callback`), stores the token encrypted, and handles refresh. Covers Notion, Gmail, Google Drive, Google Calendar, Linear, Sentry, Figma, Asana, Atlassian, Supabase, Vercel, Cloudflare, and any future `oauth` server. Outlook is the first real-account smoke test.

**Blocked by:** 08a — MCP client infrastructure (needs the generic MCP client, server registry, credential store, and syscall routing to already work).

**Status:** ready-for-agent

**Spec references:** D13 (revised — CaberOS owns credential custody), D38 (revised — MCP in v0.1), D40 (credential injection at runtime)

## API key flow

- [ ] **Backend: credential injection on connect.** `connect_server()` in `registry.py` currently passes `env_template` with `{{credential_value}}` placeholders unrendered. Fix: fetch the stored credential for the server, decrypt it, call `inject_credential()` to render the env_template, pass the rendered env dict to the MCP client.
- [ ] **Backend: reconnect after credential stored.** `POST /api/mcp/servers/{id}/credentials` should optionally trigger a reconnect after storing, so the server connects immediately once the key is provided.
- [ ] **Frontend: credential UI on ServerCard.** When a server is disconnected and has an `env_template` with `{{credential_value}}`, show a "Configure API Key" button. Clicking opens an inline form with a password-type input and a "Save & Connect" button. On success, the server card refreshes to show connected status.
- [ ] **Frontend: list/delete credentials.** Show stored credentials (type + label, never the value) with a delete button. Replacing a key = delete old + store new.
- [ ] **Tests:** store credential → connect_server renders env_template → MCP client receives the decrypted key in env. Verify encrypted at rest. Verify wrong key → connection fails gracefully.

## OAuth flow

- [ ] **Backend: OAuth loopback flow.** `POST /api/mcp/servers/{id}/connect` starts the OAuth flow — builds the authorize URL with the server's OAuth config (client_id, scope, redirect_uri), returns the URL to the frontend to open in a popup/new tab. `GET /api/mcp/oauth/callback` receives the code, exchanges it for tokens, stores encrypted via the 08a credential store.
- [ ] **Backend: token refresh.** Background task or on-demand refresh when a token expires. Stores the refreshed token encrypted, replacing the old one.
- [ ] **Backend: OAuth config per server.** Each OAuth MCP server needs client_id, client_secret, scope, authorize_url, token_url, redirect_uri. Stored in the server config (encrypted client_secret). For servers that use their own OAuth (Notion, Linear, Sentry, Figma, etc.), the client_id/secret is supplied by the operator. For servers with a fixed OAuth endpoint (Google), document the required setup.
- [ ] **Frontend: OAuth connect button.** When a server has `auth_type: oauth`, show "Connect with OAuth" instead of "Configure API Key". Clicking opens the authorize URL in a new tab. After the callback redirects back, the frontend polls or receives a webhook and refreshes the server card to show connected.
- [ ] **Frontend: revoke button.** Disconnects the server, deletes the stored OAuth token, and (where supported) calls the provider's revoke endpoint.
- [ ] **Tests:** mock OAuth flow — connect → callback → token stored encrypted → refresh → revoke clears credential. One real-account manual smoke test per provider before release (not in the automated suite).

## Outlook as first OAuth consumer

- [ ] Outlook MCP server config: uses an existing community MCP server (e.g. `k100shn/outlook-graph-mcp` or `jspv/msgraph-email-calendar-mcp`). Config is YAML — command, args, env template. No Outlook API code written in CaberOS.
- [ ] Requires an Azure app registration (client id/secret) supplied by the operator as deployment config — document this as a setup prerequisite, not something CaberOS provisions.
- [ ] Agent settings: granting `mcp.outlook.email_read` to an agent with no connected Outlook → validation error or clear warning.

## Catalog integration

- [ ] Catalog entries with `auth_type: api_key` → install shows "Configure API Key" immediately.
- [ ] Catalog entries with `auth_type: oauth` → install shows "Connect with OAuth" immediately.
- [ ] Catalog entries with `auth_type: none` → install connects directly (already works).
