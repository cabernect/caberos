# CaberOS — Technical Reference

Deep reference for the v0.2.0 architecture. For conventions and workflow see `../AGENTS.md`; for product framing see `docs/PRODUCT.md`; for rationale see `docs/spec-v0.1.md` (D1–D40) and `docs/plans/`.

---

## 1. Architecture layers

```
Clients (React dashboard · Tauri shell · external channels · future CLI)
        │  REST + SSE (bearer token or session cookie)
        ▼
FastAPI gateway (api/* routers) — transport only, no business logic of its own
        ▼
runner.py → pipeline.py → harness/loop.py
        │                    │            │
        │                    │            └── SyscallHandler protocol
        │                    │                  (approval gate · credential
        │                    │                   injection · sandbox · audit)
        │                    └── model adapter (LiteLLM; ScriptedModel in tests)
        └── session lifecycle: open → idle sweep → close (learning) → reflection
        ▼
Storage: SQLite WAL + FTS5 (Postgres optional) · filesystem workspaces ·
         Fernet-encrypted secrets
```

All entry points converge on `run_agent()` → `Pipeline.handle_inbound()` → `Harness.run()`. The transport (SSE, channel poller, scheduler) only supplies an `event_callback`.

## 2. Module map (`backend/src/agentos/`)

| Path | Role |
|---|---|
| `main.py` | FastAPI app: API routers, CORS, lifespan (startup reconcile, sweeper, scheduler, channel boot) |
| `runner.py` | `run_agent()` — DB session, model selection, harness+pipeline wiring, event emission |
| `run_manager.py` | `RunContext` registry, start/stop/get, in-memory window over durable rows |
| `pipeline.py` | Inbound pipeline: session resolution, manifest assembly, run record, attachment persistence, sweeper pokes |
| `config.py` / `config_schema.py` | Env settings (`AGENTOS_*`); Pydantic `AgentConfig`/`Limits`/`ModelConfig` |
| `agent_service.py` | Agent CRUD, version snapshots, YAML import/export |
| `versioning.py` | AgentVersion write path |
| `db.py` / `db_backends/` | Engine + `init_db()` (create_all + patches); SQLite/Postgres backend split |
| `auth.py` | Operator auth — session cookie **or** `Authorization: Bearer` (desktop), bcrypt |
| `seed.py` | First-run operator + capabilities seed |
| `defaults/` | `caber.yaml`, `agent-builder.yaml` — bundled into PyInstaller builds |
| `notifications.py` | `create_notification()` dedupe by type+entity+unread; SSE fan-out |
| `session_activity.py` | `session_activity` SSE frames; `learning` flag on sessions list |
| `reflection.py` | RSI skill-reflection pass — restricted Harness run over frozen session evidence |
| `redaction.py` | Shared read boundary for audit/timeline payloads — fails closed |
| `manifest.py` | `ExecutionManifest` assembly — pinned revisions per run |
| `previews.py` | Byte classification → bounded renderers (md/code/csv/image/pdf/office/media) |
| `runtime_installer.py` / `runtime_support.py` / `dependencies.py` | Consent-gated managed installs for optional tools/runtimes |
| `scheduler.py` | Durable schedule engine — tick, missed-run sweep, occurrence spawn |
| `secret_store.py` / `ssl_utils.py` | Fernet key custody; shared CA bundle (corporate firewalls) |
| `api/` | routers — see §5 |
| `capabilities/` | Registry, catalog metadata, effects, `builtin.py` registration, `tools/` impls |
| `syscall/` | `mediator.py` (the boundary), `protocol.py`, per-session lock, approval/elicitation registries |
| `harness/` | `loop.py` (reason→act→observe), `context.py` (assembly + multimodal), `conversation.py` (reads + compaction budgeting), `base_prompt.py`, `litellm_adapter.py`, `scripted_model.py`, `guardrails.py` |
| `memory/` | `core.py` (MEMORY.md publication), `episodic.py` (close_session, idle scan), `auto_extract.py`, `triples.py`, `recall.py`, `history_queries.py`, `notebook.py` (legacy) |
| `skills/` | `resolution.py` (effective set), `reconcile.py` (built-in seed/retire), `service.py` (Studio ops), `usage.py` + `usage_queries.py` (activations), `importer.py` (ZIP/repo hardening), `validate.py`, `builtins.py` (`BUILTIN_SKILLS`) |
| `knowledge/` | `ingest.py`, `extractors.py`, `chunker.py` (parent/child), `retrieval.py` (FTS + RRF), `embeddings.py`, `vectors.py`, `indexing.py` (generations) |
| `artifacts/` | Format handlers — docx/xlsx/pptx spec→bytes, pdf build+inspect |
| `browser/` | Managed Chrome-for-Testing runtime, CDP session control, profiles, domain leash |
| `mcp/` | `client.py` (stdio/HTTP), `registry.py`, `credentials.py`, `oauth.py` |
| `channels/` | `base.py` (Channel ABC), `registry.py`, telegram/discord/zalo_oa/zalo_bot |
| `sandbox/` | `seatbelt.py` (macOS), `bwrap.py` (Linux), `docker.py`, MXC (Windows), `workspace.py` (`resolve_within`) |
| `terminal/` | Background terminal sessions — incremental output, ownership, process-group cleanup |
| `models/` | SQLAlchemy tables — see §4 |
| `services/` | `model_ledger.py`, `observability_timeline.py`, `observability_spend.py`, `observability_filters.py`, `call_accounting.py`, `accounting_projection.py`, `cost_assessment.py`, `usage_receipts.py`, `context_capture.py` (+queries), `data_lifecycle.py`, `backups.py`, `migration.py`, `tool_status.py` |

