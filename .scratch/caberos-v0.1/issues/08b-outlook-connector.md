# 08b — Outlook connector (OAuth)

**What to build:** The operator connects a real Outlook account by configuring the Outlook MCP server and running the OAuth loopback flow. CaberOS stores the OAuth credential encrypted (Fernet) and handles token refresh. The agent can now read email, send email (with approval), and read the calendar through the generic MCP infrastructure from 08a.

**Blocked by:** 08a — MCP client infrastructure (needs the generic MCP client, server registry, subject binding, and syscall routing to already work).

**Status:** ready-for-agent

**Spec references:** D13 (revised — CaberOS owns credential custody), D38 (revised — MCP in v0.1)

- [ ] OAuth loopback flow: CaberOS runs the OAuth redirect itself (`http://localhost:8081/api/mcp/oauth/callback`), stores the token encrypted via the 08a credential store. Token refresh handled by CaberOS.
- [ ] Outlook MCP server config: uses an existing community MCP server (e.g. `k100shn/outlook-graph-mcp` or `jspv/msgraph-email-calendar-mcp`). Config is YAML — command, args, env template. No Outlook API code written in CaberOS.
- [ ] API routes: `POST /api/mcp/servers/{id}/connect` (starts OAuth), `GET /api/mcp/oauth/callback`.
- [ ] Connectors page: Connect button → starts OAuth flow. Revoke button → confirms, revokes.
- [ ] Agent settings: granting `mcp.outlook.email_read` to an agent with no connected Outlook → validation error or clear warning.
- [ ] Requires an Azure app registration (client id/secret) supplied by the operator as deployment config — document this as a setup prerequisite, not something CaberOS provisions.
- [ ] Tests: mock OAuth flow. Verify: connect → token stored encrypted → refresh → revoke clears credential. One real-account manual smoke test before release (not in the automated suite).
