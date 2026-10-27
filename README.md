# CaberOS

<p align="center">
  <strong>Local-first AI Agent Operating System</strong>
</p>

<p align="center">
  <a href="../../releases/latest">Download (macOS · Windows)</a> ·
  <a href="https://caberos.cabernect.workers.dev">Website</a> ·
  <a href="#features">Features</a> ·
  <a href="#quick-start">Quick Start</a> ·
  <a href="#architecture">Architecture</a> ·
  <a href="docs/TECHNICAL.md">Technical Reference</a> ·
  <a href="docs/PRODUCT.md">Product</a> ·
  <a href="CONTRIBUTING.md">Contributing</a>
</p>

---

CaberOS is an open-source, local-first AI Agent Operating System. It hosts personal agents on your machine, gives them a workspace, connects them to your services, lets them drive a real browser, and produces versioned documents — while the OS mediates every capability call, keeps an audit trail of every action, and accounts for every token spent.

**Local storage, governed egress.** Agents, memory, workspace, and the audit trail live on your machine. Model providers (OpenAI, Anthropic, Google, Ollama, OpenRouter) receive the inputs you configure them to see under your permission policy — egress capabilities (web fetch, browser, shell, remote embeddings) cross an approval boundary, and remembered scopes let you skip re-prompting where you choose.

## Why "OS"?

An operating system's job is identity, permissions, resource accounting, mediated access to resources, and audit — for processes. CaberOS does the same job for agents. Every capability call crosses a single boundary (the **syscall layer**) which resolves who the caller is, checks permission, injects credentials, executes, and writes an audit record.

Adding a new integration (Notion, GitHub, Slack) is a new capability, not a new subsystem. The design doesn't change.

## What's new in v0.2.0 — *Agent Workbench*

*The current development line, integrated on `feat/v0.2.0` and in release preparation — see the [v0.2.0 release plan](docs/plans/v0.2-release-plan.md).*

- **Today home** — Needs-you approvals/elicitations, recent activity, and an ask-your-agent entry point on first load.
- **Guided first run** — login → optional credential step → onboarding with real runtime checks (browser, sandbox, Node.js, uv, Git) instead of static setup lists.
- **Redesigned workbench** — reworked frontend with a span-tree/waterfall trace explorer and a context inspector over the unified model-call ledger; provider thinking surfaces only when real reasoning content is reported.
- **Artifacts & previews** — versioned DOCX/XLSX/PPTX/PDF with in-app previews and immutable revision history.
- **Managed browser** — Chrome-for-Testing with consent-gated install, headless or visible mode, operator takeover.
- **Governed skills & reflection** — three-scope skills with versioned drafts; session-close reflection can revise an agent's own local skills from frozen evidence.
- **Bounded memory** — session-close learning writes transcript summaries and durable facts; MEMORY.md publishes under a token ceiling.
- **Knowledge Vault** — lexical FTS search by default; optional hybrid embeddings (local setups work once a model is configured; remote embeddings require explicit egress consent).
- **Durable scheduling & notifications** — real timezones, missed-run recovery, retries, and deep-linked notifications.
- **Runtime readiness** — model catalog with pricing, consent-gated managed installs for optional runtimes.

## Features

### Core

- **Real model chat** — streaming SSE, multi-provider support (OpenAI, Anthropic, Google, Ollama, OpenRouter), thinking/reasoning controls with per-message effort adjustment
- **Tool use** — file read/write/search, shell (sandboxed, background terminals), web search/fetch (markdown extraction + pagination), sub-agents, datetime, skills
- **Approval flow** — egress capabilities (shell, web, browser) ask under your configured policy; decisions can be remembered per-scope (exact, same-verb, pattern, capability)
- **Elicitation** — agents ask clarifying questions via `agent_ask_user`; the dashboard shows a prompt bar
- **Guardrails** — input/output secret redaction, prompt-injection detection, system-prompt leakage prevention
- **Progressive capability discovery** — `capabilities_search`/`capabilities_load` expose bounded tool metadata on demand; schemas load per-run without widening authority

### Agent management

- **Versioned configs** — soul, persona, task, model, capabilities, limits are DB rows with full version history
- **YAML import/export** — share agent configs as YAML files
- **Rollback** — revert to any previous agent version
- **Duplicate** — clone an agent with a new ID

