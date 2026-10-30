# W8 Test Plan — Scheduler v2 (persistent schedules)

**Audience:** an agent executor. Every case has an exact command + a
machine-checkable assertion. Branch under test: `feat/v0.2.0` (W8 code is
uncommitted on top of `dcac96a`).

**What W8 added:** `Schedule`/`ScheduleRevision`/`ScheduleOccurrence` tables —
persisted `next_fire_at` is the source of truth; one occurrence row per firing
decision; immutable revisions pinned per occurrence (`schedule_revision_id` on
the manifest); once/interval/cron triggers with IANA timezones (croniter);
missed (`skip|run_once|catch_up`≤25), overlap (`skip|queue|cancel_previous|
allow_parallel`), and bounded-retry policies; pause/resume/duplicate/archive;
run-now/test-run; preview; paged occurrence history; schedule `auto_approve`
(capability allowlist — ceiling unchanged); per-run `max_cost`. Heartbeat is a
facade over a managed schedule (`managed="heartbeat"`); old
`/api/scheduler/heartbeat*` + `/alerts` endpoints unchanged. UI: two tabs —
**Schedules** (user rows only) + **Heartbeat** (per-agent cards), centered
modal editor with preset cron builder.

**Timing budget:** `TICK_SECONDS = 15` — a 60 s interval fires within ~75 s
worst case. Plan waits accordingly.

**Fixtures:** one enabled agent (`$AGENT_A`) with a working provider and the
`terminal` capability (approval-gated — needed for §8). A second agent optional.

---

## 0. Automated gates (run first)

```bash
cd backend && uv run pytest tests/test_scheduler.py tests/test_scheduler_v2.py -q
# → all pass (43 tests: 8 facade-compat + 35 engine/policy/revision)
cd backend && uv run pytest -q
# → 783+ pass — no regressions elsewhere
cd backend && uv run ruff format --check src/ tests/ && uv run ruff check src/ tests/
# → clean
cd frontend && npx tsc --noEmit && npx oxlint src/ && npx vitest run
# → tsc clean; oxlint non-fatal warnings only; 33 vitest pass
```

These cover the engine internals (DST gap/fold, restart persistence, overlap
modes, retry chains, revision pinning, startup reconcile) — the sections
below exercise the same behavior end-to-end through the API and UI.

---

## 1. Setup

```bash
cd backend
uv run uvicorn agentos.main:app --port 8081 &
# wait for: curl -s http://127.0.0.1:8081/health → {"status":"ok"}

TOKEN=$(curl -s -X POST http://127.0.0.1:8081/api/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"<operator>","password":"<password>"}' \
  | python3 -c 'import json,sys;print(json.load(sys.stdin)["session_token"])')
H="Authorization: Bearer $TOKEN"
API=http://127.0.0.1:8081/api
AGENT_A=<id of an enabled agent with a working provider>
```

---

## 2. CRUD + revisions

**2.1 Create an interval schedule**

```bash
curl -s -X POST $API/schedules -H "$H" -H 'Content-Type: application/json' -d '{
  "agent_id": "'$AGENT_A'", "name": "Ping every minute", "enabled": true,
  "trigger": {"kind": "interval", "every_seconds": 60},
  "task_prompt": "Reply with the word OK and nothing else",
  "policies": {"missed": "run_once", "overlap": "skip",
               "failure": {"mode": "no_retry"}}
}'
```

Assert: 201; `revision_number == 1`; `next_fire_at` set (~now+60 s);
`trigger.kind == "interval"`, `managed == null`, `enabled == true`.

**2.2 Validation rejects bad configs → 400**

- `trigger.every_seconds: 30` → `>= 60` error
- `trigger.cron: "not a cron"` → invalid-expression error
- `trigger.timezone: "Mars/Olympus"` → unknown-timezone error
- missing/empty `task_prompt` → `task_prompt is required`
- `policies.overlap: "parallel"` → enum error

**2.3 Edit writes a new revision; identical PUT does not**

```bash
curl -s -X PUT $API/schedules/<id> -H "$H" -H 'Content-Type: application/json' \
  -d '{<same body, task_prompt changed>}'
# → revision_number == 2
curl -s -X PUT $API/schedules/<id> ...   # identical body again
# → revision_number stays 2 (content-hash gate)
```

**2.4 Duplicate → disabled copy at rev 1**

`POST /api/schedules/<id>/duplicate` → `enabled == false`,
`name == "<name> copy"`, `next_fire_at == null`, `revision_number == 1`.

**2.5 Pause / resume / archive**

- `POST .../pause` → `enabled: false`; `next_fire_at` frozen (GET detail).
- `POST .../resume` → `enabled: true`; `next_fire_at` recomputed — the missed
  policy decides the gap (§5).
- `DELETE .../<id>` → archived: gone from `GET /api/schedules`, detail → 404.

**2.6 Managed rows reject mutation**

