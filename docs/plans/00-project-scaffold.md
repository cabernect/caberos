# 00 — Project Scaffold

## Goal

Set up the monorepo structure, Python project, frontend skeleton, and dev scripts so every other plan has a place to put code. No Docker required for v0.1 — the sandbox uses the OS's native process-level sandboxing (sandbox-exec on macOS, bwrap on Linux).

## Spec references

- **D3** — Python and FastAPI, one daemon
- **D4** — Two planes, two sockets (loopback control plane)
- **D5** — SQLite (WAL) via SQLAlchemy
- **D28** — Process-level sandbox (sandbox-exec / bwrap), no container runtime
- **D33** — The Gateway is a headless daemon; the frontend is one client of many
- **Tech Stack** — uv, FastAPI, React 19 + Vite, shadcn/ui

## Dependencies

None. This is the first plan.

## Tasks

### 1. Create monorepo structure

```
foundation-agentos/
├── backend/
│   ├── pyproject.toml
│   ├── src/
│   │   └── agentos/
│   │       ├── __init__.py
│   │       ├── main.py            # FastAPI app entry point
│   │       ├── config.py          # Settings (pydantic-settings)
│   │       └── ...
│   ├── alembic/
│   │   ├── alembic.ini
│   │   └── versions/
│   └── tests/
├── frontend/
│   ├── package.json
│   ├── vite.config.ts
│   ├── tsconfig.json
│   ├── src/
│   │   ├── main.tsx
│   │   ├── App.tsx
│   │   └── ...
│   └── index.html
├── sandbox/
│   ├── seatbelt_profile.sb        # Template SBPL profile (macOS)
│   └── bwrap_defaults.sh          # Template bwrap invocation (Linux)
├── scripts/
│   ├── dev.sh                     # Start backend + frontend in dev mode
│   └── install.sh                 # Check deps, set up env
├── docs/
│   ├── spec-v0.1.md
│   └── plans/
└── docker-compose.yml             # Optional: prod packaging (backend + frontend only)
```

Note: `docker-compose.yml` is optional and only for prod packaging of the app itself (backend + frontend). The sandbox does **not** use Docker — it uses the OS's native process-level sandboxing. See plan 06.

### 2. Initialize Python project with uv

```bash
cd backend
uv init --python 3.12
uv add fastapi uvicorn[standard] sqlalchemy[asyncio] aiosqlite alembic
uv add pydantic pydantic-settings pydantic-ai litellm
uv add cryptography httpx
uv add --dev pytest pytest-asyncio pytest-cov ruff pyright
```

Configure `pyproject.toml`:
- `[tool.ruff]` — line length 100, target Python 3.12
- `[tool.pyright]` — strict mode, venv path
- `[tool.pytest.ini_options]` — `asyncio_mode = "auto"`, `testpaths = ["tests"]`

### 2b. Set up test infrastructure

`backend/tests/conftest.py`:
- Fixture for async DB session (in-memory SQLite via `aiosqlite`)
- Fixture for test client (FastAPI `TestClient` / `httpx.AsyncClient`)
- `scripted_model` double for the harness — a fake model client that returns scripted tool calls / final answers, used by plan 03's harness tests

`backend/tests/__init__.py`:
- Empty file marking the tests directory as a package

### 3. Initialize frontend with Vite + React

```bash
cd frontend
npm create vite@latest . -- --template react-ts
npm install
npm install -D tailwindcss @tailwindcss/vite
npx shadcn@latest init
npm install @tanstack/react-query
```

Configure:
- `vite.config.ts` — proxy `/api` to `http://localhost:8081` (control plane)
- `tailwind.config.js` — shadcn/ui theme
- `src/lib/api.ts` — TanStack Query client setup

### 4. Create FastAPI app skeleton

`backend/src/agentos/main.py`:
- Two FastAPI apps (or one app, two routers): control plane on `127.0.0.1:8081`, data plane on `0.0.0.0:8080`
- Control plane: `/api/*` routes (placeholder)
- Data plane: `/webhooks/*` routes (placeholder)
- Health check on both

`backend/src/agentos/config.py`:
- Pydantic Settings: DB path, secret key, sandbox backend, model defaults
- Load from env vars + `.env` file

### 5. Create sandbox profile templates

`sandbox/seatbelt_profile.sb`:
- Template SBPL profile for macOS sandbox-exec
- Deny all file access by default
- Allow read/write to workspace (parameterized)
- Deny network by default
- Allow process execution from system paths

`sandbox/bwrap_defaults.sh`:
- Template bwrap invocation for Linux
- `--unshare-all`, `--bind {workspace} /workspace`, `--ro-bind` for system paths
- Network isolation unless explicitly allowed

### 6. Create dev script

`scripts/dev.sh`:
- Check `sandbox-exec` (macOS) or `bwrap` (Linux) is available
- Start backend with `uv run uvicorn agentos.main:app --reload --port 8081`
- Start frontend with `npm run dev`
- Trap exits to clean up

### 7. Create install script

`scripts/install.sh`:
- Check Python 3.12, uv, Node.js are installed
- Check sandbox tool: `sandbox-exec` on macOS, `bwrap` on Linux/WSL2
- On native Windows: print message directing to WSL2
- Run `uv sync` in backend
- Run `npm install` in frontend
- Create `data/` and `workspaces/` directories
- Print next steps

### 8. Create optional Docker Compose (prod packaging only)

`docker-compose.yml` (optional, for prod packaging of the app):
- `backend` service: Python app on 8081
- `frontend` service: built React app served by nginx on 3000
- Volumes: `./data` for SQLite, `./workspaces` for agent workspaces
- No sandbox service — the sandbox runs via the OS native primitive inside the backend container's host (or the container must use a base image with sandbox-exec/bwrap available)

Note: Docker Compose is optional for v0.1. The primary dev path is `scripts/dev.sh` running natively. Docker packaging is a convenience for deployment, not a requirement.

## Files to create

- `backend/pyproject.toml`
- `backend/src/agentos/__init__.py`
- `backend/src/agentos/main.py`
- `backend/src/agentos/config.py`
- `backend/alembic.ini`
- `frontend/package.json`
- `frontend/vite.config.ts`
- `frontend/src/main.tsx`
- `frontend/src/App.tsx`
- `sandbox/seatbelt_profile.sb`
- `sandbox/bwrap_defaults.sh`
- `docker-compose.yml` (optional)
- `scripts/dev.sh`
- `scripts/install.sh`
- `scripts/smoke.py`  # referenced by plan 07
- `backend/tests/__init__.py`
- `backend/tests/conftest.py`

## Verification

- `scripts/install.sh` runs without errors
- `scripts/install.sh` detects the correct sandbox tool for the platform
- `scripts/dev.sh` starts backend on :8081 and frontend on :5173
- `curl http://localhost:8081/health` returns 200
- `curl http://localhost:5173` returns the React app
- `sandbox-exec -p "(version 1) (deny file-write* (subpath \"/\")) (allow file-write* (subpath \"/tmp\"))" -- /bin/sh -c "echo ok"` works on macOS
- `uv run ruff check` passes
- `uv run pyright` passes
- `uv run pytest` runs with no tests collected (0 errors)

## Cross-references

- Plan 06 — Sandbox
- Plan 07 — Pipeline (new)
- Plan 08 — Channels (was plan 09)
- Plan 09 — Observability (was plan 12)
- Plan 10 — Connectors (was plan 07)
- Plan 11 — Memory (was plan 08)
- Plan 12 — Control plane (was plan 10)
- Plan 13 — Dashboard (was plan 11)
- Plan 14 — Testing (was plan 13)