## 3. Execution semantics

**Loop invariant** — reason → act → observe → repeat, one reasoning step at a time. Same-turn tool calls may run concurrently; separate steps never do. Parallel schedule occurrences spawn separate sessions.

**Durable runs** — status persists on every transition: `running`, `awaiting_approval`, `completed`, `failed`, `stopped`, `interrupted`. Startup reconciles orphaned `running` → `interrupted`. `get_run_status` falls back to DB after the in-memory `RunContext` window (~60s).

**Run triggers** — `chat`, `heartbeat`, `schedule`, `channel`, `reflection`, `test`.

**Session idle close** — eligibility = `last_activity_at + limits.session_idle_timeout_min` (per-agent live read; in-flight run ⇒ never idle). Sweeper sleeps until the nearest deadline (300s fallback cap); session/run/config events poke its wake event. Run start lazily closes *other* idle sessions as background tasks.

**close_session** (`memory/episodic.py`) — full-transcript `ConversationSummary` + session-scoped durable-fact extraction over terminal non-test runs, then conditional `closed` write. Provider/parse/core-conflict failure leaves the session open with originals + scratch retained. Dashboard resume reopens like a channel resume.

**Reflection (RSI)** — post-close: `snapshot_agent_local_drift` pins untracked live-dir skill edits; `reflect_session` may run one bounded pass (real `Run` row, `trigger="reflection"`) with inspect/edit authority over frozen evidence + staged agent-local edits only. Dedupes by evidence fingerprint; skipped-while-busy stays unclaimed and retries within a 7-day lookback. Never reopens the session, never rolls back learning, invisible to chat history and activation counts.

## 4. Data model (`models/`)

Tables, grouped:

- **Identity/config:** `Agent`/`AgentVersion` (config snapshot rows), `Provider` (Fernet key), `ModelCatalogOffering`/`ModelCatalogRevision` (models.dev snapshot + refresh state)
- **Execution:** `Session` (status, last_activity_at, pins), `Run` (status, trigger, cost/tokens), `ExecutionManifest` (pinned skill revisions, schedule/plan refs), `TerminalSession` records, `SubAgent` records. `ScheduleOccurrence` and the manifest correlate a run back to its schedule
- **Mediation:** `AuditRecord` (every syscall: allow/deny, redacted args, latency, `call_id`/`sub_agent_id` correlation), `ApprovalRequest` (decisions + remembered scopes), `ElicitationRequest`
- **Observability:** `ModelCall` (unified ledger: chat/embedding/probe/extract/title; thinking reported-only), `ModelRequestCapture` (redacted bodies, retention-governed)
- **Memory:** `MemoryTriple`, `ConversationSummary` (immutable), `CoreRevision` (MEMORY.md evidence/pins)
- **Skills:** `Skill`, `SkillRevision`, `SkillAssignment`, `SkillActivation` (activations), `SkillReflection` (pass records + fingerprints)
- **Knowledge:** `Document`, `DocumentChunk`, `EmbeddingResource`, `RetrievalProfile`, `IndexGeneration` (one `active`), `ChunkEmbedding`
- **Artifacts:** `Artifact`, `ArtifactRevision`
- **Scheduling:** `Schedule`, `ScheduleRevision`, `ScheduleOccurrence` (`retry_of` chains, `next_fire_at` truth)
- **Comms/ops:** `ChannelConfig`, `Notification` (dedupe key type+entity+unread), `Operator`/`OperatorSession`, `BrowserProfile`, `WebSource` (references), `Contact`