### Artifact Studio

- **Tracked deliverables** — `artifact_create` produces DOCX/XLSX/PPTX/PDF from a structured spec, never raw Office XML, saved under `artifacts/`
- **Immutable revisions** — every edit is a new revision; restore writes old bytes as a *new* revision; external-edit conflicts are detected, never overwritten
- **Previews** — in-dashboard renderers for markdown, code, JSON, CSV tables, images, PDF pages, docx elements, pptx slides, xlsx workbooks, and media — in chat, workspace, and skill views
- **Composer** — clipboard image paste, drag/drop, URL attachments, ephemeral preview chips with content-hash dedupe

### Browser automation

- **Managed browser** — Chrome-for-Testing runtime with explicit first-use install consent; headless or visible mode
- **Isolated by default** — ephemeral sessions; opt-in domain-scoped persistent profiles
- **Approval-gated** — `browser_open`/`browser_act` cross the syscall gate; domain leash keeps navigation bounded
- **Visible takeover** — the operator can take control of the browser window mid-run on request

### Skills Studio

- **Three scopes** — built-in, global, and agent-local skills; precedence `agent-local > global > built-in`
- **Versioned library** — publish, promote, duplicate, restore-as-new, disable, archive, purge (guarded by active-run pins)
- **Agent-assisted drafts** — "Create Skill" opens a builder session that drafts in `skill-drafts/`; nothing auto-publishes
- **Safe imports** — ZIP and repo-URL imports pass traversal/symlink/zip-bomb hardening and land as drafts
- **Run pinning** — each run pins exact skill revisions (`rev:` or `live:` hash), so mid-run publishes can't shift a running agent
- **RSI / evolution** — session-close reflection passes can revise an agent's own local skills from session evidence, deduped by fingerprint

### Memory

Three layers (D34):

- **Working memory** — session-scoped conversation, compacted under a context budget
- **MEMORY.md** — agent-scoped living document with identity, bounded by `core_max_tokens`, revisioned with optimistic publication
- **Knowledge graph** — SQLite triples (entity/predicate/object), queried per-contact
- **Session-close learning** — idle sessions close on a deadline-driven sweeper; closing writes a transcript summary + durable-fact extraction, then may run a bounded skill-reflection pass
- **Semantic recall** — FTS5 (SQLite) or tsvector (Postgres); `search_history` reaches across sessions

### Knowledge Vault (RAG)

- **Ingest** — documents extract to structured blocks, chunked parent/child per block type
- **Retrieval** — FTS5 lexical by default (zero egress); optional hybrid embeddings with RRF fusion and bounded parent expansion — retrieval returns source citations and a retrieval trace
- **Index generations** — blue-green rebuild/repair/activate/delete; exactly one active generation
- **Privacy-gated embeddings** — remote embedding providers refuse until egress is explicitly enabled; local endpoints (Ollama etc.) require only a configured embedding model
- **Honest limits** — tabular uploads (.xlsx/.csv) are refused until the row-query layer lands, rather than indexing a misleading text flattening

### MCP integration

- **MCP client** — stdio and HTTP transports
- **Server registry** — CRUD, tool discovery, agent bindings, per-tool `tool_filter` + deny overrides
- **Credentials** — encrypted at rest (Fernet), injected via env/headers at runtime
- **OAuth** — loopback flow with automatic token refresh and reconnect
- **Runtime resolution** — stdio commands resolved against child PATH with fallback dirs and `CABEROS_MCP_RUNTIME_PATH`
- **Catalog** — marketplace of installable MCP servers

### External channels

Four channels route external messages through the same agent pipeline:

- **Telegram** — polling + webhook, typing indicator, 4096-char split, Markdown
- **Discord** — slash commands + message create + DM, 2000-char split, Markdown
- **Zalo OA** — webhook, HMAC-SHA256 verification, `cs` message type
- **Zalo Bot Platform** — polling + webhook, typing indicator, 2000-char split

### Scheduler

- **Schedules** — one-time / interval / cron with IANA timezones and correct DST handling; persisted `next_fire_at` survives restarts
- **Missed-run policy** — skip, run once, or catch up (bounded); overlap modes skip/queue/cancel/parallel; bounded retries as new occurrences
- **Heartbeat facade** — the classic per-agent heartbeat projects onto a managed schedule; old endpoints unchanged
- **Approval + budget** — revision-scoped auto-approve caps and per-run cost overrides; the permission ceiling never widens

