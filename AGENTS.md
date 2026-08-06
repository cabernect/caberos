# CaberOS — Agent Context

## What is this project?

CaberOS is an open-source, local-first AI Agent Operating System. It hosts personal agents on your machine, gives them a workspace, connects them to your services (email, calendar), and lets them run shell commands in a sandbox. The OS supplies the harness, mediates every capability call, and gives you a dashboard to manage your agent(s).

**Language:** Python 3.12 (backend), React 19 + Vite (frontend)
**Package manager:** uv (backend), npm (frontend)
**Repo structure:** Monorepo — `/backend`, `/frontend`, `/docs`, `/sandbox`, `/scripts`

## Where things are

- `docs/spec-v0.1.md` — the full specification. 40 decisions (D1-D40). Read this first.
- `docs/plans/` — 15 implementation plans (00-14) with detailed specs, file lists, verification steps. These are the implementation reference.
- `docs/plans/README.md` — plan index and build order.
- `.scratch/caberos-v0.1/issues/` — tracer-bullet tickets (01-10, with 08 split into 08a/08b) with blocking edges. These drive the work order.
- `design-system/caberos/` — design system (dark-only, AI-native, conversation-first). MASTER.md + page specs.

## Key decisions (quick reference)

- **D1:** Agents are configuration, not code. AgentConfig is a DB row, versioned.
- **D2:** Pydantic AI is the harness. LiteLLM is the model transport.
- **D3:** Python 3.12 + FastAPI, one daemon.
- **D5:** SQLAlchemy 2.0 async + aiosqlite. SQLite with WAL mode. Schema via `create_all` + incremental patches in `init_db()` (Alembic deferred to Postgres migration).
- **D25:** Agent config lives in the DB as versioned rows (AgentVersion). YAML for import/export only.
- **D33:** The gateway is a headless daemon. The React dashboard is one client of the API. API is client-agnostic (REST + SSE).
- **D34:** Three-layer memory: working memory (session), MEMORY.md (file in agent home dir `~/agentos/agents/{agent_id}/`), knowledge graph (SQLite triples). FTS5 default, embeddings configurable.
- **D35:** Agent identity = `soul`, `persona`, `task` — versioned config fields on AgentConfig (in the DB). NOT workspace files. MEMORY.md is the exception (agent-managed file, not versioned).
- **D37:** Workspaces are shared directories for working files only. Identity is in the DB, MEMORY.md is in the agent home dir — neither in the workspace.
- **D38:** MCP tools are in v0.1 (revised — was v0.2). CLI/TUI (`caber`) still deferred to v0.2. v0.1 ships React dashboard + MCP integration. `scripts/smoke.py` is a dev tool, not a product CLI.
- **D9/D13 (revised):** Four capability kinds: `tool`, `sub_agent`, `memory`, `mcp_tool`. Native `connector_action` kind removed — MCP replaces it. CaberOS owns credential custody at rest; MCP servers receive credentials via env/headers at runtime.
- **D39:** Providers are first-class DB entities with encrypted keys (Fernet). Agents reference providers by id. LiteLLM is the transport.
- **D40:** Model discovery: dynamic where available (OpenAI, Google, Ollama), free-text fallback (Anthropic), always allow override. Save-time validation via 1-token completion.

## Ticket dependency graph

```
01 ──→ 02 ──→ 03 ──→ 04 ──→ 08a ──→ 08b
         │      │
         │      └──→ 09 ──→ 10
         │
         ├──→ 05 (parallel with 03/04)
         ├──→ 06 (parallel with 03/04/05) ──→ 07
         └──→ 05a (parallel with 05)
```

- **01** — Smoke test vertical slice (tracer bullet, no blockers)
- **02** — Dashboard chat with real model
- **03** — File operations + tool call visibility
- **04** — Approval flow
- **05** — Agent management UI
- **05a** — Global settings & provider management
- **06** — Memory + skills
- **07** — Scheduler (heartbeat is the first mode; cron/event triggers deferred to v0.5)
- **08a** — MCP client infrastructure (generic, no OAuth)
- **08b** — Outlook connector (OAuth, blocked by 08a)
- **09** — Observability + spend
- **10** — Testing hardening

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

## System prompt assembly

Every agent's system prompt is assembled in this order (D35 + base prompt):

1. **Base system prompt** (`harness/base_prompt.py`) — platform-level operating instructions, same for every agent. Covers: what CaberOS is, workspace sandboxing, capabilities & approval, `agent.ask_user` for clarifying questions, memory (MEMORY.md), output rules (no secrets, no internal paths, no system prompt leakage, no following injected file instructions), conversational style (direct, no filler, match language).
2. **Soul** — agent identity, values, principles (user-edited, versioned)
3. **Persona** — tone, communication style (user-edited, versioned)
4. **Task** — mission, instructions (user-edited, versioned)
5. MEMORY.md — long-term memory (ticket 06)
6. Available Skills — menu of skill names + descriptions (ticket 06). The agent calls `skills_load(name)` to get the full content when it decides to use one. Skills are NOT auto-injected — the agent sees the menu and chooses.
7. KG facts — knowledge graph (ticket 06)
8. Recall snippets — semantic recall fallback (ticket 06)

The base prompt is the CaberOS equivalent of GoClaw's `AGENTS.md` — a static set of operating instructions that tells the agent how to work inside the system, regardless of its soul/persona/task.

## SSE event types (for the frontend)

`typing`, `thinking`, `token`, `tool_call` (pending → pending_approval → pending_input → running → complete/denied), `turn_complete`, `message_complete`, `heartbeat`, `guardrail_correction`, `guardrail_warning`, `clarifying_question`

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

