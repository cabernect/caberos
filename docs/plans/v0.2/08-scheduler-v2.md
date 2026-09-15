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