### Observability

- **Traces** — expandable span tree, aligned waterfall, and an observation inspector over the unified `model_calls` ledger (chat, embeddings, probes, extractions, titles)
- **Runs** — durable run rows survive disconnects; orphaned runs reconcile to `interrupted` on restart; filterable list + timeline projection
- **Spend** — today / 7d / 30d per agent and trigger, plus a platform-wide ledger scope; unknown pricing is reported as unknown, never silently zero
- **References** — citations list only URLs the agent actually visited; search results stay as trace evidence
- **Notifications** — in-app + browser/Tauri notifications with deep links, dedupe, and read-state that follows what you're looking at
- **Syscall log + health** — every mediated call with allow/deny and arguments; provider, MCP, and channel status

## Quick start

### Option 1: Desktop app (easiest, macOS & Windows)

> **Platform support:** **macOS ARM64** (Tier 1) and **Windows x64** (Tier 2, beta). macOS Intel, Windows on ARM and Linux desktop builds are not available yet — use Docker or local dev there. On Windows, shell commands run in a bundled Microsoft Execution Container (MXC) — **no Docker and no WSL required**. It is experimental and needs a one-click, one-time setup (Observability → Health → *Enable shell sandbox*); until then shell is off with a clear reason and every other capability still works. Full matrix: [docs/platform-support.md](docs/platform-support.md).

**Download the latest release:** [GitHub Releases](../../releases/latest)

Or build from source:

```bash
# Build the Tauri app (bundles the PyInstaller gateway + React frontend)
(cd frontend && npm run desktop:build)

# Launch (from the repo root)
open frontend/src-tauri/target/release/bundle/macos/CaberOS.app
```

```cmd
:: Windows — needs VS Build Tools (VCTools workload) + a Windows SDK, and the
:: MSVC Rust toolchain (rustup default stable-x86_64-pc-windows-msvc), not GNU.
:: Run both in ONE cmd session: vcvars64 sets the environment for the session it
:: runs in, and Git's own link.exe would otherwise shadow the MSVC linker.
call "C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvars64.bat"
cd frontend && npm run desktop:build:windows
:: -> src-tauri\target\release\bundle\nsis\CaberOS_<version>_x64-setup.exe
```

The desktop app packages the entire backend as a PyInstaller executable and supervises it. No Python installation required. Gateway logs are at:

```bash
# macOS
tail -f "$HOME/Library/Application Support/com.caberos.desktop/logs/gateway.log"
# Windows (PowerShell)
Get-Content -Wait "$env:APPDATA\com.caberos.desktop\logs\gateway.log"
```

> **Local rebuilds:** PyInstaller's `--clean` does not prune files already sitting in `frontend/src-tauri/resources/gateway` from an earlier build, so after a version bump delete that folder first — otherwise stale `agentos-<old>.dist-info` metadata gets bundled next to the new one and the gateway can report the old version. CI starts from a fresh checkout, so releases are unaffected.

### Option 2: Docker (any platform)

```bash
git clone https://github.com/cabernect/caberos.git && cd caberos
./scripts/docker.sh up
# → http://localhost:8080
# Login: admin / admin
```

The first launch seeds the default operator and two agents (Caber, AgentBuilder). Data persists in a named Docker volume.

### Option 3: Local dev

