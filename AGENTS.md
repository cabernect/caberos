# CaberOS — Agent Context

## What is this project?

CaberOS is an open-source, local-first AI Agent Operating System. It hosts personal agents on the operator's machine, gives them a workspace, connects them to services (chat, external channels, MCP servers, the web, a managed browser), and mediates every capability call through a single syscall boundary that checks permissions, requests approvals, and writes audit records.

**Language:** Python 3.12 (backend), React 19 + TypeScript + Vite (frontend)
**Package manager:** uv (backend), npm (frontend)
**Repo structure:** Monorepo — `/backend`, `/frontend`, `/website`, `/docs`, `/skills`, `/sandbox`, `/scripts`, `/design-system`
**Desktop shell:** Tauri 2 (Rust) — `frontend/src-tauri/`
**Container:** Docker + docker-compose — `backend/Dockerfile`, `frontend/Dockerfile`, `docker-compose.yml`
**Current line:** v0.2.0 "Agent Workbench" on `feat/v0.2.0` (integrated, release pending); latest tag `v0.1.9`.

## Where things are

- `docs/spec-v0.1.md` — the v0.1 specification, 40 decisions (D1–D40).
- `docs/plans/` — v0.1 plans (00–15); `docs/plans/v0.2/` — v0.2 workstream specs (00–15) with `test_plan/` and `test_result/` records.
- `docs/plans/v0.2-release-plan.md` — release boundary, invariants, and deferred items.
- `docs/TECHNICAL.md` — deep technical reference (module map, data model, API surface, subsystem internals).
- `docs/PRODUCT.md` — product/business framing (vision, personas, positioning, roadmap narrative).
- `CONTEXT.md` — shared vocabulary (Model Offering, Reported vs Estimated Cost, etc.). Use this language; don't drift from it.
- `design-system/caberos/` — implemented theme (warm light, olive accent) + page specs.
- `AGENTS.md` (this file) — operating manual: conventions, gates, gotchas.

## Key decisions (quick reference)

- **D1 / D25:** Agents are versioned DB configuration (`AgentConfig` + `AgentVersion`), not code. YAML is import/export only.
- **D2:** Custom async harness; LiteLLM is model transport only — never a metadata/pricing authority.
- **D3:** Python 3.12 + FastAPI, one daemon.
- **D5:** SQLAlchemy 2.0 async. SQLite + aiosqlite (WAL, FTS5) default; Postgres via asyncpg supported. Schema via `create_all` + incremental `init_db()` patches (Alembic deferred).
- **D33:** FastAPI is the gateway. React dashboard, Tauri shell, and external channels are all clients of the same REST + SSE contracts.
- **D34:** Three-layer memory — session working memory, `MEMORY.md` in the agent home (`~/agentos/agents/{agent_id}/`), knowledge-graph triples. FTS5 default, embeddings opt-in.
- **D35:** Agent identity = `soul`, `persona`, `task` — authoritative versioned config fields in the DB. `MEMORY.md` renders identity; it never carries it.
- **D37:** Workspaces are shared working-file directories. Identity and MEMORY.md live outside them.
- **D9/D13 (revised):** Four capability kinds: `tool`, `sub_agent`, `memory`, `mcp_tool`. MCP replaced native connectors. CaberOS owns credential custody; MCP servers get credentials via env/headers at runtime.
- **D39:** Providers are first-class DB entities with Fernet-encrypted keys. Agents reference providers by id.
- **D40:** Model discovery: dynamic where available, free-text fallback, always allow override. Catalog/pricing authority is the bundled `models.dev` snapshot with daily validated refresh.

## Non-negotiable invariants

