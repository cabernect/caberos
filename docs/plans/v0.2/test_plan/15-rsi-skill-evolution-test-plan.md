# Test plan — v0.2 RSI skill-evolution slice

Manual verification for the landed slice on `feat/v0.2-rsi`:
skill activation accounting, session-close reflection, staged/conflict-safe
skill revisions, and drift snapshots. Plan doc: `15-rsi-skill-evolution.md`.

## Setup

- Agent configured with a working model + provider.
- Grant `read_file`, `write_file`, `skills_load`, `skills_usage` **without
  approval** on the agent — reflection can only use no-approval
  capabilities (an approval-gated `write_file` means reflection can never
  edit; that is also a test point).
- Set `limits.session_idle_timeout_min` low (1–2 min) so sessions close
  quickly — close is the reflection trigger. The sweeper is
  deadline-driven: a session closes at `last_activity + timeout` (worst
  case one 300s fallback wake if a wake-up poke is missed), not on a fixed
  5-minute tick.
- Keep the Traces page and Skills page open.
- `evolve` must resolve — check the Skills page lists it (built-in or an
  agent-local shadow).

## A. Skill activation counting

| # | Action | Expected |
|---|---|---|
| A1 | Fresh session, task needing no skill | Skills list: "Not recorded" / no count |
| A2 | Ask agent to *use* a specific skill | That skill → "Used 1 time", "Last used …" |
| A3 | Get the agent to load it again (new task) | Count increments per load |
| A4 | Forced/slash skill in one run | Counts once per run, not per model turn |
| A5 | Agent only lists skills or reads a resource | No count change — not activation |

Verify `skill_activations` rows carry `source=load|forced`, run_id, call_id.

## B. Reflection lifecycle

1. Run a real task, then send **feedback** ("that output was wrong — it
   should have done Y"), then let the session idle.
2. After idle timeout: session shows `learning` → closes.
3. **Traces**: a new `trigger=reflection` run appears, session-linked:
   - `Generation` rows = reflection model calls (`purpose="reflection"`,
     session_id set, tokens/cost aggregated on the run, latency recorded).
   - `skill_reflection` event: `changed` / `no_change` / `conflict` /
     `failed`, with source run ids and revision ids.
   - Tool calls the model made, including **denied** ones (e.g. `terminal`
     must be denied — restricted runs inspect/edit only).
4. The original task run's timeline is unchanged — reflection is distinct.

## C. Reflection → skill revision

| # | Scenario | Expected |
|---|---|---|
| C1 | Feedback describes a real reusable flaw in a local skill | Outcome `changed`; Skills → History: new `SkillRevision` with reason + `source_run_id` = reflection run; live file updated |
| C2 | Feedback was a one-off ("the data was weird this time") | `no_change`; nothing written |
| C3 | Flawed procedure was a global/built-in skill | Agent-local override created; shared/built-in bytes unchanged |
| C4 | Reflection inspects a skill via `skills_load` | No `SkillActivation` — "Used N times" unchanged |

## D. Drift scanner

| # | Action | Expected |
|---|---|---|
| D1 | Mid-run, agent writes `skills/newskill/` via ordinary `write_file`; close session | History: rev-1, summary "snapshot of live-dir change made outside a tracked edit", `source_run_id` empty |
| D2 | Manually edit a live skill file in a terminal; restart backend | Startup reconcile → new revision in History |
| D3 | Change nothing; close another session | No new revision |
| D4 | After a reflection-published revision, close again | No duplicate snapshot — publish/scanner hashes agree |
| D5 | Delete a live skill dir | History stays intact; no new row |

## E. Isolation / honesty

- Reopen the session in chat: no reflection messages or internal context —
  reflection rows stay out of conversation history.
- Session summary covers task runs only.
- Reflection run is excluded from activation counting and memory learning.

## F. Failure resilience

- Break the provider (bad key/endpoint) after tasks but before close →
  the close's own model calls fail, so **the session stays open** and no
  reflection row is created (documented memory semantics: provider
  failures leave the session open with originals retained). Restore the
  provider → close commits on retry and reflection then runs.
- A provider failure *inside* a completed close's reflection pass →
  reflection run = `failed`, session stays closed, memory learning kept.
- Restart the backend mid-reflection → startup reconcile marks the
  orphaned `running` reflection `failed`.

## Automated-only (do not attempt manually)

- Publish conflict (external edit landing between inspection and publish)
  — timing-dependent; `tests/test_skill_edit_session.py`.
- Per-turn call cap (>4 calls/turn) and evidence-fingerprint dedup —
  `tests/test_skill_reflection.py`.
- Frozen-scope paging bounds — `tests/test_skill_evidence_queries.py`.
- Drift hash consistency with tracked publish — `tests/test_skill_drift.py`.

## Notes

- A `no_change` outcome is a **successful** reflection, not a bug — the
  trace shows the model's reasoning.
- Reflection needs granted no-approval capabilities; missing grants make
  the corresponding calls denied, not failed.
- Reflection never replays task actions: `terminal`, `web_*`, browser,
  sub-agents are outside its restricted set.
