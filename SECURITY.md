# Security Policy

## Reporting a vulnerability

If you discover a security vulnerability in CaberOS, please report it via **GitHub's private vulnerability reporting**:

1. Go to the repo's **Security** tab → **Report a vulnerability**
2. Fill in the advisory form:
   - Description of the vulnerability
   - Steps to reproduce
   - Potential impact
   - Suggested fix (if any)
3. Submit — the report is private and only visible to repository maintainers

**Do NOT open a public GitHub issue for security vulnerabilities.**

You will receive a response within 48 hours. If the vulnerability is confirmed, the maintainer will:
1. Create a private fork to develop the fix
2. Publish a GitHub Security Advisory once the fix is released
3. Request a CVE ID if the vulnerability warrants one

To enable this feature in your fork: **Settings → Security → Code security → Private vulnerability reporting → Enable**.

## Security architecture

CaberOS is a **local-first** application. This means:

- **Your data never leaves your machine.** The backend runs locally (as a daemon, Docker container, or PyInstaller bundle inside the Tauri desktop app).
- **Provider API keys** (OpenAI, Anthropic, Google, etc.) are stored encrypted at rest using **Fernet symmetric encryption** (`cryptography` library). The encryption key is stored in a file with `0o600` permissions.
- **Model requests** go directly from your machine to the provider (via LiteLLM). No intermediary server.
- **The SQLite database** is stored locally. No cloud sync, no telemetry, no phone-home.

### Authentication

| Mechanism | Implementation |
|---|---|
| Password hashing | bcrypt with auto-generated salt |
| Session tokens | `secrets.token_urlsafe(32)` — 256 bits of entropy |
| Session storage | In-memory dict (lost on restart — by design for v0.1) |
| Browser auth | HttpOnly cookie (`agentos_session`, `SameSite=Lax`) |
| Desktop auth | `Authorization: Bearer <token>` header (Tauri webview) |
| Default credentials | `admin` / `admin` — forced password change on first login |

### Credential encryption

All secrets are encrypted at rest using Fernet (AES-128-CBC + HMAC-SHA256):

- Provider API keys
- MCP server credentials (API keys + OAuth tokens)
- Channel bot tokens (Telegram, Discord, Zalo)

The Fernet key is generated on first run and stored at `AGENTOS_SECRET_KEY_PATH` (default: `data/secret.key`) with `0o600` file permissions. The key file is gitignored.

### Sandbox

Shell commands run inside a process sandbox:

| Platform | Sandbox | Restrictions |
|---|---|---|
| macOS | `sandbox-exec` (seatbelt) | Write access limited to workspace; read access to system dirs; no network in strict mode |
| Linux | `bubblewrap` (bwrap) | `--unshare-all` (network, PID, IPC, mount); read-only system dirs; write only to workspace |

**YOLO mode** (`AGENTOS_YOLO_MODE=true`) bypasses all approval gates and sandbox restrictions. Use only in trusted environments. Disabled by default.

### Approval flow

Every egress capability (shell commands, web requests) requires explicit operator approval before execution. The operator can:
- Approve once
- Approve for the same scope (exact command, same verb, pattern, capability)
- Deny and stop the run

Approval decisions are logged in the audit trail.

### Guardrails

Input and output guardrails run on every message:

- **Secret redaction** — detects and redacts API keys (OpenAI `sk-*`, Anthropic `sk-ant-*`), AWS keys, GitHub tokens, and other common secret formats before they reach the model or are stored in the DB
- **Prompt injection detection** — flags common injection patterns (ignore previous instructions, system prompt extraction attempts)
- **System prompt leakage prevention** — detects attempts to extract the system prompt

## Security measures implemented

### Fixed in this audit

| Issue | Severity | Fix |
|---|---|---|
| Provider API endpoints had no authentication | CRITICAL | Added `require_operator` to all 9 provider endpoints |
| Webhook endpoint accepted requests without secret verification | CRITICAL | Added `hmac.compare_digest` verification of `X-Webhook-Secret` / `X-Bot-Api-Secret-Token` header |
| OAuth callback didn't validate `state` parameter | CRITICAL | Added state validation against expected flow state (CSRF protection) |
| Webhook secret returned in plaintext in API responses | WARNING | Changed to `has_webhook_secret: boolean` — secret never exposed in API responses |
| Secret key file permissions not enforced on existing files | WARNING | Added `chmod(0o600)` on every key load, not just creation |
| Path validation vulnerable to symlink attacks | WARNING | Replaced `startswith()` with `relative_to()` for proper symlink-safe path containment |

