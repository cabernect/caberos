# Changelog

All notable changes to CaberOS are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/).

Each GitHub release attaches the same desktop artifacts: a macOS Apple Silicon
`.dmg`, a Windows x64 `-setup.exe`, signed updater archives for both platforms,
and `latest.json` — the manifest the in-app updater polls to discover new
versions.

## [Unreleased]

## [0.2.5] — 2026-11-25 "Cleanup & Stability"

### Changed

- Organize the harness and inbound pipeline into named phases; extract run-event
  persistence with one database lock shared by events and tool transactions.
- Split built-in capability registration by domain, settings by tab, and
  conversation rendering into focused components without changing public APIs.
- Consolidate frontend upload/download requests and backend fresh-session
  persistence helpers.
- Remove the unused shadcn CLI and its dependency tree from app dependencies.

### Fixed

- Serialize parallel tool-approval event persistence with tool database
  transactions. Concurrent commits on the shared run session could otherwise
  fail cleanup, leave SQLite locked, and prevent subsequent runs from starting.
- Preserve authentication headers when combining frontend request options.
- Reset slideshow state before preview controls become interactive, preventing
  a late mount effect from closing a newly opened slideshow.

### Security

- Update Soup Sieve to 4.1.3 for CSS-selector resource-exhaustion fixes.
- Update Astro to 7.4.13 for HTML attribute-injection and image-endpoint path
  containment fixes. Website builds now require Node.js 22.23.4 or newer.
- Apply compatible Rust cookie, URL parser, and filesystem patches. Remaining
  upstream maintenance and Linux GLib findings are documented in
  `docs/plans/v0.2.5-dependency-audit.md`; no advisories are suppressed.

## [0.2.4] — 2026-11-23 "Browser Continuity & Updates"

### Added

- Desktop update polling every four hours, alongside the startup check.
  Settings -> About keeps manual checking available after success or failure.
- Context usage tooltips show cached tokens as a percentage of context used.
- Multi-tab browsing through the existing tools: `browser_observe` lists tabs;
  `browser_act` can open, switch, and close tabs without replacing other pages.
  Tabs persist across runs in the same live conversation browser.

### Changed

- Managed browsers belong to the conversation rather than individual runs.
  Follow-up runs can observe and act on the existing page; Stop preserves it.
  Headless browsers expire after ten idle minutes. Explicit browser close,
  successful conversation close, and app shutdown release the browser.

### Fixed

- Browser reuse and close enforce agent/session ownership; concurrent opens
  cannot claim the same named profile or launch duplicate session browsers.
  Actions on one browser are serialized to protect shared page state.
- Concurrent update checks are deduplicated and cannot overwrite download,
  installation, or restart-ready state. Failed downloads can be retried,
  and update-check resources are released after use.

## [0.2.3] — 2026-11-20 "Context Hotfix"

### Added

- **Editable auto-compact threshold**: agent settings expose the compaction
  threshold (percent of context window, default 70%) via `PUT
  /api/agents/{id}` and the General settings tab; partial updates merge
  with existing compaction settings and out-of-range values return 422.

### Fixed

- **Runaway context from stored tool results**: stored `tool_call` rows
  replayed verbatim into later runs, so a single oversized result (e.g. an
  ~870KB terminal screenshot) could push session context past 600k tokens
  even though the live path capped each result at 50k chars.
  `format_stored_message` now applies the same `TOOL_RESULT_MAX_CHARS`
  bound at replay; the database keeps full bytes for audit.
- **`/compact` reporting "nothing to compact" on tail-only histories**:
  forced tail pruning ran after the empty-middle early return, so manual
  compaction could never shrink a giant protected-tail payload. Tail
  pruning now runs first and its savings are reported honestly.
- **Static HTML preview hiding no-JS fallbacks**: the sanitizer dropped
  `<noscript>` entirely; it now unwraps it so author-provided fallbacks
  (e.g. scroll-reveal overrides) render in the scripts-disabled preview.

## [0.2.2] — 2026-11-19 "Artifact Craft & Preview"

### Added

- **Structured artifact authoring**: agents create tracked deliverables from
  structured specs via `artifact_create`, inspect them with
  `artifact_inspect`, and apply targeted, base-revision-checked edits with
  `artifact_revise`. Existing files become tracked via `artifact_adopt` or
  the preview panel's "Track history" action; `artifact_history` and
  `artifact_restore` keep every revision recoverable.