```bash
HBID=$(curl -s $API/schedules -H "$H" \
  | python3 -c 'import json,sys;print([s["id"] for s in json.load(sys.stdin) if s["managed"]=="heartbeat"][0])')
curl -s -X PUT $API/schedules/$HBID -H "$H" -H 'Content-Type: application/json' -d '{...}'   # → 400 "Managed schedule"
curl -s -X DELETE $API/schedules/$HBID -H "$H"                                              # → 400
```

Assert: `run-now`, `test-run`, `occurrences`, `duplicate` still work on the
managed id (they're not mutations of the config).

---

## 3. Trigger preview + timezone

```bash
curl -s -X POST $API/schedules/preview -H "$H" -H 'Content-Type: application/json' -d '{
  "trigger": {"kind": "cron", "cron": "0 9 * * 1-5", "timezone": "America/New_York"},
  "count": 6
}'
```

Assert:

- `timezone == "America/New_York"`; `occurrences` are 6 ISO instants landing
  Mon–Fri at 09:00 Eastern (DST-correct offsets when a boundary is crossed).
- `{"kind":"interval","every_seconds":90}` → instants 90 s apart.
- `{"kind":"once","at": <past ISO>}` → empty `occurrences` (past instant
  exhausts the trigger).
- Bad cron / bad tz → 400 with the validation message.

---

## 4. Live firing + occurrence materialization

**4.1 Interval fires and records history** — with the §2.1 schedule enabled:

```bash
sleep 90
curl -s "$API/schedules/<id>/occurrences" -H "$H"
```

Assert: ≥1 occurrence, `status == "completed"`, `run_id` set,
`scheduled_for ≈ next_fire_at` recorded at create time; `GET /api/schedules/<id>`
shows `last_status == "completed"`, `last_fired_at` set, `next_fire_at` advanced.

**4.2 Once trigger exhausts**

Create `{"kind":"once","at": now+70 s}` enabled. After ~90 s: one occurrence
completed; `next_fire_at == null`; schedule stays enabled but never refires.

**4.3 Revision pinning** — create a schedule, wait for occurrence A, then PUT a
changed prompt and let occurrence B fire:

```bash
curl -s "$API/schedules/<id>/occurrences" -H "$H" | python3 -c \
  'import json,sys;ocs=json.load(sys.stdin)["occurrences"];print({o["revision_id"] for o in ocs})'
```

Assert: two distinct `revision_id`s; occurrence A still points at rev 1 —
the in-flight config is captured, not shared.

**4.4 Occurrence paging** — `GET /occurrences?limit=2&offset=1` returns
`{occurrences: [...≤2], total: ≥3}` newest-first.

**4.5 Run-now is synchronous and ad-hoc**

`POST /api/schedules/<id>/run-now` blocks until the run finishes; response
`{run_id, status:"completed", error:null}`; a new occurrence appears with
`scheduled_for ≈ request time`. `test-run` returns `is_test` results via the
scripted pipeline (no model call). A schedule with an empty prompt → 400
`"Schedule has no task prompt"`.

---

## 5. Missed-run policies (gateway down)

Create three interval schedules (60 s) differing only in
`policies.missed`: `skip`, `run_once`, `catch_up`. Then:

```bash
# stop the gateway for ~4 minutes (4 missed instants each), restart
kill <uvicorn pid>; sleep 240; uv run uvicorn agentos.main:app --port 8081 &
sleep 30
```

Assert per schedule's `occurrences` (check after ~30 s of uptime):

- `skip` → **one** `skipped_missed` row at the latest missed instant, error
  `"4 occurrence(s) missed while inactive"`; `next_fire_at` is future.
- `run_once` → **one** `queued`→`running`→`completed` occurrence for the
  latest instant only (its `error` notes the earlier skips); earlier instants
  produce no rows.
- `catch_up` → one `queued` occurrence per missed instant; they drain
  sequentially (the queued-drain skips a schedule with running work) → all
  `completed` eventually.
- A `once` trigger whose `at` passed while down → at most 1 missed instant is
  ever recorded regardless of policy.

`catch_up` caps at 25 instants per sweep (`CATCH_UP_MAX`) — unit-tested; a
manual >25-missed check is optional.

---

## 6. Overlap policies

Force a slow run so two fires collide: schedule interval 60 s, task prompt
`"Use terminal to run: sleep 75; then say done"` on an agent where `terminal`
is pre-approved for the run (see §8.2 — set `auto_approve: ["terminal"]`).

- `overlap=skip` → second fire's occurrence is `skipped_overlap` while run 1
  is still running.
- `overlap=queue` → second fire lands `queued`, turns `running` only after the
  first finishes.
- `overlap=cancel_previous` → first occurrence becomes `cancelled` with
  `error` containing `cancelled by overlap policy`.
- `overlap=allow_parallel` → two `running` occurrences coexist (separate
  sessions — check `run_id`s differ).

---

## 7. Bounded retry

Force a failure cheaply — `model_override` to a nonexistent model:

```bash
curl -s -X POST $API/schedules -H "$H" -H 'Content-Type: application/json' -d '{
  "agent_id": "'$AGENT_A'", "name": "Always fails", "enabled": true,
  "trigger": {"kind": "interval", "every_seconds": 60},
  "task_prompt": "say hi",
  "policies": {"failure": {"mode": "bounded_retry", "max_attempts": 2,
                           "backoff_seconds": 60}},
  "model_override": {"model_name": "definitely-not-a-real-model-xyz"}
}'
```

Assert after ~4 min: attempt-1 occurrence `failed` → a `queued` retry with
`scheduled_for ≈ fail_time + 60 s` → attempt-2 occurrence `failed`,
`retry_of` pointing at attempt 1, `attempt == 2`. No attempt 3 (cap).
`consecutive_failures` on the schedule increments; at the alert threshold a
`schedule_failed` notification lands (`GET /api/notifications`) and the
schedule appears in `GET /api/scheduler/alerts` until cleared via
`POST /api/scheduler/alerts/<agent_id>/clear`.

Note: retries apply to any failed occurrence — a failing `test-run` queues a
retry under `bounded_retry` too (the retry path doesn't discriminate on
`is_test`).

---

## 8. Auto-approve vs the ceiling

**8.1 No pre-approval → run parks**

Schedule `auto_approve: []`, task prompt asking to run a shell command via
`terminal` (approval-gated). After firing:

- run status → `awaiting_approval`; `GET /api/runs/<run_id>` shows a pending
  approval; an `approval_required` notification exists.
- Approve via `POST /api/approvals/<approval_id>/approve` → run completes;
  occurrence flips `completed`.

**8.2 Pre-approved inside the ceiling**

Same schedule with `auto_approve: ["terminal"]` → fires and completes with no
prompt; occurrence `completed`.

**8.3 The ceiling still holds** — schedule `auto_approve: ["web_fetch"]` on an
agent that does **not** have `web_fetch` enabled: the call is still denied by
the permission check (auto_approve skips the *prompt*, never widens the
capability ceiling). Assert the audit record `allowed == false`.

---

## 9. Heartbeat facade over the engine

```bash
curl -s -X PUT $API/scheduler/heartbeat/$AGENT_A -H "$H" \
  -H 'Content-Type: application/json' -d '{
    "enabled": true, "interval_minutes": 1,
    "task_prompt": "Reply with the word OK"}'
curl -s $API/scheduler/heartbeat -H "$H"
curl -s $API/schedules -H "$H" | grep '"managed": "heartbeat"'
```

Assert:

- `GET /heartbeat` shows `enabled`, `interval_minutes`, `next_fire` populated.
- The managed row appears in `/api/schedules` with `managed == "heartbeat"`
  and `trigger.kind == "interval"` — facade and engine share state.
- `POST /api/scheduler/heartbeat/$AGENT_A/fire` blocks then returns
  `{run_id, status, error}`; the managed schedule's `occurrences` grows.
- Disabling via `PUT` → the row's `next_fire_at` goes null; no further fires.

---

## 10. Restart persistence + stale reconcile

- `next_fire_at` persists: record it, restart the gateway, GET again → same
  instant (restart must not re-anchor — only create/trigger-change/lost
  instant re-anchors).
- Kill -9 during a running occurrence → on restart the occurrence is
  `cancelled` with `error = "Gateway restarted during execution"`.

---

## 11. UI checklist (browser)

- `/scheduler` → two tabs: **Schedules** (default) and **Heartbeat** — no
  managed rows in the Schedules list.
- "New schedule" opens a **centered modal** (fixed overlay, dimmed backdrop) —
  not a drawer.
- Trigger picker: Once / Every … / On a schedule. Cron presets (Daily,
  Weekdays, Weekly on…, Monthly on day…) show a human summary
  ("Weekdays at 09:00 · Asia/Saigon") — raw expressions only under
  "Custom expression", still accompanied by the translation.
- "Preview next runs" lists the next instants in the chosen timezone.
- Agent picker lists all agents; errors (empty prompt, bad cron) show in the
  dialog, not silently.
- Card actions: toggle, Run, Test run, history (inline expand), edit,
  duplicate, archive — failures surface in the top banner.
- Heartbeat tab: one card per agent — toggle, prompt, interval, cost cap,
  fail threshold, Fire now (disabled until a prompt exists), last/next fire,
  last error.
- Page header matches other pages (icon on title line, description indented).

## Known limits (honest)

- `run-now`/`test-run` block the HTTP request for the run's whole duration —
  real runs can take a while (test-run is the scripted fast path).
- Tick granularity is 15 s; minimum interval is 60 s.
- `catch_up` is capped at 25 occurrences per sweep.
- Retries re-run the whole task — per-operation idempotency is W10+.
- Failure alerts are agent-keyed: two failing schedules on one agent collapse
  visually.
