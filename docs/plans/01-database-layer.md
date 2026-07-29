# 01 — Database Layer

## Goal

Define all SQLAlchemy models, set up Alembic migrations, and create the SQLite database. Every table the system needs lives here — this is the schema the vertical slice writes to and the dashboard reads from.

## Spec references

- **D5** — SQLite (WAL) via SQLAlchemy, single source of truth
- **Domain Model** — all nouns that need tables: Agent, Capability, Sub-agent, Connector, Channel, Contact, Session, Run, Workspace, Memory, Approval Request, Audit Record
- **D25** — Agent configuration lives in the database (immutable version rows, `active_version` pointer)
- **D8** — Contact has optional binding to an internal record
- **D30** — Memory is per-Contact, namespaced

## Dependencies

- [00-project-scaffold.md](00-project-scaffold.md) — needs the Python project and uv

## Tasks

### 1. Set up SQLAlchemy async engine and session

`backend/src/agentos/db.py`:
- Async engine: `create_async_engine("sqlite+aiosqlite:///./data/agentos.db")`
- Enable WAL mode via `PRAGMA journal_mode=WAL` on connect
- `async_sessionmaker` for session factory
- `get_db()` FastAPI dependency

### 2. Define base and mixins

`backend/src/agentos/models/base.py`:
- `Base` (DeclarativeBase)
- `TimestampMixin` — `created_at`, `updated_at` (UTC, server-default)
- `IdMixin` — UUID primary key (string, generated)

### 3. Define all models

`backend/src/agentos/models/`:

**`agent.py`** — Agent + AgentVersion
- `Agent`: id, name, enabled, active_version_id, created_at
- `AgentVersion`: id, agent_id, version_number, config (JSON), created_at, is_active
  - Config is the full Pydantic-validated agent config serialized to JSON
  - Config includes optional `heartbeat` section (D31): enabled, interval_minutes, task_prompt, max_cost_per_heartbeat, consecutive_failure_threshold (Decision 14)
  - Each save creates a new immutable version row; `active_version` pointer advances

**`capability.py`** — Capability registry
- `Capability`: id, name, kind (enum: tool/sub_agent/memory/connector_action), description, schema (JSON), egress (bool), require_approval (bool, default false)
  - Note: `mcp_tool` kind removed — MCP moved to v0.2 (Decision 11a)
- `AgentCapability`: agent_version_id, capability_id, subject_scope (self/any/none), require_approval_override
  - Many-to-many between agent versions and capabilities, with per-grant settings

**`sub_agent.py`** — Pooled sub-agents
- `SubAgent`: id, name, task (D35), model (optional), capabilities (JSON list)
- Config load rejects channel or session fields (D12 rule 1)

