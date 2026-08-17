# Contributing to CaberOS

Thanks for your interest in contributing! This guide covers the basics.

## Prerequisites

- **Python 3.12+** with [uv](https://docs.astral.sh/uv/)
- **Node 22+** with npm
- **macOS** (uses built-in `sandbox-exec`) or **Linux** (uses `bubblewrap`)

## Setup

```bash
git clone <repo-url> && cd foundation-agentos
./scripts/install.sh        # installs backend + frontend dependencies
./scripts/dev.sh            # starts backend (:8081) + frontend (:5173)
```

## Development workflow

1. Create a branch: `git checkout -b feature/your-feature`
2. Make your changes
3. Run checks (see below)
4. Commit with a clear message
5. Open a pull request

## Checks before committing

### Backend

```bash
cd backend

# Tests
uv run pytest -v

# Lint
uv run ruff check src/ tests/
uv run ruff format --check src/ tests/

# Type-check (if using mypy/pyright)
# uv run mypy src/
```

### Frontend

```bash
cd frontend

# Build (includes tsc type-check)
npm run build

# Lint
npm run lint
```

### Smoke test (end-to-end, no real LLM)

```bash
cd backend && uv run python ../scripts/smoke.py test-agent "echo hello"
```

## Code style

- **Python:** Follow existing patterns. Ruff enforces formatting. Use async for all DB and I/O operations.
- **TypeScript/React:** Functional components, hooks. Tailwind for styling. No default exports except for route components.
- **Commits:** Clear, descriptive messages. No conventional-commit prefixes required.
- **No secrets in code:** Provider keys and credentials are encrypted at rest (Fernet). Never commit `.env`, `.key`, or credential files.

## Architecture notes

- The backend is a single FastAPI daemon (`agentos.main:app`).
- All capability calls cross the `SyscallHandler` boundary (approval, audit, sandbox).
- Agents are configuration, not code — `AgentConfig` is a versioned DB row.
- The frontend talks to the backend exclusively via `frontend/src/lib/api.ts`.
- The Tauri desktop app packages the backend as a PyInstaller executable and supervises it.

See `AGENTS.md` for the full architecture reference, module layout, and key decisions.

## Pull requests

- Keep diffs minimal and focused
- Include tests for new functionality
- Update `AGENTS.md` if you add a new module, pattern, or convention
- Ensure all checks pass before requesting review

## Reporting bugs

Open a GitHub issue with:

1. Steps to reproduce
2. Expected vs actual behavior
3. Relevant logs (backend stdout, gateway log for desktop)
4. OS and version

## License

By contributing, you agree that your contributions are licensed under the MIT License.
