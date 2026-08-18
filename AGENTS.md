# CaberOS — Agent Context

## What is this project?

CaberOS is an open-source, local-first AI Agent Operating System. It hosts personal agents on your machine, gives them a workspace, connects them to your services (email, calendar), and lets them run shell commands in a sandbox. The OS supplies the harness, mediates every capability call, and gives you a dashboard to manage your agent(s).

**Language:** Python 3.12 (backend), React 19 + Vite (frontend)
**Package manager:** uv (backend), npm (frontend)
**Repo structure:** Monorepo — `/backend`, `/frontend`, `/docs`, `/sandbox`, `/scripts`
**Desktop shell:** Tauri 2 (Rust) — `frontend/src-tauri/`
**Container:** Docker + docker-compose — `backend/Dockerfile`, `frontend/Dockerfile`, `docker-compose.yml`

## Where things are

- `docs/spec-v0.1.md` — the full specification. 40 decisions (D1-D40). Read this first.
- `docs/plans/` — 15 implementation plans (00-14) with detailed specs, file lists, verification steps. These are the implementation reference.
- `docs/plans/README.md` — plan index and build order.
- `.scratch/caberos-v0.1/issues/` — tracer-bullet tickets (01-11, with 08 split into 08a/08b) with blocking edges. These drive the work order. (gitignored — use GitHub Issues for public tracking)
- `design-system/caberos/` — design system documentation. MASTER.md describes the actual implemented theme (warm light, olive accent). Page specs for agent-list and conversation.

## Key decisions (quick reference)

- **D1:** Agents are configuration, not code. AgentConfig is a DB row, versioned.
- **D2:** Custom async harness. LiteLLM is the model transport.
- **D3:** Python 3.12 + FastAPI, one daemon.
- **D5:** SQLAlchemy 2.0 async + aiosqlite. SQLite with WAL mode. Schema via `create_all` + incremental patches in `init_db()` (Alembic deferred to Postgres migration).
- **D25:** Agent config lives in the DB as versioned rows (AgentVersion). YAML for import/export only.
- **D33:** FastAPI is the current gateway/API layer. The React dashboard is one client, with Tauri and CLI as future clients using the same REST + SSE contracts. A deeper CaberCore seam is deferred until a non-HTTP entry point requires it.
- **D34:** Three-layer memory: working memory (session), MEMORY.md (file in agent home dir `~/agentos/agents/{agent_id}/`), knowledge graph (SQLite triples). FTS5 default, embeddings configurable.
- **D35:** Agent identity = `soul`, `persona`, `task` — versioned config fields on AgentConfig (in the DB). NOT workspace files. MEMORY.md is the exception (agent-managed file, not versioned).
- **D37:** Workspaces are shared directories for working files only. Identity is in the DB, MEMORY.md is in the agent home dir — neither in the workspace.
- **D38:** MCP tools are in v0.1 (revised — was v0.2). CLI/TUI (`caber`) still deferred to v0.2. v0.1 ships React dashboard + MCP integration. `scripts/smoke.py` is a dev tool, not a product CLI.
- **D9/D13 (revised):** Four capability kinds: `tool`, `sub_agent`, `memory`, `mcp_tool`. Native `connector_action` kind removed — MCP replaces it. CaberOS owns credential custody at rest; MCP servers receive credentials via env/headers at runtime.
- **D39:** Providers are first-class DB entities with encrypted keys (Fernet). Agents reference providers by id. LiteLLM is the transport.
- **D40:** Model discovery: dynamic where available (OpenAI, Google, Ollama), free-text fallback (Anthropic), always allow override. Save-time validation via 1-token completion.

## Ticket order

```
01 → 02 → 03 → 04 → 08a → 08b
       ├→ 05, 05a, 06 → 07
       └→ 09 → 10 → 11
```

01 smoke; 02 chat; 03 file/tools; 04 approvals; 05 agent UI; 05a providers;
06 memory/skills; 07 heartbeat; 08a/08b MCP; 09 observability; 10 desktop; 11 hardening.

## Testing the frontend

Use the **Playwright MCP server** (`mcp-playwright`) to test the frontend in a real browser. Available tools include: `browser_navigate`, `browser_click`, `browser_type`, `browser_snapshot`, `browser_console_messages`, `browser_evaluate`, etc. List tools with `mcp_list_tools` before calling.

