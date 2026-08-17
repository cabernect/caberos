# CaberOS

**Local-first AI Agent Operating System**

CaberOS hosts personal agents on your machine, gives them a workspace, connects them to your services, and lets them run shell commands in a sandbox. The OS supplies the harness, mediates every capability call, and gives you a dashboard to manage your agents.

## Features

- **Real model chat** — streaming SSE, multi-provider (OpenAI, Anthropic, Google, Ollama, OpenRouter), thinking/reasoning controls
- **Tool use** — file ops, shell (sandboxed), web search/fetch, sub-agents, datetime
- **Approval flow** — every egress capability requires operator approval; remember decisions per-scope
- **Agent management** — versioned configs (soul/persona/task), YAML import/export, rollback
- **Memory** — three layers: working memory (session), MEMORY.md (agent-scoped file), knowledge graph (SQLite triples)
- **Skills** — opt-in skill loading (not auto-injected); agent sees a menu and chooses
- **MCP integration** — stdio/HTTP MCP client, credential custody, OAuth, catalog marketplace
- **External channels** — Telegram, Discord, Zalo OA, Zalo Bot Platform
- **Observability** — run history, syscall audit log, spend tracking, health dashboard
- **Scheduler** — heartbeat mode (cron/event triggers deferred to v0.5)
- **Desktop app** — Tauri 2 native shell with packaged gateway
- **Docker** — full stack via docker-compose

## Quick start

### Docker (easiest)

```bash
./scripts/docker.sh up
# → http://localhost:8080
# Login: admin / admin
```

### Local dev

```bash
# Prerequisites: Python 3.12+, uv, Node 22+, npm, macOS (sandbox-exec) or Linux (bwrap)

# Install dependencies
./scripts/install.sh

# Start backend + frontend dev servers
./scripts/dev.sh
# Backend: http://127.0.0.1:8081
# Frontend: http://localhost:5173
```

### Desktop app (macOS)

```bash
cd frontend && npm run desktop:build
open frontend/src-tauri/target/release/bundle/macos/CaberOS.app
```

## Architecture

```
Browser / Desktop (Tauri) / External Channels
                    ↓
            FastAPI Gateway (REST + SSE)
                    ↓
         Agent Pipeline (13-step, D19)
                    ↓
              Harness (Pydantic AI)
                    ↓
          Model (LiteLLM transport)
                    ↓
         SyscallHandler (mediator)
           → Approval gate
           → Capabilities (tools)
           → Sandbox (bwrap / sandbox-exec)
```

**Stack:** Python 3.12, FastAPI, SQLAlchemy 2.0 async, SQLite (WAL + FTS5), React 19, Vite, Tailwind, Tauri 2.

## Default agents

On first launch, CaberOS seeds two agents:

- **Caber** — your personal agent. General-purpose, all tools enabled.
- **AgentBuilder** — a meta-agent that helps you design and create new agents.

## Configuration

All settings are env vars with the `AGENTOS_` prefix (see `backend/src/agentos/config.py`):

| Env var | Default | Description |
|---|---|---|
| `AGENTOS_DATABASE_URL` | empty (SQLite) | Postgres: `postgresql+asyncpg://user:pass@host/db` |
| `AGENTOS_DB_PATH` | `data/agentos.db` | SQLite database path |
| `AGENTOS_WORKSPACE_ROOT` | `data/workspaces` | Agent workspace directory |
| `AGENTOS_AGENT_HOME_ROOT` | `~/agentos/agents` | Agent home (MEMORY.md) |
| `AGENTOS_SKILLS_DIR` | `../skills` | System-level skills directory |
| `AGENTOS_CONTROL_PLANE_HOST` | `127.0.0.1` | API server bind host |
| `AGENTOS_CONTROL_PLANE_PORT` | `8081` | API server port |
| `AGENTOS_YOLO_MODE` | `false` | Skip all approval gates |
| `AGENTOS_HITL_TIMEOUT` | `300` | Approval timeout (seconds) |

## License

MIT — see [LICENSE](LICENSE).
