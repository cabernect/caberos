# 12 — Control Plane

## Goal

Build the control-plane API: operator authentication (session + cookie), the admin API surface, and the operator audit trail. The control plane binds to loopback only and is never tunnelled (D4).

This plan owns the **read side** of observability (Decision 12): API endpoints for querying runs, syscalls, and spend. The **write side** (logging, audit record creation) lives in plan 09 (observability).

## Spec references

- **D4** — Two planes, two sockets (control plane on loopback, never tunnelled)
- **D5** — All state in SQLite
- **D31** — Heartbeat: per-agent periodic scheduler, triggers Runs without user message
- **Decision 4** — Approval via `asyncio.Event` (approve sets event, reject sets event with denied flag)
- **Decision 5** — Heartbeat runs failed on restart/cancellation, not requeued; user-triggered runs requeued
- **Decision 12** — This plan owns the read side of observability; write side is in plan 09
- **Decision 14** — Heartbeat runs fail silently on model errors; consecutive failures trigger a single alert
- **Stories 45-52** — approve syscalls, see approval queue, install, backup, survive restart, recover runs, alerts, provider errors
- **Stories 64-70** — heartbeat enable/disable, set interval, set cost budget, see heartbeat messages, filter runs by trigger

## Dependencies

- [01-database-layer.md](01-database-layer.md) — needs Operator, OperatorAuditLog tables
- [02-agent-config.md](02-agent-config.md) — agent API routes
- [04-syscall-layer.md](04-syscall-layer.md) — approval routes interact with the syscall layer
- [07-pipeline.md](07-pipeline.md) — run execution pipeline
- [09-observability.md](09-observability.md) — write side of observability (logging, audit record creation)
- [13-frontend.md](13-frontend.md) — frontend consumes the admin API

## Tasks

### 1. Implement operator authentication

`backend/src/agentos/auth.py`:
- `POST /api/auth/login` — username + password → verify bcrypt hash → set session cookie
- `POST /api/auth/logout` — destroy session
- `GET /api/auth/me` — current operator info
- Session middleware: Starlette SessionMiddleware with signed cookies
- Session stored in SQLite (not in-memory, so it survives restarts)
- Password hashing: `bcrypt`
- First-run: force password change for the default `admin` operator

### 2. Implement operator audit trail

`backend/src/agentos/auth.py`:
- Every mutating API call logs to `OperatorAuditLog`: operator_id, action, target, timestamp
- Separate from the agent syscall log (D4)
- `GET /api/audit/operators` — operator audit log (admin only)

### 3. Implement approval routes

`backend/src/agentos/api/approvals.py`:
- `GET /api/approvals` — list pending approval requests (story 46)
- `POST /api/approvals/{id}/approve` — approve a pending syscall. Sets an `asyncio.Event` that the paused run is waiting on (Decision 4). The run wakes, sees the event is set, and resumes execution.
- `POST /api/approvals/{id}/reject` — reject a pending syscall. Sets the same `asyncio.Event` but with a denied flag, so the paused run wakes and continues with the denial.
- On approve → the paused run resumes execution
- On reject → denied audit record written, run continues with the denial

### 4. Implement spend/budget routes

`backend/src/agentos/api/spend.py`:
- `GET /api/spend` — total spend today, this week, this month (story 33)
- `GET /api/spend/agents/{agent_id}` — per-agent spend breakdown
- `GET /api/spend/breakdown` — spend by capability, by day

### 5. Implement fleet management routes

`backend/src/agentos/api/fleet.py`:
- `GET /api/fleet` — one list of every agent with status, model, today's spend (story 28)
- `POST /api/fleet/bulk-update` — change model or cost cap across agents (story 30)

### 6. Implement observability routes

`backend/src/agentos/api/observability.py`:
- `GET /api/runs` — browse recent runs (story 38)
- `GET /api/runs/{id}` — run detail: messages, syscalls, model calls, errors (story 43)
- `GET /api/runs/{id}/syscalls` — syscalls for a run, with results (story 40)
- `GET /api/syscalls` — one syscall log across all agents, filterable (story 42)
- `GET /api/contacts/{id}/conversations` — conversations for a contact (story 39)

### 7. Implement startup recovery

`backend/src/agentos/recovery.py`:
- On startup, find all Runs with status `running` or `pending`
- Requeue or fail them with an apology message (D24, story 50)
- Log the recovery actions

### 8. Implement health and config routes

`backend/src/agentos/api/system.py`:
- `GET /api/system/health` — DB connected, sandbox available, model reachable
- `GET /api/system/config` — system configuration (non-secret)
- `POST /api/system/test-model` — test model connectivity

### 9. Implement heartbeat scheduler (D31)

`backend/src/agentos/heartbeat.py`:
- A per-agent asyncio task that triggers Runs on a configured schedule
- Started when the Gateway boots, for each agent with heartbeat enabled
- Managed alongside the agent's session lifecycle

