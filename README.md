# CaberOS

<p align="center">
  <strong>Local-first AI Agent Operating System</strong>
</p>

<p align="center">
  <a href="#features">Features</a> ·
  <a href="#quick-start">Quick Start</a> ·
  <a href="#architecture">Architecture</a> ·
  <a href="#configuration">Configuration</a> ·
  <a href="#default-agents">Default Agents</a> ·
  <a href="#skills">Skills</a> ·
  <a href="#external-channels">Channels</a> ·
  <a href="#observability">Observability</a> ·
  <a href="#desktop-app">Desktop</a> ·
  <a href="#docker">Docker</a> ·
  <a href="#roadmap">Roadmap</a> ·
  <a href="CONTRIBUTING.md">Contributing</a>
</p>

---

CaberOS is an open-source, local-first AI Agent Operating System. It hosts personal agents on your machine, gives them a workspace, connects them to your services, and lets them run shell commands in a sandbox. The OS supplies the harness, mediates every capability call, and gives you a dashboard to manage your agents.

**Your data never leaves your machine.** Providers (OpenAI, Anthropic, Google, Ollama, OpenRouter) are just transports — CaberOS owns the agent, the memory, the workspace, and the audit trail.

## Why "OS"?

An operating system's job is identity, permissions, resource accounting, mediated access to resources, and audit — for processes. CaberOS does the same job for agents. Every capability call crosses a single boundary (the **syscall layer**) which resolves who the caller is, checks permission, injects credentials, executes, and writes an audit record.

Adding a new integration (Notion, GitHub, Slack) is a new capability, not a new subsystem. The design doesn't change.

## Features

### Core

- **Real model chat** — streaming SSE, multi-provider support (OpenAI, Anthropic, Google, Ollama, OpenRouter), thinking/reasoning controls with per-message effort adjustment
- **Tool use** — file read/write/search, shell (sandboxed), web search/fetch, sub-agents, datetime, skills
- **Approval flow** — every egress capability (shell, web) requires operator approval; decisions can be remembered per-scope (exact, same-verb, pattern, capability)
- **Elicitation** — agents ask clarifying questions via `agent_ask_user`; the dashboard shows a prompt bar
- **Guardrails** — input/output secret redaction, prompt-injection detection, system-prompt leakage prevention

### Agent management

- **Versioned configs** — soul, persona, task, model, capabilities, limits are DB rows with full version history
- **YAML import/export** — share agent configs as YAML files
- **Rollback** — revert to any previous agent version
- **Duplicate** — clone an agent with a new ID

### Memory

Three layers (D34):

- **Working memory** — session-scoped conversation snippets, cleared after promotion
- **MEMORY.md** — agent-scoped living document, always loaded, protected from compaction
- **Knowledge graph** — SQLite triples (entity/predicate/object), queried per-contact
- **Auto-extraction** — post-run promotion of durable facts from working memory to KG
- **Semantic recall** — FTS5 (SQLite) or tsvector (Postgres) for past-session retrieval

### Skills

- **Opt-in, not auto-injected** — the agent sees a menu of skill names + descriptions and chooses which to load
- **System skills** — 16 built-in skills (PDF, DOCX, XLSX, PPTX, web artifacts, frontend design, etc.)
- **Per-agent skills** — promote system skills to individual agents
- **Skill resources** — agents can read resource files from within a skill directory

### MCP integration

- **MCP client** — stdio and HTTP transports
- **Server registry** — CRUD for MCP servers, tool discovery, agent bindings
- **Credentials** — encrypted at rest (Fernet), injected via env/headers at runtime
- **OAuth** — loopback flow with token refresh and revoke
- **Catalog** — marketplace of installable MCP servers

### External channels

Four channels route external messages through the same agent pipeline:

- **Telegram** — polling + webhook, typing indicator, 4096-char split, Markdown
- **Discord** — slash commands + message create + DM, 2000-char split, Markdown
- **Zalo OA** — webhook, HMAC-SHA256 verification, `cs` message type
- **Zalo Bot Platform** — polling + webhook, typing indicator, 2000-char split

### Observability

- **Run history** — filterable list with status, trigger, agent, cost, duration
- **Run detail** — full message history + audit records inline
- **Syscall log** — every capability call with allowed/denied, arguments, result
- **Spend tracking** — today / 7-day / 30-day breakdown by agent and trigger
- **Health dashboard** — provider status, MCP connectivity, channel status
- **Operator audit** — login, password changes, settings changes

### Scheduler

- **Heartbeat mode** — agents run on a configurable interval (every N minutes/hours)
- **Alerts** — failed heartbeats surface in the dashboard
- **Manual fire** — trigger a heartbeat run on demand

## Quick start

### Option 1: Docker (easiest)