## 5. API surface

Routers under `/api` (route counts in `api/*.py`):

`auth` · `providers` (CRUD, model discovery, 1-token validation) · `agents` · `agent_files` (MEMORY.md, workspace, memory mgmt, previews) · `chat` (message, SSE events, run control) · `approvals` · `elicitation` · `knowledge` (documents, sources, index generations, embed spend) · `skills` (scoped views, effective, validate, publish/promote, drafts, import) · `scheduler` (heartbeat facade — legacy shape) · `schedules` (CRUD, pause/resume, run-now, occurrences) · `mcp` (servers, credentials, OAuth, catalog, bindings) · `notifications` · `channels` (CRUD, webhooks, test) · `observability` (runs, timeline, audit, spend, health) · `settings` · `data` (lifecycle/backup) · `browser` (profiles/settings) · `dependencies` (optional tools/runtimes)

Notable reads: `GET /api/home` → aggregated Today payload (agents + live-run state, needs-you items, recent activity); `GET /api/runs/{id}` → projected `timeline`; `GET /api/spend?scope=platform` → ledger totals (`priced_calls`/`unpriced_calls`/`thinking_reported_calls`); `GET /api/model-calls/{id}/context` → re-projected capture.

Runtime endpoints: `GET /api/dependencies` + `POST /api/dependencies/recheck` probe Node.js, uv, Git, and Chromium — Ollama is a convenience link, not a probe. Sandbox health is a separate surface under `GET /api/health`; the managed browser runtime has its own settings API under `api/browser`.

Auth (`/api/auth`): `login`, `logout`, `me`, `change-password`, `setup-credentials`. Session cookie or bearer. Webhook endpoints verify per-channel signatures (HMAC / secret-token headers).

**First-run lifecycle:** after login, `setup-credentials` lets the operator store credentials inline or skip; onboarding's credential step drops once setup completes, and its runtime checks report real Node.js/uv/Git/Chromium/sandbox status. Afterwards, Settings → General → Sign-in manages credentials, and the Product tour/hints surfaces live under their own General settings.

Thinking note: token usage is not reasoning text — the adapter reports `reasoning_content`/delta reasoning for chat only when the provider actually returns content; a Responses `summary:auto` flag is used only when enabled. There is no fabricated historic thinking; captures allowlist omits `extra_body`, so an omitted count does not prove the exact effective request.

## 6. Syscall boundary (`syscall/`)

Every capability call → `SyscallHandler` (`mediator.py`): resolve caller → permission check (grant model + remembered approvals: exact → same-verb → pattern → capability) → approval gate (`ApprovalRequest` row + `asyncio.Event`) → credential injection → execute (sandbox/workspace scoped) → audit record. Elicitation pauses via the same event-registry pattern. Per-session `asyncio` lock serializes reasoning steps; concurrent same-step tool calls are permitted.

`capabilities/effects.py` declares per-tool effects (egress, filesystem, approval-required); `catalog.py` + `capabilities_search`/`capabilities_load` implement progressive schema disclosure — loaded ≠ permitted.

## 7. Context assembly (`harness/`)

Per model turn: platform instructions → bounded session-pinned `MEMORY.md` → assigned skill metadata/active procedures → coherent uncovered conversation + active `ConversationSummary` → currently loaded schemas. Budgeting precedes each turn; mid-run overflow force-compacts once then fails honestly. `memory/core.py` publishes MEMORY.md with exact-bytes identity validation, `core_max_tokens` ceiling (32k default), optimistic hash, revision + session pin.

## 8. Knowledge Vault pipeline

`ingest` → `extractors` (structured blocks per format) → `chunker` (parent/child per block type) → `indexing` (blue-green generations; `reconcile_stale_builds` at startup) → `retrieval` (FTS5 always; hybrid adds embeddings + RRF + bounded parent expansion) → citations + retrieval trace. Embedding egress: remote providers require audited opt-in; locality test = local provider type or loopback/`*.local` base_url. Ledger records every embed call (operation, tokens, cost, latency). **Tabular sources refused** pending row-record layer.