To test: start both servers (backend on :8081, frontend on :5173), then use Playwright to navigate, click, type, and verify the UI.

## How to implement

1. **Read the ticket** (`.scratch/caberos-v0.1/issues/NN-*.md`) for what to build and acceptance criteria.
2. **Consult the relevant plans** (`docs/plans/NN-*.md`) for detailed specs — Pydantic models, file lists, schemas, verification steps.
3. **Implement end-to-end** (vertical slice: DB + API + harness + sandbox + frontend).
4. **Verify** against the ticket's acceptance criteria.
5. **Commit** per ticket. No Co-Authored-By lines.
6. **Update this file** if you learn something that a fresh session needs to know.

## System prompt + memory flow

Each run assembles: base prompt → soul/persona/task → `MEMORY.md` → skill menu
→ contact-scoped KG facts → relevant past-session summaries → semantic recall.
`MEMORY.md` is agent-scoped, always loaded, and protected from conversation compaction.
KG facts, summaries, and recall snippets are queried per contact and bounded.
During/after a run, memory tools write working snippets, triples, or `MEMORY.md`;
`memory/auto_extract.py` promotes durable facts and clears run-scoped snippets.
The base prompt (`harness/base_prompt.py`) contains platform rules shared by agents.

## Built-in capabilities

Registered in `capabilities/builtin.py`. Two kinds: `tool` (workspace/shell/web ops) and `memory` (subject-scoped memory ops). `run_subagent` is a tool registered separately in `capabilities/tools/subagent.py`.

| Capability | Kind | Egress | Approval | Description |
|---|---|---|---|---|
| `read_file` | tool | no | no | Read a file from the workspace |
| `write_file` | tool | no | no | Write a file to the workspace (returns a diff) |
| `search_files` | tool | no | no | Unified search — `mode`: `content` (grep), `name` (glob), `list` (dir listing) |
| `terminal` | tool | yes | yes | Run a shell command in the sandbox (persistent session) |
| `read_terminal` | tool | no | no | Read output from a running/finished terminal session |
| `close_terminal` | tool | no | no | Close a terminal session |
| `web_search` | tool | yes | yes | Search the web via DuckDuckGo (free, no API key) |
| `web_fetch` | tool | yes | yes | Fetch a URL and return text content (HTML → text) |
| `agent_ask_user` | tool | no | no | Ask the user a clarifying question (HITL elicitation) |
| `datetime_now` | tool | no | no | Get current date/time (with optional timezone) |
| `run_subagent` | tool | no | no | Spawn a sub-agent with its own task + capability subset |
| `read_subagent` | tool | no | no | Poll a running sub-agent's status/output |
| `memory_recall` | memory | no | no | Recall past conversation snippets (FTS5/Postgres FTS) |
| `memory_store` | memory | no | no | Store a snippet for later recall (subject-scoped) |
| `memory_remember_fact` | memory | no | no | Store a KG triple (entity, predicate, object) |
| `memory_query_facts` | memory | no | no | Query KG triples by entity/predicate/object |
| `memory_update` | memory | no | no | Update MEMORY.md (agent-scoped, not contact-scoped) |
| `skills_list` | tool | no | no | List available skills (name + description only — menu) |
| `skills_load` | tool | no | no | Load a skill's full content + resource listing |
| `skills_read_resource` | tool | no | no | Read a resource file from a skill directory (scoped to skill dir) |

## Attachments

Users can attach images, URLs, and files to their chat messages. Attachments are
stored in the agent workspace and the initial model message contains only
metadata and workspace-relative references.

- **Local files**: use the existing `read_file`, `search_files`, `terminal`, or
  file-processing skills.
- **Web URLs**: use the existing `web_fetch` capability; URLs are never sent as
  image inputs automatically.
- **Images**: `read_file` returns image content only when the selected model
  supports vision. Otherwise it returns a clear limitation.

The `messages.attachments` column stores metadata (type, MIME type, filename,
and URL when applicable), never base64 content. Uploaded bytes are stored under
the workspace `attachments/` directory.

## Storage summary