- **Presentations**: one canonical `.deck.json` spec feeds the in-app slide
  renderer and native PPTX export — layouts, native text/shapes/tables/
  charts, speaker notes, and pinned image snapshots. Browser motion plays
  in the app; PPTX export is a disclosed static snapshot (exported metadata
  records `browser_motion_exported: false`). PDF export is bound to the
  same spec revision.
- **DOCX craft**: named styles, covers, section breaks, headers/footers
  with page fields, table sizing and repeated headers, image sizing,
  stable block IDs, and block-level revision operations — all editable in
  Microsoft Word.
- **XLSX craft**: multi-sheet workbooks with fills, borders, alignment,
  number formats, merges, freeze panes, auto-filter, native tables and
  charts, bounded data validation and conditional formatting. Formulas
  are authored as real formula cells and recalculate in Excel; CaberOS
  never claims to evaluate them. Uploaded workbooks get feature preflight
  and preservation gates — revisions refuse to silently drop unsupported
  features until acknowledged.
- **`edit_file` capability**: exact, unique-fragment replacement for
  existing UTF-8 files — small edits no longer require regenerating the
  whole file. Missing or ambiguous matches refuse without writing;
  `write_file` remains for creation and full replacement.
- **Tool-call preparation streaming**: the chat shows
  "Preparing `tool_name`…" with a live character count as soon as a tool
  name streams, instead of appearing idle while large arguments generate.
  Nothing executes until the call is complete.
- **Window state persistence**: the desktop app remembers its size,
  position, and maximized state across launches.
- **Desktop notifications**: the unread inbox count mirrors onto the
  macOS Dock badge, and OS alerts play an explicit sound instead of
  posting silently.

### Changed

- **Reuse installed runtimes**: MCP and terminal prefer explicit overrides,
  then existing healthy managed runtimes, then compatible standard system installs
  such as Homebrew. No duplicate managed download is required; managed installation
  stays opt-in. Auto selection excludes private-home managers and symlinks into
  private locations. Strict gets read/execute
  access to selected managed version trees, not the surrounding data directory,
  and cannot modify the shared runtime store. Project dependencies/caches stay
  in the workspace. Explicit source pins and binary overrides do not silently
  fall back to another source.
- **Strict terminal networking**: Strict now confines filesystem writes while
  allowing network access for package installs and development servers.
  Workspace content can be sent externally, and terminal calls can reach
  localhost/LAN services. Package cache/prefix/temp defaults stay in the
  workspace; Strict is not an offline or data-loss-prevention mode.
- **Shared preview experience**: one renderer contract across chat,
  Workspace, and Skill resources — slide navigation and slideshow,
  workbook sheet tabs with a formula bar, cell/range selection with
  status-bar statistics, per-source zoom, and a revision-bound "Revise"
  action that prefills a draft without auto-submitting. Old chat
  revisions open the exact stored bytes and flag newer workspace
  versions without auto-switching.
- **Workspace panel**: controls now use the shared design tokens and
  components; the file list collapses for narrow panels. Authored
  document colors are preserved in dark mode.
- **External links in chat** open in the system browser instead of
  navigating the desktop app window itself.
- **Desktop preview actions**: the workspace "Open" button was removed in
  favor of "Reveal" (platform-aware label) to avoid widening the
  file-open permission scope.

### Limitations (unchanged by design)

- Office previews are extracted-content, best-effort views with a
  persistent limitation notice — no Office layout engine is bundled.
- PPTX playback of transitions/animations is not shown in-app; export is
  a static, disclosed snapshot.
- Formula results are never fabricated: formulas are stored, not
  recalculated.
- Ordinary HTML previews are static with scripts, navigation, and
  external resources disabled.
- Autonomous visual review (W5) is deferred; JSON inspection remains the
  verification contract.
- Windows and Docker packaged runs are not verified in this release
  cycle; macOS Apple Silicon is the validated desktop platform.

## [0.2.1] — 2026-11-10 "Honest Vault, Workspace & Tools"

### Added

- **Existing-folder workspaces**: select any project directory at agent
  creation or in Settings — via native dialog on the desktop app or the
  home-confined folder picker on the web. Sessions pin their workspace
  location, so changing the agent default affects new conversations only.