## 9. Scheduler engine

Tick: drain due queued occurrences → fire due schedules → commit → spawn run tasks (never inside the tick transaction). `next_fire_at` persisted; recovery = DB read + missed-run sweep (`skip`/`run_once`/`catch_up≤25`). IANA tz stored separately; DST: nonexistent → first valid instant, ambiguous → once. Occurrence pins `schedule_revision_id`; edits write hash-gated revisions. Heartbeat = managed schedule row; facade endpoints preserved; managed rows reject edit/delete (400).

## 10. Browser subsystem

Chrome-for-Testing runtime — managed install gated on explicit consent. CDP session per agent run; headless default, visible mode for takeover. Domain leash bounds navigation; persistent profiles opt-in and domain-scoped (`BrowserProfile` rows). `browser_open` persists the landed URL (redirects resolved); `browser_act` persists URL transitions (clicks, submits, SPA navigations); blocked navigations persist nothing.

## 11. References vs evidence

`WebSource` rows = URLs the agent **visited** (web_fetch / browser_open landed / browser_act transitions). `web_search` results are trace-only — inspectable in the tool-call record, never citable references. Base prompt instructs: open a page before citing it.

## 12. Sandbox matrix

| Platform | Backend | Notes |
|---|---|---|
| macOS | `seatbelt` (sandbox-exec) | Tier 1 |
| Linux | `bwrap` | needs `SYS_ADMIN` in containers |
| Windows | MXC (bundled `wxc-exec.exe`) | one-time consent setup |
| Any (fallback) | Docker container | docker.py |
| Docker deploy | bwrap if cap else Docker-isolation | compose sets `cap_add` |

`workspace.py::resolve_within` = canonical containment check (realpath + prefix). All file ops route through it.

## 13. Frontend map (`frontend/src/`)

Pages: `Today` (`/` — needs-you approvals/elicitations, recent activity, ask-an-agent), `AgentList` (`/agents`), `Conversation`, `Skills`, `KnowledgeVault`, `Scheduler`, `Mcps`, `Channels`, `Observability`, `Traces`, `Notifications`, `ProvidersSettings`, `Login`.

Key libs: `api.ts` (single fetch layer), `notificationStore.ts` (+`notificationPrefs`, `notifAdapters`, `notificationLinks`), `sessionActivity.ts`, `focusRegistry.ts`, `crossTab.ts`, `theme.tsx`, `confirm*`, `attachmentUtils.ts`, `traceFormat.ts`, `desktopFileDrop.ts`, `openUrl.ts`, `sidebarState.ts`.

Components: `DashboardSidebar`, `ChatSidebar`, `ChatInputBar`, `PageHeader`, `NotificationCenter`/`Toasts`, `RunTimeline`, `TraceInspector`/`TraceWaterfall`, `PreviewPanel` + `previews/` renderers, `SettingsOverlay`, `CreateAgentModal`, `ModelPicker`/`ModelSelect`/`ModelCatalog`, `guidance/` (`GuidanceHost`, `PageIntro`, `TourSpotlight`, `tourStops`) + `onboarding/` (first-run shell + steps), `OptionalToolsAndRuntimes`, `RuntimeInstallDialog`, `UpdateChecker`, `ToolCallBlock`, `ThinkingBlock`, `Markdown`, `DiffBlock`, `ui/` primitives.

No global navigation transition layer — onboarding and tour transitions respect reduced-motion preferences.

## 14. Build, packaging, release

- Dev: `./scripts/dev.sh` (backend :8081 + Vite :5173 proxying `/api`). The backend runs with `AGENTOS_RELOAD=false` — restart it after Python edits; file mtimes are not proof a server is stale.
- Desktop: PyInstaller gateway (`scripts/build-gateway.*`) bundled into Tauri; gateway supervisor `frontend/src-tauri/src/gateway.rs` on `127.0.0.1:51718`
- Docker: `docker-compose.yml` — nginx frontend → `:8080`, named volume `caberos-data`
- Release: `scripts/release.sh X.Y.Z` two-phase (release PR → tag `v*.*.*` → `release.yml` builds dmg/NSIS + deploys website)
- Tests: `uv run pytest -q` · `npm run test`/`lint`/`build` · ruff check + format gate
