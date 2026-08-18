# 14 — Testing Hardening

## Goal

Coverage hardening (Decision 13): real-infrastructure tests, integration tests, and edge cases. The pytest infrastructure setup (conftest.py, pytest.ini_options, fixtures, test doubles) now lives in plan 00 (scaffold). This plan focuses on writing the tests that validate invariants, security properties, and edge cases across the system.

Real SQLite, real sandbox, real filesystem — only the model and network are doubled.

## Spec references

- **Decision 13** — This plan is coverage hardening only; pytest setup is in plan 00
- **Testing Decisions** — seams, coverage priorities, real infrastructure tests
- **All invariants** — I1-I9 are asserted as behavior
- **All decisions** — security properties tested as outcomes

## Dependencies

- [00-scaffold.md](00-scaffold.md) — pytest infrastructure, conftest.py, test doubles (model + channel)
- [07-pipeline.md](07-pipeline.md) — run execution pipeline
- [08-channels.md](08-channels.md) — channel transport (was plan 09)
- [09-observability.md](09-observability.md) — observability write side (was plan 12)
- [10-connectors.md](10-connectors.md) — connectors (was plan 07)
- [11-memory-skills.md](11-memory-skills.md) — memory and skills (was plan 08)
- [12-control-plane.md](12-control-plane.md) — control plane (was plan 10)
- [13-frontend.md](13-frontend.md) — frontend (was plan 11)
- All other plans — testing validates every part

## Tasks

> **Note:** The pytest infrastructure (conftest.py, fixtures, `pyproject.toml` pytest config) and the test doubles (model double, channel transport double) are set up in plan 00 (scaffold). This plan assumes they already exist and focuses on writing the actual test suites.

### 1. Write workspace containment tests (highest priority)

`backend/tests/test_workspace_containment.py`:
- `file.read("../etc/passwd")` → denied, path escapes workspace
- `file.read("/etc/passwd")` → denied, absolute path outside workspace
- `file.write("../../../etc/cron.d/evil", "content")` → denied
- Symlink in workspace pointing outside → rejected
- `shell.run("cat /etc/passwd")` → blocked by sandbox (not visible in sandbox)
- `shell.run("curl http://example.com")` → blocked (no network by default)
- `file.read("safe.txt")` → succeeds (inside workspace)
- `file.write("dir/file.txt", "content")` → succeeds (inside workspace)

### 2. Write subject injection tests

