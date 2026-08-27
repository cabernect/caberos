# Changelog

All notable changes to CaberOS are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.51] - Unreleased

### Fixed

- Added Gatekeeper workaround instructions for the free, non-notarized macOS Apple Silicon DMG release.

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
