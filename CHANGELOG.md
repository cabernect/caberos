# Changelog

All notable changes to CaberOS are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/).

Each GitHub release attaches the same desktop artifacts: a macOS Apple Silicon
`.dmg`, a Windows x64 `-setup.exe`, signed updater archives for both platforms,
and `latest.json` — the manifest the in-app updater polls to discover new
versions.

## [Unreleased] — 0.2.0 "Agent Workbench"

Integrated on `feat/v0.2.0`; release pending.

### Added

- **Agent Workbench UI**: the dashboard was rebuilt around the new shell —
  Today home, session chat with composer and attachments, trace inspection,
  Knowledge Vault, Skills Studio, browser, scheduler, channels, notifications,
  and settings — on the warm light/olive design system with dark mode.
- **Today — the operator home**: a "Needs you" strip collecting pending
  approvals, agent questions, failed runs, and unread notifications with deep
  links to the exact chat, trace, or setting that resolves them; a rollup of
  agent activity since you last looked; a rail listing what can leave the
  machine; and a composer that sends a task to any agent.
- **Trace inspection**: every run renders as a span tree + waterfall with an
  observation inspector — model calls, tool calls, approvals, and context are
  inspectable from the `model_calls` ledger with exact `call_id` correlation.
- **Knowledge Vault**: upload documents, search them with FTS5 lexical
  retrieval (hybrid embeddings opt-in, egress-consented), cite passages, and
  manage index generations. `.xlsx`/`.csv` uploads are refused with a clear
  reason pending the deferred row-query layer.
- **Evolving skills (RSI)**: after a session closes, a bounded reflection run
  can inspect frozen session evidence and stage edits to agent-local skills;
  published skills resolve versioned per run. The reflection concurrency cap
  drains oversized tool-call batches instead of failing them.
- **Managed browser automation**: Chrome-for-Testing under operator control —
  explicit first-use install consent, headless/visible modes, domain-scoped
  profiles, approval-gated actions, takeover requests, and download staging.
- **Durable scheduler**: once/interval/cron schedules with IANA timezones,
  persisted `next_fire_at`, missed-run sweep on restart, overlap and bounded
  retry policies. Heartbeat is now a facade over a managed schedule row.
- **Artifact Studio**: agents create and revise tracked deliverables
  (docx/xlsx/pptx/pdf) from structured specs with immutable revisions,
  restore-as-new, and external-edit conflict detection.
- **Notifications**: toast + inbox with SSE-first delivery, deep links, and
  unread dedupe.
- **Guided onboarding**: first-launch wizard for provider setup, first agent,
  and first run.
- **Windows x64 desktop build**: NSIS current-user installer
  (`-setup.exe`, no admin needed); no Python, Docker, or WSL required.
- **Attachments-only composer**: messages can send files without text; native
  drag-and-drop in the Migration and Knowledge Vault views on the desktop app.

### Changed

- Sessions close on an idle deadline and write a learning pass (summary +
  durable facts) instead of expiring silently.
- Orchestration directives: models that emit parallel action plans are nudged
  back to sequential reasoning instead of fanning out.

### Fixed

- Empty thinking blocks: reasoning-capable calls now request reasoning
  summaries so reported thinking tokens produce visible content.
- Re-clicking the active session no longer blanks the chat view.

### Platform notes

- **Windows shell sandbox** uses bundled Microsoft Execution Containers (MXC):
  experimental, requires Windows 11 24H2 (build 26100+), one-time elevated
  setup, system-drive workspaces only. Other capabilities work on Windows 10+.
- **macOS** desktop builds require Apple Silicon (macOS 13+) and use Seatbelt
  sandboxing with Docker fallback.
- **Linux** runs via Docker or source install (Bubblewrap sandbox with Docker
  fallback); no native desktop build yet.

## [0.1.9] — 2026-09-14

### Fixed

- `web_fetch` in the bundled gateway: trafilatura `settings.cfg` now ships in
  the PyInstaller bundle, with a BeautifulSoup fallback on extract errors.
- Empty chat view when re-clicking the active session.
- URL-substring alert matching made explicit in tests.

### Added

- `scripts/release.sh` — one-command version bump + tag + push, with a
  two-phase flow for protected `main`.
- Faster notifications: 5s polling plus instant refetch on SSE lifecycle events.

## [0.1.8] — 2026-09-08

### Added

- Public marketing + documentation website (English and Vietnamese), deployed
  as a Cloudflare static asset Worker.
- On-demand capability controls in the dashboard.

### Fixed

- Execution and MCP recovery stability pass.
- Dashboard theme polish, sidebar persistence, chat styling.

## [0.1.7] — 2026-09-03

### Added

- Progressive capability discovery persisted in run traces; on-demand
  capability controls.
- MCP grants preserved across discovery and migration; unavailable capability
  schemas invalidated before model turns.

### Fixed

- Packaged gateway startup failure.

## [0.1.6] — 2026-08-28

### Added

- Guided setup and notification workspace.
- Configurable bounded gateway logging.
- Stable desktop OAuth callback port.

### Fixed

- API errors no longer expose exception details.
- MCP OAuth and server cleanup; default agents preserved after local reset.

## [0.1.5] — 2026-08-27

### Added

- Knowledge experience: document upload, retrieval, and citation groundwork.
- Channel enable toggle moved beside settings.

## [0.1.4] — 2026-08-25

### Added

- Trusted knowledge foundation for the vault pipeline.

### Fixed

- Path-taint findings in knowledge uploads.

## [0.1.3] — 2026-08-24

### Fixed

- Slow startup: LiteLLM remote fetch skipped, channel loading moved to
  background.
- `web_search` switched to the `ddgs` package; auth rollback handling.

## [0.1.2] — 2026-08-20

### Added

- Data migration page with preview, merge, and replace modes.
- Persistent channel sessions with live dashboard streaming.
- Zalo Bot markdown rendering.

### Fixed

- MCP v2 (`mcp` package upgrade) OAuth token refresh across restarts.
- `web_search` POST queries and shared SSL/User-Agent for `web_fetch`.

## [0.1.1] — 2026-08-19

### Fixed

- `mcp` v2 client renames and unpack fixes; CI caching for uv, PyInstaller,
  and Rust builds.

## [0.1.0] — 2026-08-18

### Added

- First public release: FastAPI gateway, agent workspaces, capability
  mediation, approvals, audit trail, chat UI, channels, and Tauri desktop app
  for macOS.

[Unreleased]: https://github.com/cabernect/caberos/compare/v0.1.9...HEAD
[0.1.9]: https://github.com/cabernect/caberos/compare/v0.1.8...v0.1.9
[0.1.8]: https://github.com/cabernect/caberos/compare/v0.1.7...v0.1.8
[0.1.7]: https://github.com/cabernect/caberos/compare/v0.1.6...v0.1.7
[0.1.6]: https://github.com/cabernect/caberos/compare/v0.1.5...v0.1.6
[0.1.5]: https://github.com/cabernect/caberos/compare/v0.1.4...v0.1.5
[0.1.4]: https://github.com/cabernect/caberos/compare/v0.1.3...v0.1.4
[0.1.3]: https://github.com/cabernect/caberos/compare/v0.1.2...v0.1.3
[0.1.2]: https://github.com/cabernect/caberos/compare/v0.1.1...v0.1.2
[0.1.1]: https://github.com/cabernect/caberos/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/cabernect/caberos/releases/tag/v0.1.0