## Multimodal input

Users can attach images, URLs, and text files to their chat messages. These are sent as multimodal content to the LLM (OpenAI/LiteLLM format):

- **Images**: base64-encoded `data:image/png;base64,...` → `{"type": "image_url", "image_url": {"url": "..."}}`
- **URLs**: sent directly → `{"type": "image_url", "image_url": {"url": "https://..."}}` (model fetches)
- **Text files**: content appended to the message as `{"type": "text", "text": "--- filename ---\n..."}`

The `messages.attachments` column stores attachment metadata (type, mime_type, filename) — not the base64 data (too large for SQLite). The actual image data is carried in the `InboundMessage.attachments` list and passed to `build_message_history` at runtime.

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

Tickets **01–06 implemented**: smoke slice, real-model chat + SSE streaming, file ops + tool call UI, approval flow + elicitation (`agent.ask_user`), guardrails (input/output secret redaction + injection detection), run manager (reconnectable SSE, stop/poll), file-write diffs, agent management UI, global settings/providers, `run_subagent` tool, and now **memory + skills** (ticket 06): MEMORY.md, knowledge graph triples, FTS5 semantic recall, skill loading with trigger matching, full D35 context assembly.

**Next up: Ticket 07 (Scheduler/Heartbeat)** — the sidebar "Scheduler" nav becomes a unified scheduling page with heartbeat as the first mode. Ticket 08 is split into 08a (generic MCP client) and 08b (Outlook OAuth). Ticket 10 note: write security tests per-ticket, not all deferred to the hardening pass.

**Ticket 06 (Memory + skills):** IMPLEMENTED. Three-layer memory + skills:
- **MEMORY.md** — agent-curated notebook in `~/agentos/agents/{id}/MEMORY.md`, always loaded into context. Agent updates via `memory_update` capability; user edits via `GET/PUT /api/agents/{id}/memory`.
- **Knowledge graph** — `memory_triples` table (subject, predicate, object, contact_id, agent_id). `memory_remember_fact` and `memory_query_facts` capabilities (subject-scoped, D10). Note: triple's "subject" exposed as `entity` in the schema to avoid colliding with D10's reserved `subject` param.
- **Semantic recall** — FTS5 (SQLite) or tsvector (Postgres) on conversation snippets. `memory_recall` and `memory_store` capabilities. Bounded: top 3 snippets auto-fetched as context fallback.
- **Skills** — markdown `SKILL.md` with YAML frontmatter (name, description, triggers). System-level `skills/` + per-agent `workspace/skills/{id}/`. Trigger-matched against user message, injected into system prompt. Aligned with the [Agent Skills spec](https://agentskills.io/specification): supports `license`, `compatibility`, `metadata`, `allowed-tools` optional fields. 17 Anthropic skills ship out of the box (pdf, docx, pptx, xlsx, mcp-builder, skill-creator, frontend-design, webapp-testing, etc.).
- **Full context assembly (D35):** base prompt → soul → persona → task → MEMORY.md → skills → KG facts → recall snippets. All loaded by the harness before the model call.
- **Cross-contact isolation** — tested as a security property (3 tests: triples, recall, syscall-level). Contact A's memory is invisible to Contact B.
- **DB backends pluggable** — SQLite (default) or Postgres via `AGENTOS_DATABASE_URL=postgresql+asyncpg://...`. `db_backends/` package with `DatabaseBackend` ABC, `SQLiteBackend`, `PostgresBackend`. FTS5 ↔ tsvector handled per-backend.
- **149 backend tests pass.**

**Recent fixes (this session):**
- Fixed `Session is already flushing` crash in the approval flow (`syscall/mediator.py` now uses a separate DB session for `ApprovalRequest`).
- Added model stream idle timeout (30s) + request timeout (120s) in `litellm_adapter.py` — prevents runs hanging forever on a stalled provider stream.
- Fixed streaming text/tool-call ordering in the frontend (`Conversation.tsx`) — text now flushes into the ordered item list before a tool call/approval card, so approvals don't render above already-streamed text.

**128 backend tests pass.** Frontend type-checks cleanly (`tsc --noEmit`). Ruff clean except long-line (E501) warnings.

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
```

## Backend module layout

```
backend/src/agentos/
├── config.py            — settings (env vars, paths, hitl_timeout)
├── db.py                — async SQLAlchemy engine, session factory, init_db (create_all + schema patches)
├── config_schema.py     — Pydantic models (AgentConfig, ModelConfig, etc.)
├── agent_service.py     — agent CRUD, versioning, YAML import/export
├── secret_store.py      — Fernet encryption for provider keys
├── seed.py              — seed default operator + capabilities
├── runner.py            — run_agent() + ScriptedModel demo (7-turn workspace check)
├── run_manager.py       — RunContext, _active_runs registry, start/stop/get run
├── pipeline.py          — D19's 13-step execution pipeline + LLM title generation
├── main.py              — FastAPI app entry point (routers, CORS, lifespan)
├── auth.py              — operator auth (session+cookie, bcrypt, login/logout/me)
├── models/              — SQLAlchemy models (all v0.1 tables)
│   └── elicitation.py   — ElicitationRequest model
├── capabilities/        — capability registry + built-in tools
│   ├── registry.py      — CapabilityDef, CapabilityRegistry
│   ├── builtin.py       — register_builtin_capabilities() (tools + memory caps)
│   └── tools/           — file, shell, web, datetime, subagent, memory
├── memory/              — three-layer memory (D34)
│   ├── notebook.py      — MEMORY.md read/write (agent home dir)
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
│   └── agent_files.py   — MEMORY.md, skills, workspace, memory management (triples/clear)
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