**Prerequisites:** Python 3.12+, [uv](https://docs.astral.sh/uv/), Node 22+, npm. For shell sandboxing: macOS (uses built-in `sandbox-exec`) or Linux (`bubblewrap`). Windows uses Microsoft Execution Containers; from a source checkout, point `CABEROS_MXC_EXE_PATH` at the SDK's `wxc-exec.exe` (the installer bundles it). See [docs/platform-support.md](docs/platform-support.md) for details.

```bash
git clone https://github.com/cabernect/caberos.git && cd caberos

# Install backend + frontend dependencies
./scripts/install.sh

# Start both servers (backend :8081, frontend :5173)
./scripts/dev.sh
```

Open `http://localhost:5173` — the Vite dev server proxies `/api` to the backend.

**Creating a release** (maintainers):

```bash
./scripts/release.sh X.Y.Z   # two-phase: release branch PR → merge → re-run to tag
```

Pushing a `v*.*.*` tag triggers the [release workflow](.github/workflows/release.yml) which builds the .dmg, creates a GitHub Release, and deploys the website to Cloudflare automatically. Tags with a `-` suffix (e.g., `v0.1.0-beta`) are marked as prerelease.

## Architecture

```
┌─────────────────────────────────────────────────────┐
│  Clients                                            │
│  ┌──────────┐  ┌──────────┐  ┌──────────────────┐  │
│  │ Browser  │  │ Tauri    │  │ External Channels │  │
│  │ (Vite)   │  │ Desktop  │  │ TG/Discord/Zalo   │  │
│  └────┬─────┘  └────┬─────┘  └────────┬──────────┘  │
└───────┼──────────────┼────────────────┼─────────────┘
        │              │                │
        ▼              ▼                ▼
┌─────────────────────────────────────────────────────┐
│  FastAPI Gateway (REST + SSE)                       │
│  chat · agents · skills · knowledge · schedules ·   │
│  mcp · channels · notifications · observability …   │
└─────┼───────────────────────────────────────────────┘
      ▼
┌─────────────────────────────────────────────────────┐
│  Agent Pipeline                                     │
│  ┌──────────────────────────────────────────────┐   │
│  │  Harness (custom async loop)                │   │
│  │  ┌─────────────┐  ┌──────────────────────┐   │   │
│  │  │ Model       │  │ SyscallHandler       │   │   │
│  │  │ (LiteLLM)   │  │ ┌──────────────────┐ │   │   │
│  │  │             │  │ │ Approval gate    │ │   │   │
│  │  │             │  │ │ Capabilities     │ │   │   │
│  │  │             │  │ │ Sandbox          │ │   │   │
│  │  │             │  │ │ Audit + ledger   │ │   │   │
│  │  │             │  │ └──────────────────┘ │   │   │
│  │  └─────────────┘  └──────────────────────┘   │   │
│  └──────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────┘
      ▼
┌─────────────────────────────────────────────────────┐
│  Storage                                            │
│  SQLite (WAL + FTS5) · Filesystem · Fernet keys    │
└─────────────────────────────────────────────────────┘
```

**Stack:**

| Layer | Technology |
|---|---|
| Backend | Python 3.12, FastAPI, Uvicorn |
| Database | SQLAlchemy 2.0 async, SQLite (WAL + FTS5) / Postgres (asyncpg) |
| Agent harness | Custom (async loop + LiteLLM) |
| Model transport | LiteLLM |
| Browser automation | Playwright/CDP over managed Chrome-for-Testing |
| Frontend | React 19, Vite, TypeScript, Tailwind CSS 4 |
| Desktop | Tauri 2 (Rust) |
| Sandbox | seatbelt (macOS), bwrap (Linux), MXC (Windows); Docker fallback on macOS/Linux |
| Packaging | PyInstaller (gateway), Tauri bundler (desktop) |

### Key design decisions

- **D1:** Agents are configuration, not code. AgentConfig is a DB row, versioned.
- **D2:** Custom async harness. LiteLLM is the model transport — not a pricing/metadata authority.
- **D33:** FastAPI is the gateway/API layer. The React dashboard, Tauri desktop, and external channels are all clients of the same REST + SSE contracts.
- **D34:** Three-layer memory: working memory (session), MEMORY.md (file), knowledge graph (SQLite triples).
- **D35:** Agent identity = soul, persona, task — versioned config fields, NOT workspace files.

See `docs/spec-v0.1.md` for the 40-decision specification and [docs/TECHNICAL.md](docs/TECHNICAL.md) for the deep technical reference (module map, data model, API surface, subsystem internals).

## Configuration

All settings are env vars with the `AGENTOS_` prefix (see `backend/src/agentos/config.py`):

| Env var | Default | Description |
|---|---|---|
| `AGENTOS_DATABASE_URL` | empty (SQLite) | Postgres: `postgresql+asyncpg://user:pass@host/db` |
| `AGENTOS_DB_PATH` | `data/agentos.db` | SQLite database path |
| `AGENTOS_SECRET_KEY_PATH` | `data/secret.key` | Fernet encryption key path |
| `AGENTOS_WORKSPACE_ROOT` | `data/workspaces` | Agent workspace directory |
| `AGENTOS_AGENT_HOME_ROOT` | `~/agentos/agents` | Agent home (MEMORY.md, per-agent skills) |
| `AGENTOS_SKILLS_DIR` | `../skills` | System-level skills directory |
| `AGENTOS_CONTROL_PLANE_HOST` | `127.0.0.1` | API server bind host |
| `AGENTOS_CONTROL_PLANE_PORT` | `8081` | API server port |
| `AGENTOS_YOLO_MODE` | `false` | Skip all approval gates (tools execute immediately) |
| `AGENTOS_HITL_TIMEOUT` | `300` | Approval/elicitation timeout in seconds (0 = wait forever) |
| `AGENTOS_SANDBOX_TIMEOUT` | `30` | Shell command timeout in seconds |
| `AGENTOS_MODEL_REQUEST_TIMEOUT` | `120` | LLM request timeout in seconds |
| `AGENTOS_MODEL_STREAM_IDLE_TIMEOUT` | `30` | SSE stream idle timeout in seconds |

For Docker, copy `.env.docker.example` to `.env.docker` and edit:

```bash
cp .env.docker.example .env.docker
# Edit CABEROS_PORT, AGENTOS_YOLO_MODE, etc.
./scripts/docker.sh up
```

## Default agents

On first launch, CaberOS seeds two agents from YAML files in `backend/src/agentos/defaults/`:

### Caber

Your personal agent. General-purpose, all tools enabled.

- **Soul:** Capable, grounded, takes ownership, prefers doing over deliberating
- **Persona:** Calm, concise, direct. Matches the user's language
- **Task:** Help with whatever you need — questions, web search, files, shell commands
- **Model:** Empty (you select in the UI after adding a provider)

### AgentBuilder

A meta-agent that helps you design and create new agents.

- **Soul:** Thoughtful, collaborative, understands the CaberOS agent config model
- **Persona:** Like a senior engineer pair-programming a config
- **Task:** Ask focused questions, design soul/persona/task, output complete YAML configs

## Skills

Skills are opt-in knowledge packs that agents can load on demand. They are **not** auto-injected into the system prompt — the agent sees a menu of names + descriptions and calls `skills_load(name)` when it decides to use one.

> **Attribution:** Built-in skills are adapted from [Anthropic's skills repository](https://github.com/anthropics/skills).

**Built-in skills** (consolidated in v0.2.0):

| Skill | Description |
|---|---|
| `browser-workflows` | Browser automation recipes |
| `doc-coauthoring` | Document co-authoring |
| `evolve` | Self-improvement via session-close reflection (RSI) |
| `frontend-design` | Frontend UI design |
| `office-documents` | DOCX/XLSX/PPTX/PDF processing |
| `skill-creator` | Create new skills |

Skills can be published to global or agent scopes, assigned per-agent, imported from ZIP/repo, and drafted by agents in builder sessions — all versioned.

## External channels

External channels route messages from messaging platforms through the same agent pipeline as the dashboard. Every channel uses the same run manager, syscall handler, and audit trail.

| Channel | Mode | Verification | Message split |
|---|---|---|---|
| Telegram | Polling + Webhook | Bot token | 4096 chars, Markdown |
| Discord | Slash + Message create + DM | Bot token | 2000 chars, Markdown |
| Zalo OA | Webhook | HMAC-SHA256 | Plain text |
| Zalo Bot | Polling + Webhook | `X-Bot-Api-Secret-Token` | 2000 chars, Markdown |

Configure channels in the dashboard → Channels page, or via the API at `POST /api/channels`.

## Observability

CaberOS tracks every run, every capability call, and every dollar spent.

- **Traces** — expandable span tree + waterfall + inspector over the `model_calls` ledger; per-model-call request bodies re-projected on read (`/api/model-calls/{id}/context`)
- **Runs** — durable list with filters (agent, status, trigger, provider, schedule, channel…); detail view projects a timeline from audit roots through tool calls to approvals
- **Spend** — agent-scoped historic totals plus `scope=platform` ledger accounting; unknown pricing is labeled, never silently zero
- **Notifications** — run lifecycle, approvals, elicitation, MCP/OAuth issues — deduped, deep-linked, and suppressed when you're already looking at the thing
- **Syscall log** — every capability call with timestamp, agent, capability, redacted arguments, result, allowed/denied
- **Health** — provider connectivity, MCP server status, channel status, runtime readiness

## Desktop app

> **Platform support:** macOS ARM64 (Tier 1) and Windows x64 (Tier 2, beta). See [docs/platform-support.md](docs/platform-support.md).
>
> **Download:** [Latest release](../../releases/latest)

The Tauri 2 desktop app packages the entire stack into a native application:

- **PyInstaller gateway** — the FastAPI backend is compiled to a standalone executable, no Python needed
- **Process-group supervision** — the Tauri shell starts the gateway in its own process group and kills it cleanly on exit
- **Bearer-token auth** — the desktop webview uses `Authorization: Bearer` headers instead of cookies (avoids cross-site cookie issues between `tauri.localhost` and `127.0.0.1`)
- **Persistent logs** — gateway stdout/stderr written to `~/Library/Application Support/com.caberos.desktop/logs/gateway.log`
- **Default agents** — `caber` and `agent-builder` seed on first launch from YAML bundled into the executable
- **Signed auto-update** — `downloading → installing → ready` then an explicit `Restart now`

```bash
# Build
cd frontend && npm run desktop:build

# DMG (optional)
npm run desktop:build:dmg

# Dev mode (hot reload)
npm run desktop:dev
```

## Docker

The Docker setup runs the full stack: backend (Python + uv) and frontend (nginx reverse proxy).

```bash
# Build and start
./scripts/docker.sh up

# View logs
./scripts/docker.sh logs

# Stop
./scripts/docker.sh down

# Force rebuild (no cache)
./scripts/docker.sh rebuild
```

**Container details:**

| Service | Image | Port | Notes |
|---|---|---|---|
| `backend` | `python:3.12-slim` + uv | 8081 (internal) | Agents can use bwrap (if `SYS_ADMIN` cap present) or Docker isolation |
| `frontend` | `nginx:alpine` | 80 → `:8080` (host) | Reverse-proxies `/api`, `/health` to backend |

Data persists in the `caberos-data` named volume (SQLite DB, secret key, workspaces, agent homes). To use Postgres instead, uncomment the `db` service and `AGENTOS_DATABASE_URL` in `docker-compose.yml`.

## Website

The public website is built with [Astro](https://astro.build) + [Starlight](https://starlight.astro.build).

- **Bilingual** — English and Vietnamese (`/vi/`) with full documentation in both languages
- **Animations** — scroll-triggered reveals, staggered hero entrance, and hover transitions
- **Deploy** — automatic on release tag via the release workflow, or manual via the "Deploy website" workflow in GitHub Actions

```bash
cd website
npm install
npm run dev      # Local dev server
npm run build    # Production build → dist/
```

## Project structure

```
foundation-agentos/
├── backend/
│   ├── src/agentos/          # FastAPI gateway + agent harness
│   │   ├── api/              # REST routes (19 routers — chat, agents, skills,
│   │   │                     #   knowledge, schedules, mcp, channels, …)
│   │   ├── capabilities/     # Tool registry + built-in tools (~35 capabilities)
│   │   ├── memory/           # Core MEMORY.md, episodic close, KG triples, recall
│   │   ├── skills/           # Resolution, reconcile, usage, importer, validation
│   │   ├── knowledge/        # Vault ingest/chunking/retrieval/embeddings
│   │   ├── services/         # Ledger, timelines, spend, lifecycle, captures
│   │   ├── browser/          # Managed browser runtime + CDP sessions
│   │   ├── mcp/              # MCP client (stdio/HTTP, credentials, OAuth)
│   │   ├── channels/         # External channels (Telegram, Discord, Zalo)
│   │   ├── sandbox/          # Process sandbox (seatbelt/bwrap/MXC/docker)
│   │   ├── syscall/          # The single boundary every capability crosses
│   │   ├── harness/          # Agent loop, context assembly, conversation reads
│   │   ├── reflection.py     # RSI skill-reflection pass (session close)
│   │   ├── defaults/         # Default agent YAMLs (caber, agent-builder)
│   │   └── ...
│   ├── tests/                # ~1,300 tests
│   ├── Dockerfile
│   └── pyproject.toml
├── frontend/
│   ├── src/
│   │   ├── pages/            # AgentList, Conversation, Skills, KnowledgeVault,
│   │   │                     #   Scheduler, Mcps, Channels, Observability,
│   │   │                     #   Traces, Notifications, ProvidersSettings
│   │   ├── components/       # ChatInputBar, PreviewPanel, RunTimeline,
│   │   │                     #   TraceInspector, SettingsOverlay, …
│   │   ├── lib/api.ts        # The only way the frontend talks to the backend
│   │   └── ...
│   ├── src-tauri/            # Tauri 2 desktop shell (Rust)
│   ├── Dockerfile
│   ├── nginx.conf
│   └── package.json
├── website/                  # Public website (Astro + Starlight, EN + VI)
├── skills/                   # 6 built-in skills
├── scripts/                  # dev, install, docker, release, build-gateway/dmg
├── sandbox/                  # Sandbox profiles (seatbelt SBPL, bwrap defaults)
├── docker-compose.yml
├── docs/                     # Specs, plans, TECHNICAL.md, PRODUCT.md
├── design-system/            # Design system docs (warm light, olive accent)
├── CONTEXT.md                # Shared vocabulary
├── AGENTS.md                 # Operating manual for AI agents
├── CONTRIBUTING.md
├── LICENSE
└── README.md
```

## Testing

### Backend

```bash
cd backend && uv run pytest -q

# Lint + format gate (CI parity)
uv run ruff check src/ tests/ && uv run ruff format --check src/ tests/

# With coverage
uv run pytest --cov=src/agentos --cov-report=term-missing
```

### Frontend

```bash
cd frontend

# Unit tests (vitest)
npm run test

# Type-check + build
npm run build

# Lint
npm run lint
```

### Smoke test (end-to-end, no real LLM)

```bash
cd backend && uv run python ../scripts/smoke.py test-agent "echo hello"
```

Uses a `ScriptedModel` double — no API key required. Tests the full pipeline: DB → harness → syscall → sandbox → audit.

### Frontend browser testing

Use the Playwright MCP server for real-browser testing. See `AGENTS.md` for details.

## Roadmap

### v0.1 (released)

- [x] Real-model chat, SSE streaming, files, sandbox, approvals, and elicitation
- [x] Agent/provider management, memory, skills, Knowledge Vault, and citations
- [x] Scheduler/heartbeat, MCP credentials/OAuth, and external channels
- [x] Observability, spend, Tauri desktop, Docker, and signed auto-update
- [x] Progressive capability discovery with run-scoped schema loading
- [x] Stable HITL, concurrent runs, SQLite resilience, and durable run lifecycle
- [x] Operator notifications, web extraction/pagination, and MCP runtime hardening

### v0.2.0 — Agent Workbench (integrated on `feat/v0.2.0`, release pending)

- [x] Artifact Studio — DOCX/PPTX/XLSX/PDF from structured specs; immutable revisions, restore, external-edit conflict handling
- [x] Workspace, composer, and chat previews for documents, slides, sheets, PDFs, media, and code
- [x] Clipboard image paste, drag/drop, and visual attachment previews
- [x] Browser automation — managed Chrome-for-Testing, headless/visible, isolated or opt-in persistent profiles, approvals, takeover
- [x] Skills Studio — three scopes, agent-assisted drafts, validation, imports, publish/promote/archive lifecycle, run pinning
- [x] RAG v2 — structured chunking, FTS default + optional hybrid, generations, egress consent, retrieval trace
- [x] Scheduler v2 — once/interval/cron, timezone/DST, missed-run, overlap, retry, heartbeat facade
- [x] Notifications v2 — in-app/browser/Tauri, deep links, dedupe, focus-aware read state
- [x] Background terminals — incremental output, ownership, cleanup
- [x] Observability v2 — unified `model_calls` ledger, projected timelines, platform spend, request captures
- [x] Runtime readiness — model catalog/pricing (models.dev snapshot), optional tools/runtimes with consent-gated managed installs
- [x] Context & memory v2 — bounded MEMORY.md publication, session-close learning, conversation summaries
- [x] RSI — session-close skill reflection runs (`trigger=reflection`), evidence-fingerprint dedupe, deferred retry
- [~] `/plan` mode — spec settled, **deferred** (see [docs/plans/v0.2/05-plan-mode.md](docs/plans/v0.2/05-plan-mode.md))
- [x] Frontend rework — redesigned workbench, "Today" home, shared UI primitives, guided tour + onboarding

See the detailed [`v0.2.0 release plan`](docs/plans/v0.2-release-plan.md).

### v0.2.1 — Connected Knowledge (planned)

- [ ] OneDrive and SharePoint file/folder Knowledge Sources
- [ ] Google Drive and Shared Drive file/folder Knowledge Sources
- [ ] Read-only OAuth, source browsing, and scheduled incremental snapshots
- [ ] Google Docs/Sheets/Slides export for local indexing
- [ ] Qdrant and configurable Retrieval Resources/Profiles
- [ ] Remote embedding privacy, cost, health, reconnect, and purge controls
- [ ] Structured sources: row-record layer for tabular data (xlsx/csv now, SQL later)

### v0.2.2 — Tasks and Event Automation (planned)

- [ ] Durable Tasks, assignment, dependencies, due dates, and completion evidence
- [ ] Task → Plan → Run → Artifact relationships
- [ ] Webhook, inbox, calendar, file-change, and connector event triggers
- [ ] Reusable approved automation templates
- [ ] Inline approval and elicitation through supported external channels

### Later

- [ ] Additional cloud-storage and retrieval adapters; pgvector after PostgreSQL support matures
- [ ] Persistent multi-agent Missions — coordinated agents, dependencies, budgets, approvals, and artifacts across runs
- [ ] Multi-operator support
- [ ] Agent marketplace and signed plugin SDK
- [ ] CLI/TUI only when it serves a concrete workflow
- [ ] Additional desktop platforms after sandbox behavior is verified

## Troubleshooting

### Desktop app: "Connecting to CaberOS" stuck

The gateway takes a few seconds to start. If it's stuck for more than 30 seconds:

```bash
# Check the gateway log
tail -f "$HOME/Library/Application Support/com.caberos.desktop/logs/gateway.log"

# Quit and relaunch
osascript -e 'tell application id "com.caberos.desktop" to quit'
open frontend/src-tauri/target/release/bundle/macos/CaberOS.app
```

### Desktop app: login doesn't work

The desktop app uses bearer-token auth (not cookies). If login fails:

1. Check the gateway log for `POST /api/auth/login` — should be `200`
2. Check for `GET /api/auth/me` — should be `200` after login
3. If login is `401`, the credentials are wrong (default: `admin` / `admin`)
4. If login is `200` but `/me` is `401`, clear localStorage in the webview and retry

### Docker: bwrap fails

Bubblewrap needs `SYS_ADMIN` capability. The compose file sets `cap_add: SYS_ADMIN`. If your Docker setup blocks this:

```yaml
# In docker-compose.yml, replace cap_add with:
privileged: true
```

### Backend: SSL certificate errors

On macOS with corporate firewalls, CaberOS uses the Homebrew CA bundle. If you hit SSL errors:

```bash
# Install ca-certificates via Homebrew
brew install ca-certificates

# Or set the path explicitly
export SSL_CERT_FILE=/opt/homebrew/etc/ca-certificates/cert.pem
export REQUESTS_CA_BUNDLE=/opt/homebrew/etc/ca-certificates/cert.pem
```

### Database locked

SQLite uses WAL mode. If you see "database is locked":

```bash
# Check for stale processes
lsof data/agentos.db

# Remove WAL/SHM files (safe, they'll be recreated)
rm -f data/agentos.db-wal data/agentos.db-shm
```

## Community

- **Issues:** [GitHub Issues](../../issues) for bugs and feature requests
- **Contributing:** See [CONTRIBUTING.md](CONTRIBUTING.md)
- **Technical reference:** [docs/TECHNICAL.md](docs/TECHNICAL.md) — architecture, data model, API surface
- **Product doc:** [docs/PRODUCT.md](docs/PRODUCT.md) — vision, personas, positioning
- **Agent operating manual:** [AGENTS.md](AGENTS.md)

## License

[MIT](LICENSE) — © 2025–2026 HoangPH25
