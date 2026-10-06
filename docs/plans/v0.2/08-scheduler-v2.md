# v0.2.0 Scheduler v2

## Outcome

CaberOS reliably starts one-time, interval, and cron work across restart/sleep with explicit timezone, overlap, missed-run, retry, approval, and history semantics.

## Included

- One-time, interval, cron, and Run now
- Named timezone and DST preview
- Missed-run, overlap, and bounded retry policies
- Versioned Schedule configuration
- Optional approved Plan revision
- Agent/model/Skill/browser/retrieval/limit/output references
- Persistent history, pause/resume, duplicate, test-run

Event/webhook triggers and generic Tasks are deferred to v0.2.2.

## Domain model

A Schedule revision captures its trigger and execution inputs. Each occurrence creates an independent run/session and Execution Manifest. Editing affects future occurrences; active work retains its captured revision.

Policies:

```text
missed: skip | run_once | catch_up
overlap: skip | queue | cancel_previous | allow_parallel
failure: no_retry | bounded_retry(backoff)
```

Safe defaults are run-once after resume, queue/skip overlap, and bounded retry. `allow_parallel` still uses separate sessions; one conversation never runs concurrent reasoning steps.

## Time semantics

Store timezone separately from expression. Preview upcoming occurrences before enabling. Define nonexistent/duplicate DST times and default to one execution rather than accidental duplication.

## Approvals and idempotency

A gated action pauses, persists state, creates approval, and notifies. Timeout never means approval. Optional pre-approved Schedule scopes remain inside the agent ceiling.

Retries must not repeat external effects. Store operation/idempotency state where adapters support it; never blindly restart an entire side-effecting sequence.

## UI

- List and calendar views
- Next-run previews
- Create/edit/duplicate/pause/resume/delete
- Run now and test-run
- Visible timezone, missed, overlap, retry, approval, and output policies
- Current run/history/failures/retries/artifacts

## Tests first

- Persistence across restart
- Sleep/resume policies
- DST gap/duplicate behavior
- Deterministic overlap behavior
- Approval wait/timeout/restart
- Edit does not mutate active execution
- Retry does not duplicate simulated external write
- History links Schedule revision, Plan, Skills, model calls, browser profile, sources, and Artifacts

## Done when

Scheduled artifact work survives restart and sleep, handles overlap/failure predictably, pauses safely for approval, and produces inspectable history.

## Implementation status (landed)

- **Models** (`models/schedule.py`): `Schedule` (identity + runtime state + `managed` flag), `ScheduleRevision` (immutable config payload, `content_hash`), `ScheduleOccurrence` (one row per firing decision — `queued|running|completed|failed|skipped_missed|skipped_overlap|cancelled`, `attempt`/`retry_of` chain). `UTCDateTime` TypeDecorator — SQLite `DateTime(timezone=True)` reads back naive; the decorator stores naive-UTC and returns aware-UTC so persisted instants can be compared safely.
- **Engine** (`scheduler.py`): single tick loop (`TICK_SECONDS=15`). Persisted `next_fire_at` is the source of truth — restart/sleep recovery is a DB read. Two-phase tick: drain due queued occurrences (backoff-aware), fire due schedules, commit, *then* spawn run tasks (the run session must see committed rows). Startup: heartbeat projection sync (content-hash-gated, preserves `next_fire_at` when unchanged so the sweep sees the true gap) → stale `running` occurrence reconcile → missed-run sweep per policy (`catch_up` bounded at 25).
- **DST semantics**: nonexistent wall time → fires once at the first valid instant (croniter shifts forward); ambiguous fold time → fires once at the first pass — the fold's second instant is suppressed when anchored on the first.
- **Heartbeat facade**: `agent_config.heartbeat` stays the authoring surface; `sync_heartbeat_schedule` projects it onto a managed schedule (`managed="heartbeat"`, rejected by schedules-API mutations). Old `/api/scheduler/heartbeat*` + `/alerts` endpoints unchanged. Startup projects a managed row for every enabled agent (inspectable via `/api/schedules`); the UI surfaces them on the Heartbeat tab, not in the schedules list.
- **Run wiring**: each occurrence runs `run_agent(new_session=True, trigger="schedule"|"heartbeat")` with `schedule_context={schedule_id, revision_id, occurrence_id, auto_approve, max_cost, plan_revision_id}` → manifest pins `schedule_revision_id`/`plan_revision_id`; pipeline sets `syscall_handler._schedule_auto_approve` and a schedule-specific `max_cost`; mediator skips the approval prompt only for listed capabilities after normal permission checks (ceiling unchanged). Harness cost-cap fix: heartbeat cap applies only to `trigger="heartbeat"`, scheduled runs use `limits.max_cost_per_run`.
- **API** (`api/schedules.py`): list/create/detail(+preview+recent occurrences)/edit-as-new-revision/pause/resume/duplicate(starts disabled)/archive/run-now/test-run/trigger-preview/paged occurrences. Managed schedules: pause/resume allowed via heartbeat toggle; edit/delete rejected (400).
- **UI** (`Scheduler.tsx`): two surfaces — **Schedules** (default) lists only user-created schedules (managed heartbeat rows filtered out); **Heartbeat** restores the v0.1 per-agent card surface (toggle, prompt, interval, cost cap, failure threshold, fire-now — via `listHeartbeats`/`updateHeartbeat`/`fireHeartbeat`). Schedule editor is a centered modal: agent picker, name, trigger-kind segmented control (Once / Every … / On a schedule). Cron is preset-driven (Daily / Weekdays / Weekly on… / Monthly on day… / Custom escape hatch) — raw expressions never the primary UI; `describeCron()` renders "Weekdays at 09:00" summaries and cards show human trigger text. IANA timezone datalist (browser tz default), live "next 6" preview via `/api/schedules/preview`, missed/overlap/retry policies, per-capability pre-approve chips (approval-gated caps only), per-run cost cap. Row actions: run-now / test-run / pause-resume / duplicate / archive / inline occurrence history. Action errors surface in a banner.
- **Tests**: `test_scheduler_v2.py` — trigger math, DST gap/fold, validation, revision immutability + occurrence pinning, missed skip/run_once/catch_up, all four overlap modes, execute success/failure counters, bounded retry backoff + cap, run-now, restart reconcile + persistence, heartbeat revision tracking, manifest pinning, auto-approve prompt skip + out-of-scope still prompts. 783 backend tests green; tsc + oxlint + 33 vitest green.

### Deferred / known limits

- Retries re-run the task; true per-operation idempotency keys need adapter support (W10+).
- `plan_revision_id`, `model_override`, `skill` are captured on the revision/manifest; Plan entities don't exist yet — the field is a forward-compat string ref.
- Alert cards are keyed per agent — two simultaneously-failing schedules on one agent collapse visually (cleared together).
- Calendar view (plan lists list+calendar) deferred — list-first shipped.
