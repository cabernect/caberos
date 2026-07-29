# 10 — Connectors

## Goal

Build the connector system: OAuth flows for external services, encrypted credential storage (Fernet), and the first connectors (Outlook/email/calendar). Connectors are shared across agents — connect once, any agent can use the capabilities.

## Spec references

- **D13** — Connectors hold credentials; secrets are referenced, never inlined
- **D8** — Subject binding (Contact → mailbox/calendar)
- **D9** — Connector action capability kind
- **Stories 15-18** — connect service, encrypted token, see which agents use a connector, revoke

## Dependencies

- [01-database-layer.md](01-database-layer.md) — needs Connector, ConnectorCapability tables
- [04-syscall-layer.md](04-syscall-layer.md) — syscall layer injects credentials at call time
- [05-capabilities.md](05-capabilities.md) — connector actions are registered as capabilities
- [07-pipeline.md](07-pipeline.md) — connector actions are invoked through the execution pipeline

## Tasks

### 1. Implement secret encryption

`backend/src/agentos/secrets.py`:
- Use `cryptography.fernet.Fernet` for symmetric encryption
- Master key stored in a key file (`./data/secret.key`) with restrictive permissions (0600)
- Key generated on first run if not present
- `encrypt(plaintext) -> ciphertext`, `decrypt(ciphertext) -> plaintext`
- Secrets stored in DB as `secret://connector/{connector_id}/{credential_name}` references
- Actual encrypted values in a `secrets` table (or filesystem sidecar)
- **Never** return decrypted values to the dashboard, logs, or model context

### 2. Implement OAuth flow

`backend/src/agentos/connectors/oauth.py`:
- Generic OAuth 2.0 authorization code flow
- Configurable per-connector: `client_id`, `client_secret`, `auth_url`, `token_url`, `scopes`, `redirect_uri`
- **Loopback redirect URI (Decision 10):** register `http://localhost:8081/api/connectors/oauth/callback` as the redirect URI with Microsoft/Google
  - The OAuth redirect happens in the user's browser, which is on the same machine as the control plane, so it hits the control plane directly — no tunnel needed
  - `localhost` resolves to `127.0.0.1`, so this is the same socket as D4's control plane binding
- `GET /api/connectors/oauth/callback` — OAuth callback handler on the control plane
- Token refresh logic (store refresh token, refresh when access token expires)
- Token stored encrypted via the secret store

### 3. Build connector interface

`backend/src/agentos/connectors/base.py`:

```python
class Connector(ABC):
    name: str                        # "outlook", "gmail", "calendar"
    type: str                        # connector type
    capabilities: list[str]          # ["email.read", "email.send", ...]

    async def connect(self, credentials: dict) -> None: ...
    async def execute(self, action: str, args: dict, subject: dict) -> Any: ...
    async def disconnect(self) -> None: ...
```

### 4. Implement Outlook connector

`backend/src/agentos/connectors/outlook.py`:
- Uses Microsoft Graph API
- OAuth scopes: `Mail.Read`, `Mail.Send`, `Calendars.Read`, `Calendars.ReadWrite`
- Capabilities:
  - `email.read` — read emails (subject-scoped, resolves to bound mailbox)
  - `email.send` — send email (subject-scoped, `require_approval` recommended)
  - `calendar.read` — read calendar events
  - `calendar.create` — create calendar event
- Uses `httpx` for API calls
- Egress: true (leaves the machine)

### 5. Implement Gmail connector (optional for v0.1 stretch)

`backend/src/agentos/connectors/gmail.py`:
- Uses Gmail API
- Similar capability set to Outlook
- OAuth via Google

### 6. Build connector registration

`backend/src/agentos/connectors/registry.py`:
- Register connector capabilities in the capability registry on startup
- Each connector action becomes a `CapabilityDef` of kind `connector_action`
- The `execute` function calls `connector.execute(action, args, subject)`
- Credentials are injected by the syscall layer (not by the connector itself)

### 7. Create API routes

`backend/src/agentos/api/connectors.py`:
- `GET /api/connectors` — list all connectors (name, type, capabilities, connected)
- `POST /api/connectors/{type}/connect` — start OAuth flow
- `GET /api/connectors/oauth/callback` — OAuth callback
- `DELETE /api/connectors/{id}` — revoke connector (deletes credentials, unregisters capabilities)
- `GET /api/connectors/{id}/agents` — which agents use this connector (blast radius, story 17)

### 8. Implement subject binding for connectors

- When a Contact is bound to an email mailbox (D8), the binding stores the mailbox address
- `email.read()` resolves to that mailbox via the syscall layer
- The connector receives the resolved mailbox, not a model-supplied one

## Files to create

- `backend/src/agentos/secrets.py`
- `backend/src/agentos/connectors/__init__.py`
- `backend/src/agentos/connectors/oauth.py`
- `backend/src/agentos/connectors/base.py`
- `backend/src/agentos/connectors/outlook.py`
- `backend/src/agentos/connectors/gmail.py` (stretch)
- `backend/src/agentos/connectors/registry.py`
- `backend/src/agentos/api/connectors.py`
- `backend/tests/test_connectors.py`

## Verification

- Encrypt a token → decrypt → matches original
- Encrypted token never appears in API responses or logs
- OAuth flow: redirect → callback → token stored encrypted
- `email.read()` with bound Contact → returns emails from the bound mailbox
- `email.read()` with unbound Contact → denied, reason "no subject binding"
- `email.send()` with `require_approval` → ApprovalRequest created
- Revoke connector → credentials deleted, capabilities unregistered, agents that used it lose access
- `GET /api/connectors/{id}/agents` → lists agents using this connector
- `uv run pytest tests/test_connectors.py` passes (mock OAuth + API calls)