| What | Where | Versioned? |
|---|---|---|
| Agent identity (soul, persona, task) | DB — AgentConfig fields | yes (AgentVersion) |
| Agent config (model, capabilities, limits, etc.) | DB — AgentConfig fields | yes (AgentVersion) |
| MEMORY.md | File — `~/agentos/agents/{agent_id}/MEMORY.md` | no (living document) |
| Knowledge graph | DB — memory_triples table | no |
| Provider keys | DB — encrypted (Fernet) | n/a |
| Connector tokens | DB — encrypted (Fernet) | n/a |
| Workspace (working files) | Filesystem — shared directory | n/a |
| Skills | Filesystem — `skills/` (system) + `workspace/skills/{agent_id}/` (per-agent) | n/a |

## Current status

Tickets **01–09 implemented**: smoke slice, real-model chat + SSE streaming, file ops + tool call UI, approval flow + elicitation (`agent.ask_user`), guardrails, run manager, agent management UI, providers, `run_subagent`, memory + skills (ticket 06), scheduler/heartbeat (ticket 07), MCP client infrastructure (08a), MCP credentials/OAuth (08b), external channels (08c), and observability + spend (ticket 09).

**Current: Ticket 10 (Tauri desktop app) in progress. Next: Ticket 11 (Testing hardening). CaberCore extraction is deferred.**