1. **Execution loop:** a conversation advances strictly reason → act → observe → repeat, one reasoning step at a time. Multiple tool calls in one model turn may run concurrently within that step; separate reasoning steps never run concurrently in the same conversation. (Parallel *schedule* runs get separate sessions — the invariant holds.)
2. **Syscall mediation:** every capability call crosses `syscall/mediator.py` — permission check, approval gate, credential injection, execution, audit record. No capability bypasses it.
3. **Honest data:** never present reconstructed/historical data as live captures; never infer price from a model alias; a legacy zero without pricing provenance is *unknown*, not free; unknown timestamps stay unpositioned on trace timelines; empty states say so.
4. **Memory never expands permissions.** The agent-global core is for the personal owner's use.
5. **References = visited URLs.** `web_search` hits are trace evidence only; a `WebSource` row means the agent actually fetched/opened that URL.
6. **No silent authority expansion:** no automatic optional downloads, privilege escalation, or egress — installs and remote embeddings require explicit operator consent.

## How to implement

1. Read the relevant spec (`docs/plans/v0.2/NN-*.md`) and any ticket/issue context.
2. Implement end-to-end (vertical slice: DB + API + harness + frontend where applicable).
3. Verify against acceptance criteria; keep tests green.
4. Commit per coherent unit. **No Co-Authored-By lines. Always ask before committing or pushing.**
5. Before every push, run the CI equivalent: `cd backend && uv run ruff check src/ tests/ && uv run ruff format --check src/ tests/ && uv run pytest -q` and for frontend changes `cd frontend && npm run lint && npm run build`. Format violations fail CI like test failures (`uv run ruff format src/ tests/` fixes).
6. Update this file (or TECHNICAL.md / CONTEXT.md) when you learn something a fresh session needs.

## Testing the frontend

Use the **Playwright MCP server** (`mcp-playwright`) for real-browser verification: start backend on :8081 and frontend on :5173, then navigate/click/verify via `browser_navigate`, `browser_snapshot`, `browser_console_messages`, etc. List tools with `mcp_list_tools` first. Browser verification is a required completion gate for UI work.

**Dev DB note:** real development uses `backend/data/agentos.db`. Isolate QA servers on separate ports; never replace the normal backend with a temporary database.

## Runs, sessions, and lifecycle

- **Durable runs:** every run is a DB row; status transitions persist (`running` → `awaiting_approval` → `completed`/`failed`/`stopped`). On startup, orphaned `running` rows reconcile to `interrupted`. `get_run_status` falls back to the DB after the in-memory window expires.
- **Session idle close:** a session becomes eligible for close once idle past the agent's live `limits.session_idle_timeout_min`. A session with an in-flight run is never idle — long work can't be swept out from under itself. The sweeper (`main.py`) is deadline-driven: it sleeps until the nearest `last_activity_at + timeout` (300s fallback cap), and run/session events poke its wake event. Run starts lazily close *other* idle sessions as background tasks.
- **Session close = learning:** `close_session` (`memory/episodic.py`) writes a full-transcript summary + durable-fact extraction, then a conditional `closed` commit. Provider/parse/core-conflict failures leave the session open. Explicit resume reopens it.
- **RSI / reflection:** after close commit, `snapshot_agent_local_drift` pins untracked live-dir skill edits, then `reflection.py` may run one bounded skill-reflection pass — a real `Run` row (`trigger="reflection"`) with inspect/edit authority over frozen session evidence and staged agent-local skill edits only. Failures never reopen the session or roll back learning; reflection runs stay out of chat history and activation counts. Skipped reflections (agent busy) leave the evidence fingerprint unclaimed and are retried on later sweeps (7-day lookback, capped).
- **In-flight visibility:** closes broadcast `session_activity` SSE frames and set `learning` on the sessions list so the chat view shows internal work.

## System prompt + context assembly

Each run assembles: platform instructions (`harness/base_prompt.py`), the bounded session-pinned `MEMORY.md`, assigned skill metadata/active procedures, coherent uncovered conversation + its saved summary, and currently loaded permitted schemas. Identity appears once, inside the core. Conversation reads use `harness/conversation.py`; complete-input budgeting precedes each model turn; mid-run context overflow force-compacts once and retries, then fails honestly.

`memory/core.py` owns `MEMORY.md` publication: exact bytes, identity validation, ceiling (`core_max_tokens`, default 32768), optimistic hash checks, revisions, session pins. `ConversationSummary` rows are immutable snapshots; a losing CAS write never leaves a row.

