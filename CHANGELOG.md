# Changelog

All notable changes to CaberOS are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).



## [Unreleased]

### Added

- Windows x64 desktop support (Tier 2, beta) — NSIS installer, packaged gateway, WebView2 bootstrapper
- Windows shell sandboxing by delegating to bubblewrap inside WSL2, reusing the Linux isolation profile
- Sandbox availability reported by `GET /api/health` and shown on the Observability → Health tab, naming any missing dependency
- `docs/platform-support.md` — canonical platform tier contract, linked from README and AGENTS.md
- Gateway version reported over `/health`; the dashboard flags a shell/gateway version mismatch after an update
- Multi-platform release matrix, with the updater manifest built in a dedicated job that fails when a platform is missing

### Fixed

- `get_backend()` no longer raises on unsupported platforms — the shell capability is refused with a reason instead, leaving the other 21 capabilities working
- The bwrap availability probe bound no filesystem, so it failed with "execvp /bin/sh: No such file or directory" on every host and reported working sandboxes as unavailable
- Packaged gateway crashed on startup with "attempted relative import with no known parent package" — the frozen entry point runs as `__main__` and needs absolute imports
- The desktop shell could not locate the gateway on Windows, where the PyInstaller directory and executable names differ
- Windows process cleanup left orphaned gateway processes holding the fixed port; the gateway now runs inside a kill-on-close Job Object
- `datetime_now` rejected every named timezone on Windows, which ships no system tz database
- The Fernet key was left readable by other local users on Windows, where `chmod(0o600)` only toggles the read-only flag
- `check-version.sh` ignored `agentos/__init__.py`, which had drifted to 0.1.5, and assumed a working `python3` that Windows does not provide
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
