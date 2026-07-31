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
- `.scratch/caberos-v0.1/issues/` — 10 tracer-bullet tickets (01-10) with blocking edges. These drive the work order.
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
01 ──→ 02 ──→ 03 ──→ 04 ──→ 08
         │      │
         │      └──→ 09 ──→ 10
         │
         ├──→ 05 (parallel with 03/04)
         ├──→ 06 (parallel with 03/04/05) ──→ 07
```

- **01** — Smoke test vertical slice (tracer bullet, no blockers)
- **02** — Dashboard chat with real model
- **03** — File operations + tool call visibility
- **04** — Approval flow
- **05** — Agent management UI
- **06** — Memory + skills
- **07** — Heartbeat
- **08** — Connectors (Outlook)
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
6. Skills — prompt injection (ticket 06)
7. KG facts — knowledge graph (ticket 06)

The base prompt is the CaberOS equivalent of GoClaw's `AGENTS.md` — a static set of operating instructions that tells the agent how to work inside the system, regardless of its soul/persona/task.

## SSE event types (for the frontend)

`typing`, `thinking`, `token`, `tool_call` (pending → pending_approval → pending_input → running → complete/denied), `turn_complete`, `message_complete`, `heartbeat`, `guardrail_correction`, `guardrail_warning`, `clarifying_question`

## Built-in capabilities (10 tools)

| Tool | Egress | Approval | Description |
|---|---|---|---|
| `file.read` | no | no | Read a file from the workspace |
| `file.write` | no | no | Write a file to the workspace |
| `file.list` | no | no | List files in a directory |
| `file.search` | no | no | Search file contents (grep with regex + glob filter) |
| `file.glob` | no | no | Find files by name pattern |
| `shell.run` | yes | yes | Execute a shell command in the sandbox |
| `datetime.now` | no | no | Get current date/time (with optional timezone) |
| `web.search` | yes | yes | Search the web via DuckDuckGo (free, no API key) |
| `web.fetch` | yes | yes | Fetch a URL and return text content (HTML → text) |
| `agent.ask_user` | no | no | Ask the user a clarifying question (HITL elicitation) |

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
| Skills | Filesystem — `workspace/skills/{agent_id}/` | n/a |

## Current status

- **Baseline commit:** `c50e2a7` on `main` — spec, plans, design system, tickets.
- **Ticket 01 (smoke test vertical slice):** IMPLEMENTED. All 23 tests pass, smoke script works end-to-end.
- **Ticket 02 (dashboard chat with real model):** IMPLEMENTED. 37 tests pass. LiteLLM adapter, provider API, operator auth, chat channel (SSE), React frontend (login + agent list + conversation view with streaming). Frontend builds successfully.
- **Ticket 03 (file ops + tool call visibility):** IMPLEMENTED. 50 tests pass. Real syscall layer (subject injection, result reduction), tool call blocks (collapsible, state icons), thinking blocks (streaming, auto-collapse), per-turn cost badges. shadcn/ui components.
- **Ticket 04 (approval flow + elicitation):** IMPLEMENTED. Two human-in-the-loop mechanisms:
  - **Approval gate:** Syscall mediator pauses run on `require_approval=true` capabilities, creates ApprovalRequest, emits `pending_approval` SSE event with approval_id. Frontend shows inline Approve/Deny buttons with "Remember for this session" checkbox (session-scoped auto-allow for same capability+args). Approval API (`GET /api/approvals`, `POST approve/reject`) resolves asyncio.Event via process-global registry. Agent continues after denial (tries alternative approach).
  - **Elicitation (clarifying question):** New capability `agent.ask_user(question, options?)`. When the agent calls it, the mediator creates an ElicitationRequest, emits `clarifying_question` SSE event, and pauses the run. Frontend shows the question with option buttons (if `options` provided) or a free-text input field. User responds via `POST /api/elicitation/{id}/respond`, which resolves the asyncio.Event. The user's response becomes the tool call result — the agent continues with that context (same run, same context, not a new message). ElicitationRequest model, elicitation_registry, 5 tests. Demo exercises the full flow with a 3-option question.
- **Guardrails (D2):** IMPLEMENTED. Both input and output guardrails.
  - **Input guardrails** (run on user message before storage/processing): secret redaction (don't persist API keys in message history), prompt injection detection (warns but doesn't block — the message still goes through, logged for audit). Does NOT check context leakage (users are allowed to reference their own file paths).
  - **Output guardrails** (run on model's final answer before it reaches the user): secret redaction (`[REDACTED]`), prompt injection detection (flags "ignore previous instructions", role reset tags, ChatML markers — warns but doesn't remove, operator should see what the agent tried to echo), context leakage check (redacts home paths to `[PATH]`, flags agent home dir paths, system prompt fragments, 3+ internal UUIDs).
  - 81 tests pass. SSE events: `guardrail_correction` (replaces streamed content with clean version), `guardrail_warning` (shows warnings in UI, with `direction: "input"` or `"output"`). Input warnings show in a separate yellow box before the streaming response.

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
├── config.py            — settings (env vars, paths)
├── db.py                — async SQLAlchemy engine, session factory, init_db (create_all + schema patches)
├── config_schema.py     — Pydantic models (AgentConfig, ModelConfig, etc.)
├── agent_service.py     — agent CRUD, versioning, YAML import/export
├── secret_store.py      — Fernet encryption for provider keys
├── seed.py              — seed default operator + capabilities
├── runner.py            — run_agent() — universal entry point (CLI, API, gateway, native app)
├── pipeline.py          — D19's 13-step execution pipeline
├── main.py              — FastAPI app entry point (routers, CORS, lifespan)
├── auth.py              — operator auth (session+cookie, bcrypt, login/logout/me)
├── models/              — SQLAlchemy models (all v0.1 tables)
├── capabilities/        — capability registry + built-in tools
│   ├── registry.py      — CapabilityDef, CapabilityRegistry
│   ├── builtin.py       — register_builtin_capabilities()
│   └── tools/           — file.read, file.write, file.list, file.search, file.glob,
│                         shell.run, datetime.now, web.search, web.fetch
├── api/                 — REST API routes (control plane)
│   ├── agents.py        — list/get agents
│   ├── chat.py          — dashboard chat channel (calls run_agent(), broadcasts SSE)
│   └── providers.py     — provider CRUD, model discovery, validation
├── sandbox/             — process-level sandbox
│   ├── base.py          — SandboxBackend ABC, get_backend()
│   ├── seatbelt.py      — macOS sandbox-exec
│   ├── bwrap.py         — Linux bubblewrap
│   └── workspace.py     — path validation, workspace creation
├── syscall/             — the single boundary every capability call crosses
│   ├── protocol.py      — SyscallHandler Protocol, ToolCall, SyscallResult
│   ├── mediator.py      — StubSyscallHandler (auto-approve, writes audit)
│   └── lock.py          — per-Contact asyncio lock
└── harness/             — agent execution loop
    ├── base_prompt.py   — static platform system prompt (same for every agent)
    ├── context.py       — system prompt + tool schema assembly + multimodal message building
    ├── scripted_model.py — ScriptedModel double (no real LLM needed)
    ├── litellm_adapter.py — LiteLLM adapter (real model, D6/D39)
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