- **Workspace provenance for legacy sessions**: historical roots resolve
  from recorded run evidence. Sessions with unknown or conflicting history
  fail with a clear reason instead of silently switching to today's
  default; artifact previews follow the same provenance rules.
- **Vault chunk inspection**: browse the persisted parent/child chunk tree
  of any document — structure, source locations, token counts, and bounded
  text through a lazy, paginated inspector.
- **Tabular Vault sources**: CSV and XLSX uploads now persist typed sheets,
  rows, and cells. Agents get `doc_query_rows` for allowlisted filters,
  counts, and aggregates computed over the complete matching set — counts
  and aggregates stay exact regardless of page size. Legacy `.xls` remains
  unsupported.
- **Settings → Tools**: global tool bindings configure *how* capabilities
  execute — provider, model, and options per operation — with readiness
  reporting and modality-filtered model suggestions. Bindings never widen
  agent permissions; capability grants still decide *who* may call what.
- **Configurable search services**: `web_search` can run on Tavily, Exa,
  Brave Search, or Firecrawl (Cloud or self-hosted) alongside the free
  DDGS default, with dedicated provider credentials in the same encrypted
  store. Search results remain trace evidence, never auto-cited references.
- **Image generation and editing**: mediated `image_generate` and
  `image_edit` capabilities produce validated output staged as tracked
  artifacts, displayed inline, with every provider attempt recorded in the
  model-call ledger.
- **Speech**: batch dictation into an editable composer draft and explicit
  per-message Read Aloud — no unsolicited playback. Speech-to-text and
  text-to-speech bind independently to OpenAI-compatible, OpenRouter,
  ElevenLabs, or Gemini services; generated audio is cached for replay.
- **Local terminal backend selection**: strict-mode background terminals
  keep their admitted backend; Auto preserves OS-native selection while
  explicit choices fail honestly when unavailable. A transport seam
  prepares for remote drivers without shipping them.
- **Conversation compaction feedback**: `/compact` shows visible
  session-scoped submission, progress, and outcome — compacted, unchanged,
  or failed — instead of completing silently.
- **MCP improvements**: query-based capability discovery and simpler
  server setup flows.

### Changed

- **pypdf** upgraded to `>=6.21.4,<7.0.0`, clearing seven Dependabot
  high-severity advisories without a major-version jump.

### Fixed

- **Web folder browser confinement**: directory browsing resolves and
  verifies paths inside the operator's home before listing; traversal and
  symlink escapes are refused. External workspaces remain configurable by
  path or native dialog.
- **Run lifecycle edge cases**: refused admissions persist a failed run and
  emit their startup event; events fired before run-context registration
  replay instead of leaving runs stuck or misreported.
- **Speech reliability**: stale synthesis results can no longer start
  playback for a superseded request, and message navigation cancels
  pending audio.
- **Image staging validation**: write destinations are verified before
  bytes land.
- **Network policy hardening**: `web_fetch` destination classification,
  browser navigation checks, MCP HTTP transport policy, and cached OAuth
  binding revalidation.
- **Terminal and sandbox hardening**: process-group cleanup, bounded
  output, cancellation paths, requested Docker resource/privilege limits,
  and layered Seatbelt confinement.

### Platform notes

- Remote terminal execution (SSH, Daytona, Modal), realtime two-way Voice
  Mode, video generation, and agent-authored apps are **not** in this
  release.
- Native sandbox enforcement beyond the macOS dev host — and the four
  opt-in live Seatbelt tests — still require dedicated runner evidence.
- One low-severity `deepmerge` advisory remains open; it arrives
  transitively via the shadcn CLI and has no patched release to upgrade to.

## [0.2.0] — 2026-10-30 "Agent Workbench"

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

[Unreleased]: https://github.com/cabernect/caberos/compare/v0.2.4...HEAD
[0.2.4]: https://github.com/cabernect/caberos/compare/v0.2.3...v0.2.4
[0.2.3]: https://github.com/cabernect/caberos/compare/v0.2.2...v0.2.3
[0.2.2]: https://github.com/cabernect/caberos/compare/v0.2.1...v0.2.2
[0.2.1]: https://github.com/cabernect/caberos/compare/v0.2.0...v0.2.1
[0.2.0]: https://github.com/cabernect/caberos/compare/v0.1.9...v0.2.0
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