### Existing security practices

- **SQLAlchemy ORM** used for all application queries — no raw SQL with user input
- **Fernet encryption** for all credentials at rest
- **bcrypt** for password hashing
- **HttpOnly cookies** for browser session management
- **No debug mode** in production
- **`.gitignore`** excludes `.env`, `*.key`, `*.db`, `data/`, build artifacts
- **No secrets in git history** — verified via `git log --pickaxe` scan
- **CORS** restricted to `localhost:5173`, `127.0.0.1:5173`, `tauri.localhost`, `tauri://localhost`
- **Password hashes** never returned in API responses (`OperatorOut` excludes `password_hash`)
- **Provider API keys** never returned in plaintext (`ProviderOut` returns `has_key: boolean`)
- **MCP credentials** never returned in plaintext (only metadata: id, type, label)

## Known limitations (v0.1)

These are known security limitations that are accepted for v0.1 but should be addressed in future versions:

### Single-operator model

CaberOS v0.1 is designed for a single operator. There is no multi-tenancy or role-based access control. Any authenticated operator can access all agents, configurations, and data. Multi-operator support is planned for v0.5+.

### In-memory sessions

Session tokens are stored in an in-memory dictionary. All sessions are invalidated when the backend restarts. This is acceptable for a local-first app but will be replaced with DB-persisted sessions in a future version.

### Session token in login response

The login response includes `session_token` in the JSON body. This is required for the Tauri desktop app, which uses bearer-token auth (the webview can't reliably use cookies cross-origin). The token is also set as an HttpOnly cookie for browser clients.

### Default admin credentials

The first-run default is `admin` / `admin` with `must_change_password=True`. This is intentional for usability — the operator is forced to change it on first login. If you're deploying CaberOS in a shared environment, change the password immediately.

### macOS sandbox profile

The seatbelt profile allows `file-read*` and `process-exec*` broadly. This is necessary for the shell capability to function (agents need to run arbitrary commands). The approval gate is the primary control — no command runs without operator consent (unless YOLO mode is enabled).

### DDL uses string interpolation

Schema management functions in `db_backends/sqlite_backend.py` and `db_backends/postgres_backend.py` use f-string interpolation for DDL statements (`ALTER TABLE`, `PRAGMA`). These are called with hardcoded values only — no user input reaches them. SQLAlchemy doesn't support parameterized DDL identifiers, so this is an accepted limitation.

### Floating dependency ranges

Backend dependencies use floating ranges (`>=X.Y.Z`). The `uv.lock` file pins exact versions for reproducible builds. A future CI step will add `pip-audit` or `safety` for dependency vulnerability scanning.

## Best practices for users

### Change the default password immediately

```bash
# On first login, you'll be prompted to change your password.
# If you skip it, change it via the Settings page in the dashboard.
```

### Protect your data directory

```bash
# The data directory contains your DB, encryption key, and workspaces.
# Ensure it's not world-readable:
chmod -R 700 ~/Library/Application\ Support/com.caberos.desktop/  # macOS desktop
chmod -R 700 data/  # local dev
```

### Don't enable YOLO mode in shared environments

YOLO mode (`AGENTOS_YOLO_MODE=true`) skips all approval gates. Only use it on a trusted machine where you're the only operator.

### Keep your encryption key safe

The Fernet key at `data/secret.key` (or `AGENTOS_SECRET_KEY_PATH`) is the only thing protecting your credentials at rest. If you lose it, all encrypted credentials become unrecoverable. If someone gains access to it, they can decrypt all your stored API keys.

```bash
# Back up your key securely (not in the repo!):
cp data/secret.key ~/secure-backup/agentos-key-backup
```

### Use webhook secrets for external channels

When configuring Telegram, Discord, or Zalo channels in webhook mode, always set a webhook secret. Without it, anyone who knows your webhook URL can trigger agent runs.

### Review the audit log regularly

The Observability page → Syscall Log shows every capability call with arguments and results. Review it periodically to ensure agents are behaving as expected.
