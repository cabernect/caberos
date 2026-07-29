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
- **D5:** SQLAlchemy 2.0 async + aiosqlite + Alembic. SQLite with WAL mode.
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

## How to implement

1. **Read the ticket** (`.scratch/caberos-v0.1/issues/NN-*.md`) for what to build and acceptance criteria.
2. **Consult the relevant plans** (`docs/plans/NN-*.md`) for detailed specs — Pydantic models, file lists, schemas, verification steps.
3. **Implement end-to-end** (vertical slice: DB + API + harness + sandbox + frontend).
4. **Verify** against the ticket's acceptance criteria.
5. **Commit** per ticket. No Co-Authored-By lines.
6. **Update this file** if you learn something that a fresh session needs to know.

## SSE event types (for the frontend)

`typing`, `thinking`, `token`, `tool_call` (pending → running → complete/denied), `turn_complete`, `message_complete`, `heartbeat`

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

# Start dev server (backend on :8081)
./scripts/dev.sh

# Install/setup
./scripts/install.sh
```

## Backend module layout

```
backend/src/agentos/
├── config.py            — settings (env vars, paths)
├── db.py                — async SQLAlchemy engine, session factory
├── config_schema.py     — Pydantic models (AgentConfig, ModelConfig, etc.)
├── agent_service.py     — agent CRUD, versioning, YAML import/export
├── secret_store.py      — Fernet encryption for provider keys
├── seed.py              — seed default operator + capabilities
├── pipeline.py          — D19's 13-step execution pipeline
├── main.py              — FastAPI app entry point
├── models/              — SQLAlchemy models (all v0.1 tables)
├── capabilities/        — capability registry + built-in tools
│   ├── registry.py      — CapabilityDef, CapabilityRegistry
│   ├── builtin.py       — register_builtin_capabilities()
│   └── tools/           — file.read, file.write, file.list, shell.run
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
    ├── context.py       — system prompt + tool schema assembly
    ├── scripted_model.py — ScriptedModel double (no real LLM needed)
    └── loop.py          — Harness.run() — the agent loop
```

## Key patterns

- **SyscallHandler Protocol:** The harness depends on the `SyscallHandler` protocol, not a concrete impl. This lets us swap the stub (auto-approve) for the real mediator (approval flow) without touching the harness.
- **ScriptedModel:** Tests use a scripted model double — no API key, no real LLM. The smoke script also uses it.
- **Idempotent registry:** `CapabilityRegistry.register()` is idempotent — safe to call multiple times.
- **Workspace path validation:** All file operations go through `WorkspaceManager.validate_path()` which rejects paths that escape the workspace via `..` or absolute paths.
