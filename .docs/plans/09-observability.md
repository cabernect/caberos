# 09 — Observability

## Goal

Build the *write* side of the observability layer (Decision 12): `run_id` correlation across all logs, JSON structured logging, audit record creation, cost tracking, and latency recording. The *read* side (API endpoints for querying runs, syscalls, spend) lives in [12-control-plane.md](12-control-plane.md). Observability is a feature, not logging (D26).

## Spec references

- **D26** — Observability is a feature, not logging
- **D12** — Write side of observability is owned by this plan; read side is in plan 12 (control-plane)
- **D19** — Execution pipeline step 13 (record)
- **I6** — Every run is accounted

## Dependencies

- [01-database-layer.md](01-database-layer.md) — needs Run, AuditRecord, Message tables
- [03-harness.md](03-harness.md) — the harness records tokens, cost, latency on each Run
- [07-pipeline.md](07-pipeline.md) — the execution pipeline calls the recorder at the record step

## Tasks

### 1. Set up structured logging

`backend/src/agentos/logging.py`:
- stdlib `logging` with a JSON formatter
- Every log entry includes: `timestamp`, `level`, `logger`, `message`, and contextual fields
- Context variables (using `contextvars`): `run_id`, `agent_id`, `session_id`, `contact_id`
  - Set at the start of a Run, automatically included in every log line within that Run
  - Cleared when the Run ends
- Configure via `pyproject.toml` or `config.py`: log level, output (stdout for prod, file for dev)

### 2. Implement run recording

`backend/src/agentos/observability/recorder.py`:
- At Run creation: insert Run row with `status=running`, `started_at=now`
- During the run: update tokens_in, tokens_out, cost as they accumulate
- At Run completion: set `status=completed` or `failed`, `completed_at=now`, `latency_ms`
- Time-to-first-reply: record when the first reply is sent (D26)
- All updates are to the Run row; audit records are separate immutable inserts

### 3. Implement cost tracking

`backend/src/agentos/observability/cost.py`:
- LiteLLM provides token counts and cost per call (via the adapter, D6)
- Accumulate cost per Run (including sub-agent turns, D12 rule 5)
- Convert to a consistent currency (configurable, default USD or VND)
- Check against `max_cost_per_run` after each turn
- Store cost on the Run row

### 4. Implement error and fallback surfacing

- Model errors, provider fallbacks, retries, denied syscalls → all appear in the dashboard, not only in logs
- Errors are stored on the Run (an `errors` JSON field or separate table)
- The control-plane API routes (in [12-control-plane.md](12-control-plane.md)) read these

### 5. Implement delivery-gap detection

`backend/src/agentos/observability/gaps.py`:
- Track last message received per channel per agent
- If no messages for a configurable threshold (e.g. 24h on a channel that usually gets traffic) → alert
- For v0.1 (dashboard chat only), this is less relevant but the structure is in place for external channels

### 6. Implement push-based alerting

`backend/src/agentos/observability/alerts.py`:
- At least one push path for hard failures (D26)
- v0.1 options:
  - Desktop notification (macOS `osascript -display notification`)
  - Webhook to a configurable URL (Slack, Discord, etc.)
- Alert on: model provider unreachable, sandbox failure, run crashed, approval waiting too long
- Configurable per alert type

### 7. Implement shell audit trail

- Every shell command and its output is recorded on the Run (D26)
- Visible in the dashboard ([13-dashboard.md](13-dashboard.md)) as part of the run detail
- Stored in the audit record or a dedicated `shell_log` table

## Files to create

- `backend/src/agentos/logging.py`
- `backend/src/agentos/observability/__init__.py`
- `backend/src/agentos/observability/recorder.py`
- `backend/src/agentos/observability/cost.py`
- `backend/src/agentos/observability/gaps.py`
- `backend/src/agentos/observability/alerts.py`
- `backend/tests/test_observability.py`

## Verification

This plan owns the *write* side only — verification is about "is the data correctly written and correlated," not "can you query it" (querying is verified in [12-control-plane.md](12-control-plane.md) and [13-dashboard.md](13-dashboard.md)).

- Send a message → Run row created with `status=running` → completed with tokens, cost, latency recorded
- Log lines include `run_id`, `agent_id` context fields
- Cost on Run matches sum of all model calls in the run
- Sub-agent cost rolls up to parent Run
- Model error → error recorded on Run row, alert pushed (desktop notification)
- Time-to-first-reply recorded on the Run row
- `grep run_id=<id>` in logs → all lines for that run are correlated
- Audit records written as immutable inserts, separate from the Run row
- `uv run pytest tests/test_observability.py` passes (see [14-testing.md](14-testing.md))