`backend/tests/test_subject_injection.py`:
- `email.read()` with bound Contact → resolves to bound mailbox, audit record shows correct subject
- `email.read()` with unbound Contact → denied, reason "no subject binding"
- Model passes `email.read(mailbox="other@person.com")` → denied (schema doesn't accept parameter)
- `memory.recall()` → resolves to session's Contact, not model-supplied
- Cross-contact recall → Contact A cannot recall Contact B's memories

### 3. Write scope narrowing tests

`backend/tests/test_scope_narrowing.py`:
- Agent with `self` scope calls `email.read()` → resolves to own mailbox
- Agent with `any` scope calls `email.read()` → resolves to own mailbox (any means the agent *can* access others, but subject injection still resolves to self)
- Sub-agent with broader capabilities than parent → narrowed to parent's grants
- Every combination of agent ceiling × sub-agent ceiling

### 4. Write delivery integrity tests

`backend/tests/test_delivery.py`:
- Duplicate `message_id` → exactly one reply
- Two concurrent messages from same Contact → ordered replies (second queues)
- Crash mid-run (simulate by killing the process) → on restart, run recovered or failed

### 5. Write compaction tests

`backend/tests/test_compaction.py`:
- Long session (many turns) → context stays under `max_context_tokens`
- Compaction event recorded on Run
- Warning fires at 80% of ceiling (before 100%)

### 6. Write cost control tests

`backend/tests/test_cost.py`:
- Run exceeding `max_cost_per_run` → stops, fallback applied
- Recorded cost matches sum of all calls (including sub-agent turns)
- Sub-agent turns count against parent Run's limits

### 7. Write approval gate tests

`backend/tests/test_approval.py`:
- `require_approval` syscall → does not execute until approved
- ApprovalRequest created with correct context
- Approve → syscall executes, audit record written
- Reject → denied audit record, run continues

### 8. Write plane isolation test

`backend/tests/test_plane_isolation.py`:
- Control-plane route (`/api/*`) is NOT served on the data-plane socket (`0.0.0.0:8080`)
- Data-plane route (`/webhooks/*`) is NOT served on the control-plane socket (`127.0.0.1:8081`)
- Asserted by making requests to the wrong port and checking for 404

### 9. Write memory tests

`backend/tests/test_memory.py`:
- **Three-layer memory:**
  - MEMORY.md — persistent file in the agent home dir, read and written by the agent via `memory.update` (D34)
  - Knowledge graph triples — structured facts stored and queried
  - Semantic recall — embedding-based recall bounded by token budget
- Store and recall round-trip across all three layers
- Recall bounded by token budget
- Memory namespaced per Contact (cross-contact recall returns nothing)
- Clear memory deletes all entries
- **Skills loading and trigger matching:** skills are loaded from the workspace, trigger matching selects the right skill for a given input
- **Identity fields in context assembly:** `soul`, `persona`, `task` (config fields on `AgentConfig` — D35) are included in the context window during run execution, in that order, before MEMORY.md

### 10. Write heartbeat tests

`backend/tests/test_heartbeat.py`:
- Heartbeat config enabled → scheduler starts asyncio task
- Heartbeat fires → Run created with `trigger = "heartbeat"`
- Heartbeat run follows same pipeline as user-triggered run
- Heartbeat run exceeds `max_cost_per_heartbeat` → stopped, recorded
- Heartbeat produces result → message delivered to dashboard channel, tagged as heartbeat
- Heartbeat produces nothing → recorded silently in audit log
- Disable heartbeat → scheduler task cancelled, no more heartbeat runs
- Update heartbeat interval via API → scheduler restarts with new interval
- Run list filterable by trigger (user_message / heartbeat)
- **Consecutive failure threshold testing (Decision 14):**
  - Heartbeat run hits a model error → fails silently, no retry
  - Consecutive failures below threshold → no alert
  - Consecutive failures reach threshold (default 3) → single alert sent to operator via dashboard
  - Successful heartbeat run → consecutive failure count resets to 0
  - Configurable threshold via `HeartbeatConfig.consecutive_failure_threshold`
- **Heartbeat run failed on restart (Decision 5):**
  - Restart with in-flight heartbeat run → run marked `failed`, not requeued
  - Next interval fires naturally after restart
  - User-triggered runs are requeued on restart (contrast with heartbeat)
- **Heartbeat run failed on cancellation (Decision 5):**
  - Cancel an in-flight heartbeat run → marked `failed` with reason "heartbeat cancelled by operator"
  - Shutdown with in-flight heartbeat run → marked `failed` with reason "heartbeat cancelled by shutdown"

### 11. Set up real-infrastructure tests

`backend/tests/real/`:
- `test_sandbox_isolation.py` — real process-level sandbox (sandbox-exec on macOS, bwrap on Linux), filesystem escape and network egress blocked. Marked `@pytest.mark.real` — excluded from default suite.
- `test_tool_calling.py` — real Ollama model, Vietnamese/English prompts, well-formed syscalls. Marked `@pytest.mark.ollama`.
- `test_smoke.py` — manual end-to-end: dashboard chat, shell command, file read/write, email read via real connector. Marked `@pytest.mark.smoke`.

> The pytest marker configuration (`[tool.pytest.ini_options]` in `pyproject.toml`) is set up in plan 00 (scaffold).

## Files to create

> conftest.py, doubles/__init__.py, doubles/model.py, and doubles/channel.py are created in plan 00 (scaffold).

- `backend/tests/test_workspace_containment.py`
- `backend/tests/test_subject_injection.py`
- `backend/tests/test_scope_narrowing.py`
- `backend/tests/test_delivery.py`
- `backend/tests/test_compaction.py`
- `backend/tests/test_cost.py`
- `backend/tests/test_approval.py`
- `backend/tests/test_plane_isolation.py`
- `backend/tests/test_memory.py`
- `backend/tests/test_heartbeat.py`
- `backend/tests/real/test_sandbox_isolation.py`
- `backend/tests/real/test_tool_calling.py`
- `backend/tests/real/test_smoke.py`

## Verification

- `uv run pytest` — all default tests pass (excluding real/ollama/smoke)
- `uv run pytest -m real` — sandbox isolation tests pass (requires sandbox-exec on macOS or bwrap on Linux)
- `uv run pytest --tb=short` — no unexpected failures
- `uv run pytest --cov=agentos --cov-report=term-missing` — coverage report shows key modules covered
- Every coverage priority from the spec has at least one test file