Chat-model dispatch attempts carry a capture reference; bodies are best-effort, redacted, retained per the installation retention policy. The trace inspector re-projects stored bodies on read via `/api/model-calls/{id}/context`.

Defaults: `max_turns_per_run` 200, `session_idle_timeout_min` 5, `max_cost_per_run` 500. `limits.max_context_tokens` defaults unset (model's real window is the ceiling); it remains an accepted explicit override — do not remove the field.

## Built-in capabilities

Registered in `capabilities/builtin.py` (+ `run_subagent`/`read_subagent` in `tools/subagent.py`). Kinds: `tool`, `memory`. Egress/approval flags are the mediation contract.

| Capability | Egress | Approval | Description |
|---|---|---|---|
| `read_file` | no | no | Read workspace file (text/docs/images w/ vision cap; 50k cap) |
| `write_file` | no | no | Write workspace file (returns diff) |
| `search_files` | no | no | `mode`: content (grep) / name (glob) / list |
| `terminal` | yes | yes | Shell command in sandbox (persistent background session) |
| `read_terminal` / `close_terminal` | no | no | Read/close a terminal session |
| `doc_list` / `doc_search` / `doc_inspect` | no | no | Knowledge Vault: list docs, retrieve (FTS5/hybrid), inspect |
| `web_search` | yes | yes | DuckDuckGo search — results are trace evidence, NOT references |
| `web_fetch` | yes | yes | URL → markdown (trafilatura), paginated, 50k ceiling; persists a reference |
| `browser_open` | yes | yes | Open URL in managed browser; persists landed URL (incl. redirects) |
| `browser_observe` | no | no | Snapshot current page for the agent |
| `browser_act` | yes | yes | Click/type/navigate; URL transitions persist references |
| `browser_extract` | no | no | Extract structured content from the page |
| `browser_close` | no | no | Close the browser session |
| `agent_ask_user` | no | no | HITL clarifying question (elicitation) |
| `datetime_now` | no | no | Current date/time (optional timezone) |
| `run_subagent` / `read_subagent` | no | no | Spawn/poll a sub-agent (own task + capability subset) |
| `memory_recall` / `memory_store` | no | no | Session-scoped recall/store (FTS5 or tsvector) |
| `memory_remember_fact` / `memory_query_facts` | no | no | KG triples (entity, predicate, object) |
| `memory_update` | no | no | Update MEMORY.md (agent-scoped) |
| `search_history` | no | no | Search other sessions' summaries/messages |
| `skills_list` / `skills_load` / `skills_read_resource` / `skills_usage` | no | no | Skill menu → load → resources → activation counts |
| `capabilities_search` / `capabilities_load` | no | no | Progressive schema discovery: search metadata, load schemas next turn (never widens authority) |
| `artifact_create` | no | no | Tracked deliverable (docx/xlsx/pptx/pdf) from structured spec → `artifacts/` |
| `artifact_inspect` | no | no | Reopen + validate; report structure + tracking honestly |
| `artifact_revise` | no | no | Structured ops vs base revision; conflicts on external edits |
| `artifact_adopt` / `artifact_history` / `artifact_restore` | no | no | Track existing file; list revisions; restore-as-new-revision |

## Subsystem notes

### Skills (governed library)
DB is the resolution authority: `Skill`/`SkillRevision`/`SkillAssignment`. `resolve_effective_skills()` precedence: agent-local > global > built-in (global respects availability/assignments; disabled/archived agent-local rows suppress the live dir). Runs pin `skill_revision_ids` (`rev:<id>` or `live:<sha256>`) in the manifest — mid-run publishes can't wobble a run. Built-ins seed from `skills/builtins.py` (`BUILTIN_SKILLS`: browser-workflows, doc-coauthoring, evolve, frontend-design, office-documents, skill-creator); removed names are retired at startup. "Create Skill" opens a builder-mode session (`skill-creator` force-loaded, drafts land in `skill-drafts/`, no publish capability by construction). Imports (ZIP/repo URL) go through `skills/importer.py` hardening and land as drafts. Drafts are for *new* skills only: updates to an existing agent-local skill edit the live `skills/<name>/` dir and are pinned as revisions by `snapshot_agent_local_drift` at session close — a same-name `skill-drafts/` dir can never index or publish (unique name per scope+owner) and reconcile logs it as an orphan.

### Knowledge Vault (RAG)
Structured extraction → per-block-type parent/child chunking → FTS5 lexical (default) + optional hybrid embeddings → RRF fusion → bounded parent expansion → citations + retrieval trace. Index generations are blue-green (exactly one `active`; concurrent rebuild → 409; stale `building` reconciled to `failed` at startup). Remote embedding providers require explicit egress consent (audited); `fusion=lexical` makes zero provider calls. Every embed call lands in the `model_calls` ledger. **Tabular uploads (.xlsx/.csv) are refused at ingest** pending the deferred row-query layer — a clear refusal beats a misleading index.

### Observability
`model_calls` is the unified ledger (chat/embedding/probe/extract/title; thinking tokens are reported-only). Correlation via `call_id`/`sub_agent_id` on audits/approvals/elicitations/artifacts — exact joins, never temporal. `GET /api/runs/{id}` returns a projected `timeline` (audit roots → tombstone tool_call → pending approval); `/api/spend?scope=platform` reads the ledger while agent scope keeps historic run totals — they are intentionally not algebraically equal. `redaction.py` is the shared read boundary; sensitive payloads fail closed. Traces page: span tree + waterfall + observation inspector.

### Notifications
`create_notification()` dedupes by type + entity + unread state. Deep links carry `action_path`; toasts + inbox; SSE-first delivery. The conversation view retro-marks focused-entity notifications read when the window regains focus (`markReadForFocusedEntities` in `notificationStore.ts`).

### Scheduler
`Schedule`/`ScheduleRevision`/`ScheduleOccurrence` — persisted `next_fire_at` is truth; restart recovery is a DB read + missed-run sweep (`skip`/`run_once`/`catch_up`, capped 25). Triggers: once/interval/cron (croniter) with IANA timezone; DST handled (nonexistent → first valid instant, ambiguous → once). Overlap: skip/queue/cancel_previous/allow_parallel. Failure: `no_retry`/`bounded_retry` (retries = new occurrences via `retry_of`). Heartbeat is a facade over a managed schedule row — old `/api/scheduler/heartbeat*` endpoints unchanged; managed rows reject edit/delete.

### Browser automation
Managed Chrome-for-Testing (explicit first-use install consent), CDP sessions, headless/visible modes, domain-scoped opt-in persistent profiles, domain leash, approval-gated actions, takeover requests, download staging. `web_fetch` stays the non-interactive path.

### Artifacts & previews
`Artifact`/`ArtifactRevision`: stable identity, immutable revisions, restore-as-new, conflict detection on external edits, run/message provenance. Structured spec → bytes, never raw Office XML. `previews.py` classifies bytes → bounded renderers; workspace + skill preview endpoints accept path or `{artifact_id, revision_id}`.

### Channels & MCP
Channels (Telegram/Discord/Zalo OA/Zalo Bot) route through the same pipeline and audit. MCP: stdio/HTTP client, registry, encrypted credentials, OAuth loopback + refresh, stdio PATH resolution (`CABEROS_MCP_RUNTIME_PATH`), per-tool `tool_filter` + deny overrides.

### Runtime readiness / dependencies
Optional tools/runtimes live in global Settings → General. Direction: app-managed/private installs by default, fixed subprocess recipes, guided system install when unmanaged — all gated on explicit consent. No automatic downloads.

## Attachments & workspace layout

`attachments/` = user inputs; `artifacts/` = agent deliverables (`artifact_create` prefixes paths, refuses `attachments/`); workspace root + other dirs = scratch. Attachment metadata (type, MIME, filename, URL) lives on `messages.attachments` — never bytes. Images >15 MB refused; downscaled ≤1568px; vision-gated. Documents: PDF paged extraction, Office → flattened text via `to_elements`, unknown binaries refused. 50k char caps on reads and tool results in history.

## Storage summary

| What | Where | Versioned? |
|---|---|---|
| Agent identity + config | DB (`AgentConfig`) | yes (`AgentVersion`) |
| MEMORY.md | `~/agentos/agents/{id}/MEMORY.md` | living file; `CoreRevision` evidence/pins |
| Knowledge graph | DB `memory_triples` | no |
| Session summaries | DB `ConversationSummary` | immutable snapshots |
| Provider/connector secrets | DB, Fernet-encrypted | n/a |
| Workspace files | shared dirs | n/a |
| Governed skills | bytes `skills/` + `data/skills-store/{id}/rev-{n}/`; index in DB | yes (`SkillRevision`) |
| Agent-local skills | `workspace/skills/{agent_id}/` | optional published snapshots |
| Skill drafts | `workspace/{agent}/skill-drafts/`, `data/skills-drafts/` | no |
| Schedules | DB `Schedule`/`ScheduleRevision`/`ScheduleOccurrence` | yes |
| Artifacts | `artifacts/` workspace files + DB revisions | yes (`ArtifactRevision`) |
| Runs/audit/ledger | DB `Run`, audit log, `model_calls` | append-only |
| Browser profiles | `data/browser-profiles/` (opt-in persistent) | n/a |
| Knowledge index | DB `knowledge_index` generations + chunks | generations |

## Build & test commands

```bash
# Backend (from backend/): tests + lint + format gate
uv run pytest -q
uv run ruff check src/ tests/ && uv run ruff format --check src/ tests/

# Smoke test (full pipeline, ScriptedModel — no real LLM)
cd backend && uv run python ../scripts/smoke.py test-agent "echo hello"

# Seed DB
cd backend && uv run python -m agentos.seed

# Dev servers (backend :8081, frontend :5173 w/ /api proxy)
./scripts/dev.sh            # both
cd frontend && npm run dev  # frontend only

# Frontend gates
cd frontend && npm run lint && npm run build && npm run test

# Desktop (Tauri)
cd frontend && npm run desktop:dev    # dev mode
cd frontend && npm run desktop:build  # packaged app

# Docker full stack → http://localhost:8080
./scripts/docker.sh up|down|logs|rebuild
```

Current test baseline: ~1,300 backend tests (88 files), 27 frontend test files.

## Gotchas

- **Release:** `./scripts/release.sh X.Y.Z` from a clean tree — two-phase (release branch PR → merge → re-run to tag). Version is a literal in all manifests; never hand-edit or tag a stale commit.
- **CodeQL path-injection:** `Path.resolve()`+`is_relative_to` is not a sanitizer — use `os.path.realpath()`+`startswith()` via `sandbox/workspace.py`'s `resolve_within()`, and check containment before reading.
- **CodeQL URL-substring:** never `in`/`find` a URL string — use `urlparse(u).hostname == "host"`.
- **Datetimes:** SQLite drops tzinfo; `models/base.py` stamps UTC on load. Keep tz-aware; never compare with naive `datetime.now()`.
- **Gateway supervisor (desktop):** PyInstaller gateway on `127.0.0.1:51718`, own process group, logs at `~/Library/Application Support/com.caberos.desktop/logs/gateway.log`. Desktop auth = bearer token (not cookies).
- **Auth:** `auth.py` accepts session cookie OR `Authorization: Bearer` (desktop).
- **Env vars:** `AGENTOS_` prefix — see `config.py`; key ones: `AGENTOS_DATABASE_URL` (Postgres opt-in), `AGENTOS_DB_PATH`, `AGENTOS_YOLO_MODE` (skip all approvals), `AGENTOS_HITL_TIMEOUT`, `AGENTOS_SANDBOX_TIMEOUT`, `AGENTOS_MODEL_REQUEST_TIMEOUT`, `AGENTOS_MODEL_STREAM_IDLE_TIMEOUT`.
