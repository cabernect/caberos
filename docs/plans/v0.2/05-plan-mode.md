# v0.2.0 Plan Mode (scoped)

> **Status: DEFERRED.** Spec is settled and preserved for implementation when
> the trigger fires — "a real task hurts without approach-level review"
> (e.g. approving many gated calls blind on a consequential task). Until then
> the cost (Plan table, mediator hook, card UI, tests) outweighs the value of
> an opt-in feature on a single-user system. Per-tool approvals already
> prevent bad outcomes; plan mode only shows the approach earlier.
>
> All rulings below were settled in a grilling pass — implement as written,
> don't re-litigate.

## Outcome

`/plan` lets users inspect a proposed approach before any side effects, then
execute it under the normal capability gates. Opt-in only — never mandatory,
never auto-triggered by heuristics in v1.

Plan mode is a **permission preset + a plan card**, not a new subsystem. It
reuses the W0 `effects` classification, the approval mediator, and the W0
ExecutionManifest. No revision-versioning state machine, no deviation
classifier, no staleness revalidation tables.

## Interaction

`/plan <goal>` enters planning with that goal; bare `/plan` or the composer
mode selector enters planning and the *next* message supplies the goal.
`/plan` while a non-terminal plan exists is rejected ("finish or discard the
active plan first").

**Scope is the session, keyed to plan lifecycle — not a separate flag.** The
read-only preset is active iff a Plan row exists in `drafting` or
`awaiting_approval`. `/plan` creates the row immediately (status `drafting`),
so the preset always has a Plan behind it. Approve flips to `executing` →
preset off; Discard → preset off.

Consequences:

- Any message sent while a plan is `drafting`/`awaiting_approval` is gated
  read-only — including unrelated questions. That's correct: "this session is
  planning" is the mental model, and a read can't hurt a read-only question.
- Discard is available in `drafting` and `awaiting_approval` — the escape
  hatch before a draft exists.
- Discard is *not* available during `executing` — you stop the run (existing
  mechanism) and the plan follows it.

## Domain model

```text
Plan
  id
  session_id
  agent_id
  title
  status            # drafting | awaiting_approval | executing | completed | failed | discarded
  draft             # JSON blob — mutable until approved
  approved_snapshot # frozen copy of draft at approval time
  execution_run_id? # the run spawned by Approve
```

`draft` shape (what the card renders):

```text
objective           # required
steps[]             # required — ordered: title + description
scope               # inputs/resources the plan will touch
capabilities        # capability names the plan expects to need
expected_artifacts
approval_points     # effects the user should expect to be asked about
risks
completion_criteria
```

One non-terminal plan per session. Edits before approval mutate `draft`;
approval freezes `approved_snapshot`. There is no revision history — the
bound snapshot plus the run's ExecutionManifest is the audit trail.

`status` is always a mirror of something real, never its own parallel truth:
a plan in `executing` ends when its `execution_run` ends — run `completed` →
plan `completed`; run `failed`/`stopped`/`interrupted` → plan `failed` with
the reason carried. The startup reconciler flips orphaned `executing` plans
in the same sweep that reconciles orphaned runs.

## Planning policy (the permission preset)

While the preset is active, the mediator applies two rules per call:

- **Mutating calls auto-deny** — `effects` ⊄ `{read}` → honest denial:
  "you're in plan mode — include this in the plan or ask to exit." Enforced
  at the mediator, same seam as approvals; prompt text cannot bypass it.
- **Read calls auto-approve** — `effects ⊆ {read}` skips `require_approval`.
  The plan-level approval is the real gate; per-call read gates during
  planning are ceremony without information. Every read remains visible in
  the timeline. (Deliberate relaxation: ungated egress reads like
  `web_fetch`/`web_search` — the user invoked `/plan` knowing investigation
  happens.)

Allowed therefore: file reads, search, retrieval, Skill loading,
`browser_open`/`observe`/`extract`, `agent_ask_user`, `memory_recall`,
`web_fetch`, `web_search`, and the plan-draft writer itself.

Two deliberate rulings:

- **`browser_act` — allowlist, not denylist.** `browser_act` is tagged
  `external_write`, but a per-action check allows `navigate`, `scroll`,
  `hover` in plan mode; everything else — `click`, `type`, `select`,
  `keypress`, and **any future action until consciously classified** — is
  denied. `navigate` is a GET and GETs can mutate in principle (logout
  links); accepted because `web_fetch` has identical exposure and the domain
  leash still applies.
- **`run_subagent` is denied.** It is deliberately tagged mutating ("can
  reach every effect class inside the parent's ceiling"), so the effects
  gate covers it with zero code — no spawn-a-subagent bypass. A read-only
  `capabilities` subset carve-out is a possible follow-up, not v1.

Unknown/unclassified MCP tools already default to `DEFAULT_MUTATING` → denied.

## Approval and execution

- **Approve is a bare click.** It freezes `draft` into `approved_snapshot`,
  records the snapshot reference on the ExecutionManifest, and **spawns a new
  run** seeded with the snapshot ("execute this plan") — `execution_run_id`
  links them. The planning run already ended at `plan_submit`; a suspended
  run would die at the next restart anyway (the reconciler marks parked runs
  `interrupted`), so the Plan row is the durable handoff — and making the
  plan the seed is what forces draft quality. No optional note field: "yes
  but skip step 4" breaks the invariant **approved snapshot ≡ executed
  plan**; amendments go through Revise, which costs one model turn.
- **Revise is explicit.** A Revise affordance on the card focuses the
  composer ("Revise plan…"); the message is tagged as revision feedback →
  status returns to `drafting` → the model updates `draft` → `plan_submit`
  flips it back to `awaiting_approval`. Untagged messages during
  `awaiting_approval` are ordinary gated chat; the plan stays put.
- **Approve covers the plan as an approach — it does not pre-approve
  individual calls.** Per-tool gates apply normally during execution.
- **`capabilities` is an approval ceiling, mechanically enforced.** During a
  plan-bound execution run, a call to a capability *not* in the approved
  list requires approval even if normally ungated — that prompt is the
  deviation signal ("plan said these tools; it now wants `terminal`"), no
  classifier needed. Under-declared plans get friction, which forces honest
  plans. All other draft fields (`scope`, `risks`, …) are descriptive intent,
  not enforcement.
- **Ungranted capabilities badge, don't block.** If the draft names a
  capability the agent isn't granted, `plan_submit` still accepts it; the
  card renders a "not granted" badge. The user can grant it and approve, or
  approve anyway (the call fails honestly and the agent adapts) — the card's
  job is surfacing the gap, not forbidding it.
- Execution progress = the normal run timeline. Card steps are display-only;
  the harness tracks no per-step state.
- Descriptive-field deviation (new domain, bigger scope): the agent pauses
  and asks via the normal approval/`agent_ask_user` path, saying what
  changed. Approved → continue, noted on the run record.
- Plan state persists on the DB row: an `awaiting_approval` plan survives a
  backend restart and its card re-renders; `executing` plans mirror their
  run's reconcile outcome.

## Plan-draft writer

`plan_submit` — session-scoped capability, **injected into the tool menu only
while the preset is active** (reuses the progressive-disclosure seam; it
doesn't exist as a schema outside plan mode, so normal runs can't create
Plan rows and pay no context cost). Writes/updates `draft`, flips status to
`awaiting_approval`. Schema is typed-but-shallow: `objective` and `steps[]`
required, everything else optional — card quality comes from the prompt
asking for the fields, not the schema enforcing them. Re-calling while
`awaiting_approval` just updates the draft (model self-revision).

## UI

- Composer: mode selector + `/plan` parsing; visible "Plan mode" badge while
  the preset is active
- **Inline card** at submit — the artifact of record, lives in the message
  stream permanently
- **Pinned banner** while `awaiting_approval`/`executing` — title + status
  only, no step ticking (steps are display-only); click scrolls to the card.
  Unpins at terminal status.
- Card renders all draft fields; ungranted capabilities get a "not granted"
  badge
- Actions: Approve & Execute (bare click), Revise (tagged feedback),
  Discard (`drafting`/`awaiting_approval` only)
- Deviation pause renders as a normal approval card with the deviation note

## Tests first

- `/plan` never resolves as a Skill
- Preset keyed to lifecycle: active in `drafting`/`awaiting_approval`, off in
  `executing`/terminal; no separate session flag
- Mutating calls auto-deny; read calls auto-approve (`web_fetch` fires with
  no gate); `run_subagent` denied
- `browser_act`: navigate/scroll/hover pass, click/type/select/keypress
  denied, unlisted action denied
- `plan_submit` absent from the tool menu outside plan mode; draft updates;
  approve freezes snapshot + binds manifest + spawns seeded execution run
- Revise-tag → `drafting` → resubmit → `awaiting_approval`; untagged message
  during `awaiting_approval` doesn't touch the plan
- `/plan` during a non-terminal plan is rejected
- Execution: call outside approved `capabilities` requires approval even if
  ungated; per-tool gates otherwise normal
- Discard during `executing` rejected; run stop → plan mirrors to `failed`
- Plan row survives restart; orphaned `executing` plan reconciles with its run

## Done when

A user can `/plan` an integrated artifact/browser task, watch the agent
inspect read-only (no approval clicks during planning), review and revise the
plan card, approve it, see execution under normal gates plus the capability
ceiling, and observe one honest deviation pause.

## Explicitly out of scope (v1)

- Auto-triggering plan mode from task complexity/risk heuristics
- Plan revision history, comments, step-by-step pause/continue controls
- Material-vs-tactical deviation classification
- Staleness revalidation of referenced files/skills/profiles at approval time
- Harness-owned PlanStep status tracking
- Read-only-subset `run_subagent` during planning
- Approve-with-note amendments (use Revise)
- Per-session "keep gating egress reads" toggle