**Heartbeat config** (stored in agent's DB record, D25):
```python
class HeartbeatConfig(BaseModel):
    enabled: bool = False
    interval_minutes: int = 60       # how often to fire
    task_prompt: str                  # what the agent should do
    max_cost_per_heartbeat: float = 0.50  # cost budget per heartbeat run
    consecutive_failure_threshold: int = 3  # alert after N consecutive failures (Decision 14)
```

**Scheduler logic:**
- On Gateway startup, load all agents with `heartbeat.enabled = True`
- For each, start an asyncio task that:
  1. Sleeps for `interval_minutes`
  2. Creates a Run with `trigger = "heartbeat"` and the heartbeat task prompt as the inbound message
  3. Runs through the normal execution pipeline (D19, steps 4–13)
  4. Enforces `max_cost_per_heartbeat` (separate from `max_cost_per_run`)
  5. If the run produces a result, delivers it to the dashboard channel (message appears in conversation, tagged as heartbeat)
  6. If the run produces nothing of note, records silently in audit log
  7. Repeats

**Failure handling (Decision 5 — restart/cancellation):**
- Heartbeat runs are **failed** on restart or cancellation, not requeued. The next interval fires naturally.
- User-triggered runs are requeued on restart.
- In-flight heartbeat runs on cancel/shutdown are marked `failed` with reason `"heartbeat cancelled by operator"` (cancel) or `"heartbeat cancelled by shutdown"` (shutdown).

**Failure handling (Decision 14 — model errors):**
- Heartbeat runs fail silently on model errors. No retry.
- Consecutive failures are counted. When the count reaches the configured threshold (default: 3, configurable via `HeartbeatConfig.consecutive_failure_threshold`), a single alert is sent to the operator via the dashboard.
- The consecutive failure count resets on a successful heartbeat run.

**API routes** (`backend/src/agentos/api/heartbeat.py`):
- `PUT /api/agents/{id}/heartbeat` — enable/disable, set interval, task prompt, cost budget
- `GET /api/agents/{id}/heartbeat` — current heartbeat config and next fire time
- `POST /api/agents/{id}/heartbeat/trigger` — manually trigger a heartbeat run (for testing)

**Integration with Run model:**
- Run table gains a `trigger` column: `"user_message"` or `"heartbeat"`
- Heartbeat runs follow the same pipeline as user-triggered runs
- The dashboard channel receives heartbeat results as messages tagged with `trigger = "heartbeat"`

**Lifecycle:**
- When an agent's heartbeat config is updated via API, the scheduler task is cancelled and restarted with the new config
- When an agent is disabled, its heartbeat task is cancelled
- On Gateway shutdown, all heartbeat tasks are cancelled gracefully. In-flight heartbeat runs are marked `failed` with reason `"heartbeat cancelled by shutdown"` (Decision 5). They are not requeued; the next interval fires naturally on restart.

## Files to create

- `backend/src/agentos/auth.py`
- `backend/src/agentos/heartbeat.py`
- `backend/src/agentos/api/approvals.py`
- `backend/src/agentos/api/spend.py`
- `backend/src/agentos/api/fleet.py`
- `backend/src/agentos/api/observability.py`
- `backend/src/agentos/api/heartbeat.py`
- `backend/src/agentos/api/system.py`
- `backend/src/agentos/recovery.py`
- `backend/tests/test_auth.py`
- `backend/tests/test_api.py`
- `backend/tests/test_heartbeat.py`

## Verification

- Login with wrong password → 401
- Login with correct password → session cookie set
- Mutating call without session → 401
- Mutating call with session → succeeds, OperatorAuditLog entry created
- Approval queue shows pending requests → approve → run resumes
- Reject → denied audit record, run continues
- Spend endpoint returns today/week/month totals, breakdown by trigger
- Fleet endpoint lists all agents with status, spend, and heartbeat status
- Restart with in-flight runs → user-triggered runs recovered or failed with apology; heartbeat runs failed (not requeued)
- Cancel an in-flight heartbeat run → marked `failed` with reason "heartbeat cancelled by operator"
- Shutdown with in-flight heartbeat runs → marked `failed` with reason "heartbeat cancelled by shutdown"
- Heartbeat run hits a model error → fails silently, no retry
- 3 consecutive heartbeat failures (default threshold) → single alert to operator via dashboard
- Successful heartbeat run → consecutive failure count resets to 0
- `GET /api/system/health` → all green
- Enable heartbeat on an agent → set interval to 1 minute for testing → heartbeat run fires → appears in conversation as heartbeat-tagged message
- Disable heartbeat → scheduler stops, no more heartbeat runs
- Heartbeat run exceeds cost budget → stopped, recorded
- Manually trigger heartbeat via API → run executes immediately
- Run list filterable by trigger (user_message / heartbeat)
- `uv run pytest tests/test_auth.py tests/test_api.py tests/test_heartbeat.py` passes
