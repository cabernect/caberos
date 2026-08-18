# Contributing to CaberOS

Thanks for your interest in contributing! This guide covers everything you need to get started, from setup to pull request.

## Table of contents

- [Prerequisites](#prerequisites)
- [Setup](#setup)
- [Development workflow](#development-workflow)
- [Running the app](#running-the-app)
- [Checks before committing](#checks-before-committing)
- [Code style](#code-style)
- [Architecture overview](#architecture-overview)
- [Adding a new capability](#adding-a-new-capability)
- [Adding a new API route](#adding-a-new-api-route)
- [Adding a new frontend page](#adding-a-new-frontend-page)
- [Adding a new skill](#adding-a-new-skill)
- [Adding a new external channel](#adding-a-new-external-channel)
- [Testing](#testing)
- [Debugging](#debugging)
- [Pull request process](#pull-request-process)
- [Reporting bugs](#reporting-bugs)
- [License](#license)

## Prerequisites

| Tool | Version | Purpose |
|---|---|---|
| Python | 3.12+ | Backend runtime |
| [uv](https://docs.astral.sh/uv/) | latest | Python package manager |
| Node.js | 22+ | Frontend build |
| npm | 10+ | Frontend package manager |
| Rust | stable | Tauri desktop shell (optional) |
| macOS | 13+ | For `sandbox-exec` (built-in) |
| Linux | any modern | For `bubblewrap` (`apt install bubblewrap`) |

**macOS only:** Install [Homebrew](https://brew.sh/) and `ca-certificates` if you're behind a corporate firewall:

```bash
brew install ca-certificates
```

## Setup

```bash
# Clone
git clone <repo-url> && cd foundation-agentos

# Install backend + frontend dependencies
./scripts/install.sh

# Verify the backend starts
cd backend && uv run uvicorn agentos.main:app --port 8081 --reload
# → http://127.0.0.1:8081/health should return {"status":"ok"}

# Verify the frontend starts
cd frontend && npm run dev
# → http://localhost:5173
```

## Development workflow

1. **Create a branch** from `main`:
   ```bash
   git checkout -b feature/your-feature
   ```

2. **Read the relevant docs:**
   - `AGENTS.md` — full architecture reference, module layout, key decisions
   - `docs/spec-v0.1.md` — the 40-decision specification
   - `docs/plans/NN-*.md` — implementation plans with detailed specs
   - `.scratch/caberos-v0.1/issues/NN-*.md` — tracer-bullet tickets (gitignored — use GitHub Issues)

3. **Implement end-to-end** (vertical slice: DB + API + harness + sandbox + frontend)

4. **Run checks** (see below)

5. **Commit** with a clear message:
   ```bash
   git add -A
   git commit -m "Add X capability with approval flow and audit"
   ```

6. **Open a pull request** with a description of what changed and why

## Running the app

### Dev mode (backend + frontend)

```bash
./scripts/dev.sh
# Backend: http://127.0.0.1:8081
# Frontend: http://localhost:5173 (proxies /api to backend)
```

### Desktop dev mode (Tauri with hot reload)

```bash
cd frontend && npm run desktop:dev
```

### Docker

```bash
./scripts/docker.sh up
# → http://localhost:8080
```

### Smoke test (no real LLM needed)

```bash
cd backend && uv run python ../scripts/smoke.py test-agent "echo hello"
```

## Checks before committing

### Backend

```bash
cd backend

# Run all tests (348 tests)
uv run pytest -v

# Run a specific test file
uv run pytest tests/test_auth.py -v

# Run with coverage
uv run pytest --cov=src/agentos --cov-report=term-missing

# Lint
uv run ruff check src/ tests/
uv run ruff format --check src/ tests/

# Auto-fix lint issues
uv run ruff check --fix src/ tests/
uv run ruff format src/ tests/
```

### Frontend

```bash
cd frontend

# Type-check + build
npm run build

# Lint
npm run lint

# Auto-fix lint issues
npm run lint -- --fix
```

### Database migrations (Alembic)

```bash
cd backend

# Apply all migrations
uv run alembic upgrade head

# Check current revision
uv run alembic current

# Create a new migration
uv run alembic revision --autogenerate -m "Add new table"

# Mark existing DB as up-to-date (without running migrations)
uv run alembic stamp head
```

### Git whitespace check

```bash
git diff --check
```

## Code style

### Python

- **Formatter:** Ruff (enforced). Run `uv run ruff format src/ tests/` to auto-format.
- **Async everywhere:** All DB and I/O operations must be async. Use `async def`, `await`, `AsyncSession`.
- **Type hints:** Required on all function signatures.
- **Pydantic models:** Use Pydantic v2 for all config/schema models (`config_schema.py`).
- **SQLAlchemy 2.0 style:** Use `select()` statements, not legacy `Query`.
- **Error handling:** Handle errors at the right boundary. Not every line needs try/catch — look at existing patterns.
- **No secrets in code:** Provider keys are encrypted at rest (Fernet). Never log or commit secrets.
- **Comments:** Keep comments minimal. Prefer self-documenting code. Don't add/remove comments unless asked.

### TypeScript / React

- **Functional components only:** No class components.
- **Hooks:** Use React hooks (`useState`, `useEffect`, `useMemo`, etc.).
- **Tailwind CSS:** Use Tailwind utility classes for styling. CSS variables for theme tokens (`var(--color-background)`, etc.).
- **API access:** The frontend talks to the backend **only** through `frontend/src/lib/api.ts`. Never call `fetch()` directly in components.
- **Named exports:** Use named exports (`export function Login()`), not default exports (except for route components that React Router lazy-loads).
- **Path alias:** Use `@/` for imports from `src/` (e.g., `import { api } from "@/lib/api"`).

### Commits

- Clear, descriptive messages. Focus on "why" not just "what".
- No conventional-commit prefixes required (no `feat:`, `fix:`, etc.).
- Keep commits focused — one logical change per commit.
- Don't commit generated files (build artifacts, `.venv/`, `node_modules/`, `target/`).

### Git

- Never update git config.
- Never use `-i` flags (interactive mode).
- Don't push unless explicitly asked.
- Don't commit if no changes exist.

## Architecture overview

CaberOS is a monorepo with a Python backend and React frontend:

```
backend/src/agentos/
├── main.py              # FastAPI app entry (routers, CORS, lifespan)
├── config.py            # Settings (env vars, paths)
├── config_schema.py     # Pydantic models (AgentConfig, ModelConfig)
├── agent_service.py     # Agent CRUD, versioning, YAML import/export
├── auth.py              # Operator auth (cookie OR bearer token, bcrypt)
├── seed.py              # Seed default operator + capabilities + agents
├── pipeline.py          # 13-step execution pipeline (D19)
├── run_manager.py       # RunContext, active run registry
├── runner.py            # run_agent() — the single entry point
├── secret_store.py      # Fernet encryption for provider keys
├── db.py                # Async SQLAlchemy engine, init_db
├── api/                 # REST routes
│   ├── chat.py          # POST /message, SSE events, run management
│   ├── agents.py        # Agent CRUD, versions, rollback
│   ├── providers.py     # Provider CRUD, model discovery
│   ├── approvals.py     # Approval list/approve/reject
│   ├── elicitation.py   # Elicitation respond
│   ├── agent_files.py   # MEMORY.md, skills, workspace
│   ├── mcp.py           # MCP servers, credentials, OAuth, catalog
│   ├── channels.py      # External channel CRUD, webhooks
│   ├── observability.py # Runs, audit, spend, health
│   ├── scheduler.py     # Heartbeat config, fire, alerts
│   ├── settings.py      # YOLO mode toggle
│   └── skills.py        # System skill import/delete/promote
├── capabilities/        # Tool registry + built-in tools
├── memory/              # Three-layer memory
├── skills/              # Skill loader (menu → load → read resource)
├── mcp/                 # MCP client (stdio/HTTP, credentials, OAuth)
├── channels/            # External channels (Telegram, Discord, Zalo)
├── sandbox/             # Process sandbox (seatbelt/bwrap)
├── syscall/             # The single boundary every capability crosses
├── harness/             # Agent loop (Pydantic AI + LiteLLM adapter)
└── models/              # SQLAlchemy models (all v0.1 tables)
```

### Key patterns

- **SyscallHandler Protocol:** The harness depends on the `SyscallHandler` protocol, not a concrete impl. This lets us swap the stub (auto-approve) for the real mediator (approval flow) without touching the harness.
- **ScriptedModel:** Tests use a scripted model double — no API key, no real LLM.
- **Idempotent registry:** `CapabilityRegistry.register()` is idempotent — safe to call multiple times.
- **Workspace path validation:** All file operations go through `WorkspaceManager.validate_path()` which rejects paths that escape the workspace via `..` or absolute paths.
- **Bearer-token auth:** The backend accepts the session token from either the `agentos_session` cookie or the `Authorization: Bearer` header. The desktop app uses the header; the browser dev mode uses the cookie.

See `AGENTS.md` for the complete reference.

## Adding a new capability

1. **Create the tool** in `backend/src/agentos/capabilities/tools/your_tool.py`:

```python
from .base import Capability, CapabilityResult

async def your_tool(args: dict, context) -> CapabilityResult:
    # Implement the tool logic
    result = do_something(args["param"])
    return CapabilityResult(success=True, output=result)

# Register in capabilities/builtin.py:
# registry.register(CapabilityDef(
#     name="your_tool",
#     kind="tool",
#     description="Does something useful",
#     egress=False,           # True if it makes network calls
#     require_approval=False,  # True if it needs operator approval
#     handler=your_tool,
#     parameters_schema={...},
# ))
```

2. **Seed it:** The capability is auto-seeded from the runtime registry on startup (`seed.py`).

3. **Test it:** Add a test in `backend/tests/test_tools_new.py`.

4. **Frontend:** Tool calls are automatically rendered by `ToolCallBlock.tsx` — no frontend changes needed unless the tool has special UI needs.

## Adding a new API route

1. **Create or extend a router** in `backend/src/agentos/api/your_router.py`:

```python
from fastapi import APIRouter, Depends
from ..auth import require_operator
from ..models.operator import Operator

router = APIRouter(prefix="/api/your-feature", tags=["your-feature"])

@router.get("")
async def list_items(operator: Operator = Depends(require_operator)):
    # ...
    return {"items": []}
```

2. **Register the router** in `backend/src/agentos/main.py`:

```python
from .api import your_router
app.include_router(your_router.router)
```

3. **Add the frontend API call** in `frontend/src/lib/api.ts`:

```typescript
listItems: () => request<{ items: any[] }>("/api/your-feature"),
```

4. **Add the type** in `frontend/src/lib/types.ts` if needed.

5. **Test it:** Add a backend test and verify the frontend type-checks.

## Adding a new frontend page

1. **Create the page** in `frontend/src/pages/YourPage.tsx`:

```tsx
import { api } from "@/lib/api";

export function YourPage() {
  // Use api.xxx() to fetch data
  return <div>...</div>;
}
```

2. **Add the route** in `frontend/src/App.tsx`:

```tsx
<Route path="/your-page" element={authed ? <YourPage /> : <Navigate to="/login" />} />
```

3. **Add navigation** in the sidebar (if applicable).

4. **Type-check:** `cd frontend && npm run build`

## Adding a new skill

1. **Create the skill directory** in `skills/your-skill/`:

```
skills/your-skill/
├── SKILL.md          # Skill content (loaded when the agent calls skills_load)
└── resources/        # Optional resource files (read via skills_read_resource)
```

2. **SKILL.md format:**

```markdown
# Your Skill Name

Description of what this skill does and when to use it.

## Instructions

Step-by-step guidance for the agent...
```

3. **No registration needed** — the skill loader discovers skills by scanning the skills directory.

4. **Test it:** Start the app, create an agent, and verify `skills_list` shows your skill.

## Adding a new external channel

1. **Create the channel** in `backend/src/agentos/channels/your_channel.py`:

```python
from .base import Channel, OutboundMessage, OutputConstraints

class YourChannel(Channel):
    platform = "your_platform"

    async def start(self): ...
    async def stop(self): ...
    async def send(self, msg: OutboundMessage): ...
    async def receive(self) -> list: ...
```

2. **Register it** in `backend/src/agentos/channels/registry.py`.

3. **Add the API routes** in `backend/src/agentos/api/channels.py` if needed.

4. **Add tests** in `backend/tests/`.

5. **Frontend:** The Channels page auto-discovers channels from the API.

## Testing

### Backend tests

The backend has 348 tests covering auth, pipeline, tools, memory, MCP, channels, observability, and more.

```bash
cd backend

# All tests
uv run pytest -v

# Specific file
uv run pytest tests/test_auth.py -v

# Specific test
uv run pytest tests/test_auth.py::TestAuth::test_login_correct -v

# With coverage
uv run pytest --cov=src/agentos --cov-report=term-missing

# Only run tests that match a pattern
uv run pytest -k "auth" -v
```

### Test patterns

- **ScriptedModel:** Tests that need an agent use `ScriptedModel` — a scripted model double that returns predetermined responses. No API key needed.
- **AsyncDB fixtures:** Tests use an in-memory or temp-file SQLite database with `db_engine` fixture.
- **HTTP client:** Tests use `httpx.AsyncClient` with `ASGITransport` for API tests.

### Frontend tests

```bash
cd frontend

# Type-check + build
npm run build

# Lint
npm run lint
```

For real-browser testing, use the Playwright MCP server (see `AGENTS.md`).

### Smoke test

```bash
cd backend && uv run python ../scripts/smoke.py test-agent "echo hello"
```

This runs the full pipeline with a `ScriptedModel` — DB → harness → syscall → sandbox → audit. No API key required.

## Debugging

### Backend debugging

```bash
# Start with auto-reload
cd backend && uv run uvicorn agentos.main:app --port 8081 --reload

# Enable debug logging
AGENTOS_LOG_LEVEL=debug uv run uvicorn agentos.main:app --port 8081 --reload

# Check the DB directly
sqlite3 backend/data/agentos.db "SELECT id, name FROM agents;"

# Check the gateway log (desktop)
tail -f "$HOME/Library/Application Support/com.caberos.desktop/logs/gateway.log"
```

### Frontend debugging

```bash
cd frontend && npm run dev
# Open http://localhost:5173 — Vite shows errors in the browser console
```

### Common issues

- **"database is locked"** — Another process is using the DB. Check `lsof data/agentos.db`. Remove WAL/SHM files if stale: `rm -f data/agentos.db-wal data/agentos.db-shm`
- **SSL errors on macOS** — Install `ca-certificates` via Homebrew, or set `SSL_CERT_FILE` env var.
- **Port 8081 already in use** — `lsof -i :8081` to find the process, then kill it.
- **Desktop app blank screen** — Check the gateway log. The gateway may have failed to start.

## Pull request process

1. **Before opening a PR:**
   - All tests pass (`uv run pytest -v`)
   - Lint passes (`ruff check` + `ruff format --check`)
   - Frontend builds (`npm run build`)
   - `git diff --check` is clean (no whitespace errors)

2. **PR description should include:**
   - Summary of changes (bullet points)
   - Why the change was made
   - Test plan (what you tested and how)

3. **Keep diffs minimal and focused.** One logical change per PR.

4. **Update `AGENTS.md`** if you:
   - Add a new module or directory
   - Add a new pattern or convention
   - Change the architecture
   - Add a new env var or config option

5. **Don't commit:**
   - Secrets (`.env`, `.key`, credentials)
   - Build artifacts (`__pycache__/`, `node_modules/`, `dist/`, `target/`)
   - Generated files (`.db`, `.db-wal`, `.db-shm`)

## Reporting bugs

Open a GitHub issue with:

1. **Steps to reproduce** — exact commands or UI actions
2. **Expected behavior** — what you thought would happen
3. **Actual behavior** — what actually happened
4. **Logs:**
   - Backend: stdout from `uvicorn`
   - Desktop: `tail -100 "$HOME/Library/Application Support/com.caberos.desktop/logs/gateway.log"`
   - Frontend: browser console output
5. **Environment:**
   - OS (macOS/Linux, version)
   - CaberOS version (`git describe --tags` or commit hash)
   - Python version, Node version
   - Docker version (if using Docker)

## License

By contributing, you agree that your contributions are licensed under the [MIT License](LICENSE).
