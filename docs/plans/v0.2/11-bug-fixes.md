# v0.2 Bug Fixes and Hardening (W11)

## Outcome

Known defects found during W3 development are fixed or honestly bounded, with
regression tests. This ticket is a living list — append newly found bugs rather
than filing ad-hoc.

## Dependencies

- 08b MCP OAuth machinery (already built — discovery, DCR, PKCE, token persistence)

## Bugs

### B1 — HTTP MCP servers don't discover OAuth on 401

**Symptom:** adding `{"type": "http", "url": "https://mcp.tradingview.com/mcp"}`
fails with `mcp_connection_failed` + "Server returned an error response".

**Root cause:** OAuth wiring is opt-in via `server.oauth_config` set at creation
(`mcp/registry.py:143`). A server added without it connects with a bare client;
the server's 401 + `WWW-Authenticate: Bearer resource_metadata=...` is treated
as a generic failure, never as "start OAuth". Claude Code et al. treat auth
discovery as part of the transport handshake — minimal config suffices there.

**Fix:**
- On failed HTTP connect (no `oauth_config`), probe `initialize` once; if the
  response is 401 carrying `resource_metadata`, auto-set `oauth_config`
  (default scope, default callback URI) so the server reports
  `auth_type: "oauth"` and the existing Connect-with-OAuth UI appears.
- Notification becomes "requires OAuth — connect via dashboard" instead of
  "Server returned an error response".
- `PATCH /servers/{id}` gains the ability to change `auth_type`/`oauth_config`
  so a misconfigured server is fixable without delete/re-add.

## Tests first

- Fake HTTP MCP that 401s with `WWW-Authenticate` → server gains
  `oauth_config`, notification says OAuth-required; PATCH auth_type change.

## Done when

- A minimal `{type: http, url}` server that requires OAuth ends up connected
  after one user consent — matching Claude Code behavior.
- No known-bug entries remain without either a fix or an explicit documented
  limitation.