**`connector.py`** — Connectors and credentials
- `Connector`: id, name, type (outlook/gmail/calendar/...), credential_ref (secret:// path), created_at
- `ConnectorCapability`: connector_id, capability_name (e.g. "email.read", "calendar.create")

**`provider.py`** — Model providers (Decision 17)
- `Provider`: id, name, type (openai/anthropic/google/ollama/azure/...), credential_ref (secret:// path, encrypted API key, null for local), base_url (optional), org_id (optional), extra_params (JSON), created_at
- Multiple providers of the same `type` allowed (personal vs work keys)
- The API key is stored encrypted via the secret store (Fernet, plan 10), referenced by `credential_ref` — never inlined
- Agents reference a provider by id (`AgentVersion.config.model.provider_id`)

**`contact.py`**
- `Contact`: id, channel, bot_id, external_user_id, display_name, binding (JSON, optional), created_at
- Unique constraint on `(channel, bot_id, external_user_id)`

**`session.py`**
- `Session`: id, contact_id, agent_id, status (active/idle/closed), started_at, last_activity_at, idle_timeout_min

**`run.py`** — Run + messages
- `Run`: id, session_id, contact_id, agent_id, status (pending/running/completed/failed), trigger (user_message/heartbeat), message_id, tokens_in, tokens_out, cost, latency_ms, started_at, completed_at, is_test (bool)
  - `trigger` field (D31): distinguishes user-triggered runs from heartbeat-triggered runs
- `Message`: id, run_id, role (user/assistant/system/tool/heartbeat), content, created_at
  - `heartbeat` role for messages produced by heartbeat-triggered runs (D31)

**`audit.py`**
- `AuditRecord`: id, run_id, agent_id, sub_agent_id (optional), capability_name, subject_contact_id (optional), allowed (bool), denied_reason (optional), cost, latency_ms, created_at
- Immutable — no updates, only inserts

**`approval.py`**
- `ApprovalRequest`: id, run_id, capability_name, args (JSON), status (pending/approved/rejected), decided_by, decided_at, created_at

**`memory.py`**
- `MemoryEntry`: id, contact_id, agent_id, key, value, tags (JSON), created_at
- Index on `(contact_id, agent_id)`
- `MemoryTriple`: id, contact_id, agent_id, subject (str), predicate (str), object (str), source_run_id (str, optional), created_at
  - Knowledge graph layer (Decision 7): structured facts as subject-predicate-object triples
  - Index on `(contact_id, agent_id)`
- Note: MEMORY.md (D34) is NOT a DB table — it's a markdown file in the agent home dir (`~/agentos/agents/{agent_id}/MEMORY.md`), read/written as a file. No model needed here.

**`operator.py`** — Operator auth (D4)
- `Operator`: id, username, password_hash (bcrypt), created_at
- `OperatorAuditLog`: id, operator_id, action, target, created_at

### 4. Set up Alembic

```bash
cd backend
uv run alembic init alembic
```

- Edit `alembic.ini` — `sqlalchemy.url = sqlite:///./data/agentos.db`
- Edit `env.py` — import `Base`, set `target_metadata = Base.metadata`
- Create first migration: `uv run alembic revision --autogenerate -m "initial schema"`
- Apply: `uv run alembic upgrade head`

### 5. Create seed script

`backend/src/agentos/seed.py`:
- Creates a default operator (admin/admin, forces password change on first login)
- Seeds the capability registry with built-in tools (file.read, file.write, file.list, shell.run, memory.recall, memory.store)
- Run via `uv run python -m agentos.seed`

## Files to create

- `backend/src/agentos/db.py`
- `backend/src/agentos/models/__init__.py`
- `backend/src/agentos/models/base.py`
- `backend/src/agentos/models/agent.py`
- `backend/src/agentos/models/capability.py`
- `backend/src/agentos/models/sub_agent.py`
- `backend/src/agentos/models/connector.py`
- `backend/src/agentos/models/provider.py`
- `backend/src/agentos/models/contact.py`
- `backend/src/agentos/models/session.py`
- `backend/src/agentos/models/run.py`
- `backend/src/agentos/models/audit.py`
- `backend/src/agentos/models/approval.py`
- `backend/src/agentos/models/memory.py`
- `backend/src/agentos/models/operator.py`
- `backend/alembic/env.py`
- `backend/alembic/versions/0001_initial_schema.py`
- `backend/src/agentos/seed.py`

## Verification

- `uv run alembic upgrade head` creates all tables in `./data/agentos.db`
- `sqlite3 ./data/agentos.db ".tables"` shows all tables
- `uv run python -m agentos.seed` creates operator + seeded capabilities
- `uv run pytest tests/test_db.py` — basic CRUD on each model passes
- WAL mode is active: `sqlite3 ./data/agentos.db "PRAGMA journal_mode;"` returns `wal`

## Cross-references

- Plan 07 — Pipeline (new)
- Plan 08 — Channels (was plan 09)
- Plan 09 — Observability (was plan 12)
- Plan 10 — Connectors (was plan 07)
- Plan 11 — Memory (was plan 08)
- Plan 12 — Control plane (was plan 10)
- Plan 14 — Testing (was plan 13)