**Ticket 10 (Tauri Desktop App):** IN PROGRESS. macOS ARM64 (Apple Silicon) only — macOS Intel and Windows builds require cross-compilation/CI and are not yet set up.
- Tauri 2 shell wraps the React frontend + packaged PyInstaller gateway.
- Gateway supervisor (`frontend/src-tauri/src/gateway.rs`): starts the PyInstaller gateway in its own process group, routes stdout/stderr to `<app_data_dir>/logs/gateway.log`, kills the full process group on app exit.
- Desktop auth uses **bearer token** (not cookies): login returns `session_token` in the JSON response, frontend stores it in `localStorage`, sends it as `Authorization: Bearer <token>` on every request. The backend accepts the token from either the cookie or the bearer header. This avoids cross-site cookie issues between the Tauri webview origin (`tauri.localhost`) and the gateway (`127.0.0.1:8081`).
- Desktop API base: `http://127.0.0.1:8081` (not `tauri.localhost`, which is intercepted by Tauri's custom protocol handler).
- Default agents (`caber`, `agent-builder`) seed on first launch — PyInstaller bundles `defaults/*.yaml` via `--add-data` in `scripts/build-gateway.sh`.
- Gateway log: `tail -f "$HOME/Library/Application Support/com.caberos.desktop/logs/gateway.log"`

**Docker:** IMPLEMENTED. Full stack via docker-compose:
- Backend: `python:3.12-slim` + uv + bubblewrap (bwrap) for shell sandboxing, `SYS_ADMIN` cap for user namespaces.
- Frontend: multi-stage Node build → nginx:alpine, reverse-proxies `/api` and `/health` to backend, SSE buffering disabled.
- Data persists in named volume `caberos-data`. Postgres option commented out in `docker-compose.yml`.
- `./scripts/docker.sh {up|down|logs|rebuild}`

**Ticket 07 (Scheduler/Heartbeat):** IMPLEMENTED. Heartbeat scheduler with multi-mode UI.

**Ticket 08a (MCP Client Infrastructure):** IMPLEMENTED. MCP client (stdio/HTTP), server registry, credential store, DB models, 19 API routes, connectors page, agent bindings. 26 tests pass.

**Ticket 08b (MCP Credentials — API Key + OAuth):** IMPLEMENTED. API key flow, OAuth loopback flow with token refresh, revoke, catalog integration.

**Ticket 08c (External Channels):** IMPLEMENTED. Four channels:
- **Telegram** — polling + webhook, typing indicator, 4096-char split, Markdown
- **Discord** — slash commands + message create + DM, 2000-char split, Markdown
- **Zalo OA** — webhook, HMAC-SHA256 verification, `cs` message type, plain text
- **Zalo Bot Platform** — polling + webhook, typing indicator, 2000-char split, `X-Bot-Api-Secret-Token` verification, Markdown
- Channel registry, API routes, frontend Channels page, per-channel test state
- **SSL fix:** `ssl_utils.py` — shared CA bundle path (Homebrew `ca-certificates`) for corporate firewall compatibility. All httpx clients use `verify=SSL_CERT_PATH`.
- 68 channel tests pass (29 Telegram + 39 Discord/Zalo).

**Ticket 09 (Observability + Spend):** IMPLEMENTED.
- **API:** `GET /api/runs` (filterable list), `GET /api/runs/{id}` (detail with messages + audit), `GET /api/audit` (syscall log), `GET /api/spend` (today/7d/30d breakdown by agent + trigger), `GET /api/operator-audit`, `GET /api/health`
- **Frontend:** Observability page with 4 tabs (Runs, Syscall Log, Spend, Health). Run detail view with messages + audit records inline. Denied syscalls highlighted.
- **Tests:** Observability coverage verified.

**Model discovery enhancements (this session):**
- Thinking/reasoning metadata + per-message thinking controls (brain icon, effort slider)
- `max_context_tokens` and `max_output_tokens` from OpenRouter live metadata
- Image-generation models filtered from chat discovery (402 → 393 models)
- OpenRouter discovery uses live metadata instead of LiteLLM static catalog

**311 backend tests pass.** Frontend type-checks cleanly (`tsc --noEmit`).

## Build & test commands

```bash
# Backend tests (from repo root)
cd backend && uv run pytest -v

# Lint
cd backend && uv run ruff check src/ tests/
cd backend && uv run ruff format --check src/ tests/

# Smoke test (end-to-end pipeline with scripted model double, no real LLM)
cd backend && uv run python ../scripts/smoke.py test-agent "echo hello"

# Seed DB (creates default operator + capabilities)
cd backend && uv run python -m agentos.seed

# Database migrations (Alembic)
cd backend && uv run alembic upgrade head          # apply all migrations
cd backend && uv run alembic current               # check current revision
cd backend && uv run alembic revision --autogenerate -m "description"  # create migration
cd backend && uv run alembic stamp head            # mark existing DB as up-to-date

# Start dev server (backend on :8081)
./scripts/dev.sh

# Frontend dev server (Vite on :5173, proxies /api to backend)
cd frontend && npm run dev

# Frontend build
cd frontend && npm run build

# Install/setup
./scripts/install.sh

# Desktop app (Tauri — build + run the .app)
cd frontend && npm run desktop:build
open frontend/src-tauri/target/release/bundle/macos/CaberOS.app

# Desktop dev (Tauri dev mode — hot reload)
cd frontend && npm run desktop:dev

# Docker (full stack — backend + frontend via nginx)
./scripts/docker.sh up        # build + start, → http://localhost:8080
./scripts/docker.sh logs      # tail logs
./scripts/docker.sh down      # stop
./scripts/docker.sh rebuild   # force rebuild images
```

## Backend module layout

```
backend/src/agentos/
├── config.py            — settings (env vars, paths, hitl_timeout)
├── db.py                — async SQLAlchemy engine, session factory, init_db (create_all + schema patches)
├── config_schema.py     — Pydantic models (AgentConfig, ModelConfig, etc.)
├── agent_service.py     — agent CRUD, versioning, YAML import/export
├── secret_store.py      — Fernet encryption for provider keys
├── ssl_utils.py         — shared SSL CA bundle path (corporate firewall fix)
├── seed.py              — seed default operator + capabilities
├── runner.py            — run_agent() + ScriptedModel demo (7-turn workspace check)
├── run_manager.py       — RunContext, _active_runs registry, start/stop/get run
├── pipeline.py          — D19's 13-step execution pipeline + LLM title generation
├── main.py              — FastAPI app entry point (routers, CORS, lifespan)
├── auth.py              — operator auth (session cookie OR bearer token, bcrypt, login/logout/me)
├── models/              — SQLAlchemy models (all v0.1 tables)
│   └── elicitation.py   — ElicitationRequest model
├── capabilities/        — capability registry + built-in tools
│   ├── registry.py      — CapabilityDef, CapabilityRegistry
│   ├── builtin.py       — register_builtin_capabilities() (tools + memory caps)
│   └── tools/           — file, shell, web, datetime, subagent, memory
├── memory/              — memory layers and promotion (D34)
│   ├── notebook.py      — MEMORY.md read/write (agent home dir)
│   ├── auto_extract.py  — post-run durable fact extraction and deduplication
│   ├── triples.py       — knowledge graph (subject/predicate/object triples)
│   └── recall.py        — semantic recall (FTS5 / Postgres tsvector)
├── skills/              — skill loading (D11b, D11c) — NOT auto-injected
│   └── loader.py        — list_skills (menu), load_skill (full content + resources)
├── db_backends/         — pluggable database backends (D5)
│   ├── base.py          — DatabaseBackend ABC
│   ├── factory.py       — URL scheme → backend class
│   ├── sqlite_backend.py — SQLite + aiosqlite (WAL, FTS5)
│   └── postgres_backend.py — Postgres + asyncpg (tsvector, GIN)
├── api/                 — REST API routes (control plane)
│   ├── agents.py        — list/get agents
│   ├── chat.py          — chat channel (POST /message, GET /runs/{id}/events SSE, run management)
│   ├── providers.py     — provider CRUD, model discovery, validation
│   ├── approvals.py     — approval list/approve/reject API
│   ├── elicitation.py   — elicitation respond API
│   ├── agent_files.py   — MEMORY.md, skills, workspace, memory management (triples/clear)
│   ├── mcp.py           — MCP server CRUD, credentials, OAuth, catalog, bindings
│   ├── channels.py      — external channel CRUD, webhook receiver, test
│   └── observability.py — runs list/detail, audit log, spend, health (Ticket 09)
├── channels/            — external messaging channels (Ticket 08c)
│   ├── base.py          — Channel ABC, OutboundMessage, OutputConstraints
│   ├── registry.py      — channel class + active instance registry
│   ├── telegram.py      — Telegram (polling + webhook)
│   ├── discord.py       — Discord (slash commands, message create)
│   ├── zalo_oa.py       — Zalo Official Account (webhook + HMAC)
│   └── zalo_bot.py      — Zalo Bot Platform (polling + webhook + typing)
├── mcp/                 — MCP client infrastructure (Ticket 08a/08b)
│   ├── client.py        — MCP stdio/HTTP client
│   ├── registry.py      — server registry, tool discovery
│   ├── credentials.py   — encrypted credential storage
│   └── oauth.py         — OAuth loopback flow
├── sandbox/             — process-level sandbox
│   ├── base.py          — SandboxBackend ABC, get_backend()
│   ├── seatbelt.py      — macOS sandbox-exec
│   ├── bwrap.py         — Linux bubblewrap
│   └── workspace.py     — path validation, workspace creation
├── syscall/             — the single boundary every capability call crosses
│   ├── protocol.py      — SyscallHandler Protocol, ToolCall, SyscallResult
│   ├── mediator.py      — SyscallHandler (approval gate, elicitation, audit)
│   ├── lock.py          — per-Session asyncio lock (concurrent sessions)
│   ├── approval_registry.py — asyncio.Event registry for approval resolution
│   └── elicitation_registry.py — asyncio.Event registry for elicitation resolution
└── harness/             — agent execution loop
    ├── base_prompt.py   — static platform system prompt (same for every agent)
    ├── context.py       — system prompt + tool schema assembly + multimodal message building
    ├── scripted_model.py — ScriptedModel double (no real LLM needed)
    ├── litellm_adapter.py — LiteLLM adapter (real model, streaming, reasoning tokens)
    ├── guardrails.py    — input/output guardrails (secret redaction, injection detection)
    └── loop.py          — Harness.run() — the agent loop
```

## Entry point architecture

All entry points (API server, CLI, gateway, native app) call `run_agent()`:

```
CLI (future)          API Server (chat.py)         Native App (future)
Gateway (future)      Batch Runner (future)        Python Library
         \                |                /
          \               |               /
           →  run_agent(agent_id, text, user_id, event_callback, ...)  ← runner.py
                    |
                    →  Pipeline.handle_inbound()  ← pipeline.py
                            |
                            →  Harness.run()      ← harness/loop.py
                                    |
                                    →  Model (LiteLLM or Scripted)
                                    →  SyscallHandler (mediator)
                                            →  Capabilities (tools)
```

`run_agent()` handles: DB session, model selection, harness+pipeline wiring, event emission, error handling. The caller provides an `event_callback` for transport (SSE, stdout, WebSocket, etc.).

## Key patterns

- **SyscallHandler Protocol:** The harness depends on the `SyscallHandler` protocol, not a concrete impl. This lets us swap the stub (auto-approve) for the real mediator (approval flow) without touching the harness.
- **ScriptedModel:** Tests use a scripted model double — no API key, no real LLM. The smoke script also uses it.
- **Idempotent registry:** `CapabilityRegistry.register()` is idempotent — safe to call multiple times.
- **Workspace path validation:** All file operations go through `WorkspaceManager.validate_path()` which rejects paths that escape the workspace via `..` or absolute paths.
