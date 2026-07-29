# 08 — Connectors (Outlook)

**What to build:** The operator connects an Outlook account via OAuth (loopback redirect flow). The connector stores the credential encrypted (Fernet). The agent can now read email, send email (with approval), and read the calendar. Connectors are shared across agents — one Outlook connection serves any agent granted the `email.read` capability. The connectors page shows connected services, their capabilities, and which agents use them (blast radius).

**Blocked by:** 04 — Approval flow (email.send requires approval — the operator approves before an email is sent).

**Status:** ready-for-agent

- [ ] OAuth loopback redirect: the connector starts a local HTTP server on a loopback port, redirects the user to Microsoft's OAuth page, receives the callback with the auth code, exchanges it for tokens. Tokens stored encrypted (Fernet, same secret store as provider keys). Refresh token used to maintain access.
- [ ] Fernet secret store: `cryptography` library. Encryption key stored in `~/agentos/secret.key` (generated on first run, 0600 perms). All secrets (connector tokens, provider API keys) encrypted with this key. Never logged in plaintext.
- [ ] Connector model: `Connector` (id, name, type, credential_ref, created_at). `ConnectorCapability` (connector_id, capability_name). One connector exposes multiple capabilities (email.read, email.send, calendar.read).
- [ ] Outlook connector: implements email.read (list messages, get message), email.send (send message), calendar.read (list events, get event). Uses Microsoft Graph API. Credentials injected by the syscall layer (the agent never sees the token — D10).
- [ ] Connector capabilities registered: `email.read`, `email.send`, `calendar.read` — kind: `connector_action`. Subject-scoped (the operator's own data — `subject: self`). `email.send` has `require_approval: true` by default.
- [ ] Connectors page: list connected services (name, type, capabilities, connected status). Connect button → starts OAuth flow. Revoke button → confirms, revokes. Per-connector: list of agents using it (blast radius).
- [ ] Agent settings: capabilities list now includes connector actions (grouped under "Connectors"). Granting `email.read` to an agent that has no connected Outlook → validation error or clear warning.
- [ ] Audit: connector actions are audited like all syscalls. The audit record shows which connector was used, which capability, and whose data was accessed.
