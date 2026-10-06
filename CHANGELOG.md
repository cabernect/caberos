# Changelog

All notable changes to CaberOS are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Windows x64 desktop app (Tier 2, beta): NSIS installer, packaged gateway, WebView2 bootstrapper, per-user install
- Prioritized shell-sandbox backends with graceful degradation: Seatbelt (macOS) or bwrap (Linux) first, then a Docker fallback on those platforms
- Windows shell sandbox without Docker or WSL: the installer bundles Microsoft Execution Containers (MXC, MIT, hash-pinned at build time), auto-selected on Windows and reported as `experimental` because Microsoft does not yet call it a security boundary
- MXC sandbox gets an allowlisted environment: host variables (API keys, tokens) are never forwarded to sandboxed commands
- First-run "Enable shell sandbox" button in Observability → Health runs MXC's one-time elevated host setup (Windows shows its own permission prompt)
- `GET /api/health` reports `sandbox` (`kind`, `state`, `reason`, `setup_required`) and the gateway `version`; the dashboard flags a shell/gateway version mismatch
- Multi-platform release matrix; the updater manifest is built in a dedicated job that fails when a platform is missing
- `docs/platform-support.md` — canonical platform and sandbox-backend contract

### Fixed

- `get_backend()` raised `RuntimeError` on Windows and any non-macOS/Linux platform instead of degrading
- An "unavailable" sandbox result was cached for the life of the process, so starting a missing dependency never took effect without restarting the app; unavailable results are now re-probed on each call
- MXC policy blocked the UI subsystem, so ordinary console programs (`whoami`, PowerShell) died with `STATUS_DLL_INIT_FAILED`; the policy now enables UI while keeping clipboard and input injection blocked
- Packaged gateway lookup on Windows joined the `.exe` name to the directory name
- Windows process cleanup left orphaned gateways holding the fixed port; the gateway now runs inside a kill-on-close Job Object
- `RunEvent::Reopen` was compiled on every platform though it exists only on macOS
- Bundled YAML/JSON/manifest reads used the locale codepage on Windows (mojibake); now explicit UTF-8
- The Fernet key was left readable by other local users on Windows, where `chmod(0o600)` is a no-op; now restricted with an ACL
- Open-mode shell used `/bin/sh` on Windows; now `cmd.exe /c`
- `scripts/smoke.py` granted a non-existent capability name so the shell step silently did nothing
- `check-version.sh` assumed `python3`, which Windows does not provide

## [0.1.8] - Unreleased

### Added

- Approval batches for multiple tool calls emitted in one model turn, with decisions collected before approved calls execute
- Vietnamese (`vi`) public website and documentation routes with locale navigation, canonical URLs, and `hreflang` metadata

### Changed

- SQLite control-plane writes retry complete transactions after rollback with bounded exponential backoff
- Exhausted database contention returns a retryable `503 database_busy` response with `Retry-After`
- Website and documentation keep English as the default locale while providing Vietnamese content for every documentation route

### Fixed

- Preserve strict reason → act → observe → repeat execution boundaries while retaining same-turn tool concurrency
- Persist elicitation responses before waking the waiting agent run
- Make capability-save failures visible and restore server-confirmed state after a failed write
- Persist MCP connection failure notifications and startup reconciliation safely during transient database contention
- Honor a configurable MCP connection timeout and surface expired OAuth refresh tokens as explicit re-authentication failures instead of generic timeouts
- Automatically connect and discover MCP tools after successful OAuth authorization

### Security

- Approval and denial decisions remain persisted before in-process waiters are released

## [0.1.6] - Released

### Added

- Guided first-run setup for provider, model, and initial agent configuration
- Stable loopback gateway port for the Tauri desktop app
- Persistent operator notifications for run failures, approvals, MCP failures, and OAuth re-authentication
- Dedicated Notifications page with unread filtering and related-page actions
- Live system health status in the observability dashboard
- Expanded MCP catalog with setup-required entries for account-specific integrations
- Configurable logging levels and bounded desktop gateway log rotation

### Fixed

- OAuth access tokens refresh proactively using the provider-reported expiration
- Rotated OAuth refresh tokens are persisted for providers such as Notion
- OAuth callback URLs follow the configured gateway port
- Desktop app close confirmation uses the application confirmation UI

### Security

- Sanitized SQLite integrity-check and provider-validation failures so raw exception details remain in server logs instead of API responses or notifications

## [0.1.5] - Released

### Added

- Knowledge Vault document re-indexing for explicitly imported documents
- Persisted document sources and citation inspection in chat
- Focused frontend component tests with Vitest and React Testing Library

### Security

- Hardened archive, skill, workspace, sandbox, and database identifier path boundaries
- Sanitized OAuth redirect errors and user-facing internal failures
- Restricted CI workflow permissions to the jobs that need write access
- Validated browser URLs before opening them

## [0.1.0] - 2025-08-18

### Added

- Local-first AI Agent Operating System with headless FastAPI gateway
- React 19 dashboard with dark-only, conversation-first design
- Tauri desktop app (macOS Apple Silicon)
- Agent configuration system — agents are versioned DB rows, not code
- Three-layer memory: working memory (FTS5), MEMORY.md, knowledge graph (triples)
- Skills system with progressive disclosure (menu → load → read resource)
- MCP client infrastructure (stdio + HTTP, credentials, OAuth flow)
- Four external channels: Telegram, Discord, Zalo OA, Zalo Bot Platform
- Syscall boundary with approval flow, sandboxing, and audit logging
- Provider management with encrypted API keys (Fernet)
- Model discovery for OpenAI, Anthropic, Gemini, Ollama, OpenRouter, and 20+ more
- Non-chat models (embeddings, TTS, STT, image gen) filtered from discovery
- Observability dashboard with runs, syscall log, spend tracking, and health
- Scheduler with heartbeat mode
- Sub-agent support (`run_subagent`, `read_subagent`)
- Guardrails (secret detection, path injection, prompt injection)
- SSE streaming (typing, thinking, tokens, tool calls, turn complete)
- Attachment support (images, URLs, files)
- Thinking/reasoning controls (effort slider, brain icon)
- Copy-to-clipboard on rendered Markdown code blocks
- GitHub Actions CI (pytest, ruff, frontend build + lint)
- GitHub Actions release workflow (tag-triggered DMG build)
- SECURITY.md with GitHub private vulnerability reporting

### Security

- Provider API keys encrypted at rest (Fernet, AES-128-CBC + HMAC-SHA256)
- MCP credentials injected at runtime, never exposed in API responses
- Webhook endpoints validate configured secrets (timing-safe comparison)
- OAuth state validation (CSRF protection)
- Workspace path traversal protection (path relationship validation)
- Secret key file permissions enforced (0o600)
- Operator authentication (bcrypt, session + bearer token)

### Known Limitations

- macOS Apple Silicon only (no Intel or Windows builds yet)
- Single-operator (no multi-tenancy)
- Sessions stored in memory (lost on restart)
- Knowledge Vault UI deferred to v0.2
- CLI/TUI deferred to v0.2
- Cron/event triggers deferred to v0.5