```bash
git clone <repo-url> && cd foundation-agentos
./scripts/docker.sh up
# → http://localhost:8080
# Login: admin / admin
```

The first launch seeds the default operator and two agents (Caber, AgentBuilder). Data persists in a named Docker volume.

### Option 2: Local dev

**Prerequisites:** Python 3.12+, [uv](https://docs.astral.sh/uv/), Node 22+, npm, and either macOS (uses built-in `sandbox-exec`) or Linux (`bubblewrap`).

```bash
git clone <repo-url> && cd foundation-agentos

# Install backend + frontend dependencies
./scripts/install.sh

# Start both servers (backend :8081, frontend :5173)
./scripts/dev.sh
```

Open `http://localhost:5173` — the Vite dev server proxies `/api` to the backend.

### Option 3: Desktop app (macOS)

```bash
# Build the Tauri app (bundles the PyInstaller gateway + React frontend)
cd frontend && npm run desktop:build

# Launch
open frontend/src-tauri/target/release/bundle/macos/CaberOS.app
```

The desktop app packages the entire backend as a PyInstaller executable and supervises it. No Python installation required. Gateway logs are at:

```bash
tail -f "$HOME/Library/Application Support/com.caberos.desktop/logs/gateway.log"
```

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
│  ┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐ ┌──────────┐  │
│  │ Chat │ │Agents│ │ MCP  │ │Obsv. │ │ Channels │  │
│  └──┬───┘ └──────┘ └──────┘ └──────┘ └──────────┘  │
└─────┼───────────────────────────────────────────────┘
      ▼
┌─────────────────────────────────────────────────────┐
│  Agent Pipeline (13-step, D19)                      │
│  ┌──────────────────────────────────────────────┐   │
│  │  Harness (Pydantic AI)                       │   │
│  │  ┌─────────────┐  ┌──────────────────────┐   │   │
│  │  │ Model       │  │ SyscallHandler       │   │   │
│  │  │ (LiteLLM)   │  │ ┌──────────────────┐ │   │   │
│  │  │             │  │ │ Approval gate    │ │   │   │
│  │  │             │  │ │ Capabilities     │ │   │   │
│  │  │             │  │ │ Sandbox (bwrap)  │ │   │   │
│  │  │             │  │ │ Audit log        │ │   │   │
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
| Agent harness | Pydantic AI |
| Model transport | LiteLLM |
| Frontend | React 19, Vite, TypeScript, Tailwind CSS 4 |
| Desktop | Tauri 2 (Rust) |
| Sandbox | macOS `sandbox-exec` / Linux `bubblewrap` |
| Packaging | PyInstaller (gateway), Tauri bundler (desktop) |

### Key design decisions

- **D1:** Agents are configuration, not code. AgentConfig is a DB row, versioned.
- **D2:** Pydantic AI is the harness. LiteLLM is the model transport.
- **D33:** FastAPI is the gateway/API layer. The React dashboard, Tauri desktop, and future CLI are all clients of the same REST + SSE contracts.
- **D34:** Three-layer memory: working memory (session), MEMORY.md (file), knowledge graph (SQLite triples).
- **D35:** Agent identity = soul, persona, task — versioned config fields, NOT workspace files.
- **D38:** MCP tools in v0.1. CLI/TUI deferred to v0.2.

See `docs/spec-v0.1.md` for the full 40-decision specification.

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

**16 built-in skills:**

| Skill | Description |
|---|---|
| `algorithmic-art` | Algorithmic art generation |
| `brand-guidelines` | Brand guideline application |
| `canvas-design` | Canvas-based design |
| `claude-api` | Claude API usage patterns |
| `doc-coauthoring` | Document co-authoring |
| `docx` | Word document processing |
| `frontend-design` | Frontend UI design |
| `internal-comms` | Internal communications |
| `mcp-builder` | MCP server building |
| `pdf` | PDF processing |
| `pptx` | PowerPoint processing |
| `skill-creator` | Create new skills |
| `slack-gif-creator` | Slack GIF creation |
| `theme-factory` | Theme generation |
| `web-artifacts-builder` | Web artifact building |
| `webapp-testing` | Web app testing |
| `xlsx` | Excel processing |

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

- **Runs page** — filter by agent, status, trigger (chat/heartbeat/channel/test). Click any run to see the full message history and audit records inline.
- **Syscall log** — every capability call with timestamp, agent, capability name, arguments (redacted), result, allowed/denied. Denied calls highlighted.
- **Spend** — today / 7-day / 30-day breakdown by agent and trigger. Tracks input/output tokens and cost per run.
- **Health** — provider connectivity, MCP server status, channel status.
- **Operator audit** — logins, password changes, YOLO mode toggles.

## Desktop app

The Tauri 2 desktop app packages the entire stack into a native macOS application:

- **PyInstaller gateway** — the FastAPI backend is compiled to a standalone executable, no Python needed
- **Process-group supervision** — the Tauri shell starts the gateway in its own process group and kills it cleanly on exit
- **Bearer-token auth** — the desktop webview uses `Authorization: Bearer` headers instead of cookies (avoids cross-site cookie issues between `tauri.localhost` and `127.0.0.1`)
- **Persistent logs** — gateway stdout/stderr written to `~/Library/Application Support/com.caberos.desktop/logs/gateway.log`
- **Default agents** — `caber` and `agent-builder` seed on first launch from YAML bundled into the executable

```bash
# Build
cd frontend && npm run desktop:build

# DMG (optional)
npm run desktop:build:dmg

# Dev mode (hot reload)
npm run desktop:dev
```

## Docker

The Docker setup runs the full stack: backend (Python + uv + bwrap) and frontend (nginx reverse proxy).

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
| `backend` | `python:3.12-slim` + uv | 8081 (internal) | bwrap needs `SYS_ADMIN` cap |
| `frontend` | `nginx:alpine` | 80 → `:8080` (host) | Reverse-proxies `/api`, `/health` to backend |

Data persists in the `caberos-data` named volume (SQLite DB, secret key, workspaces, agent homes). To use Postgres instead, uncomment the `db` service and `AGENTOS_DATABASE_URL` in `docker-compose.yml`.

## Project structure

```
foundation-agentos/
├── backend/
│   ├── src/agentos/          # FastAPI gateway + agent harness
│   │   ├── api/              # REST routes (chat, agents, mcp, channels, observability)
│   │   ├── capabilities/     # Tool registry + built-in tools
│   │   ├── memory/           # Three-layer memory (notebook, triples, recall, auto-extract)
│   │   ├── skills/           # Skill loader (menu → load → read resource)
│   │   ├── mcp/              # MCP client (stdio/HTTP, credentials, OAuth)
│   │   ├── channels/         # External channels (Telegram, Discord, Zalo)
│   │   ├── sandbox/          # Process sandbox (seatbelt/bwrap)
│   │   ├── syscall/          # The single boundary every capability crosses
│   │   ├── harness/          # Agent loop (Pydantic AI + LiteLLM)
│   │   ├── defaults/         # Default agent YAMLs (caber, agent-builder)
│   │   └── ...
│   ├── tests/                # 348 tests
│   ├── Dockerfile
│   └── pyproject.toml
├── frontend/
│   ├── src/
│   │   ├── pages/            # AgentList, Conversation, Providers, MCP, Channels, Observability...
│   │   ├── components/       # ModelSelector, ToolCallBlock, SettingsOverlay...
│   │   ├── lib/api.ts        # The only way the frontend talks to the backend
│   │   └── ...
│   ├── src-tauri/            # Tauri 2 desktop shell (Rust)
│   ├── Dockerfile
│   ├── nginx.conf
│   └── package.json
├── skills/                   # 16 system-level skills
├── scripts/                  # dev, install, docker, build-gateway, build-dmg, desktop-dev
├── sandbox/                  # Sandbox profiles (seatbelt SBPL, bwrap defaults)
├── docker-compose.yml
├── docs/                     # Spec + implementation plans
├── design-system/            # Design system docs (warm light, olive accent)
├── AGENTS.md                 # Full architecture reference for AI agents
├── CONTRIBUTING.md
├── LICENSE
└── README.md
```

## Testing

### Backend (348 tests)

```bash
cd backend && uv run pytest -v

# Specific module
uv run pytest tests/test_auth.py -v

# With coverage
uv run pytest --cov=src/agentos --cov-report=term-missing
```

### Frontend

```bash
cd frontend

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

### v0.1 (current)

- [x] Smoke test vertical slice
- [x] Dashboard chat with real models
- [x] File operations + tool call visibility
- [x] Approval flow + elicitation
- [x] Agent management UI
- [x] Global settings & provider management
- [x] Memory + skills
- [x] Scheduler/heartbeat
- [x] MCP client infrastructure + credentials/OAuth
- [x] External channels (Telegram, Discord, Zalo)
- [x] Observability + spend
- [x] Tauri desktop app
- [x] Docker support
- [ ] Testing hardening (Ticket 11)

### v0.2 (planned)

- [ ] CLI/TUI (`caber` command)
- [ ] CaberCore extraction (headless runtime, separate from FastAPI)
- [ ] Cron/event triggers for scheduler
- [ ] More MCP catalog entries

### v0.5+

- [ ] Postgres migration tooling (Alembic)
- [ ] Multi-operator support
- [ ] Agent marketplace
- [ ] Plugin SDK

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
- **Architecture reference:** See [AGENTS.md](AGENTS.md) for the full module layout, key decisions, and patterns

## License

[MIT](LICENSE) — © 2025 HoangPH25
