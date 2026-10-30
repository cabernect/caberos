# v0.2.0 RSI — Skill evolution loop (first slice)

First slice of Recursive Self-Improvement (CONTEXT.md): experience-driven
revision of the agent's procedures. The procedures are **skills**; the
revision loop is `build → use → outcome review → revise`, and the review is
an ordinary user message, not a gate.

## What already worked (no new code)

- **Build**: agent writes `workspace_root/{agent_id}/skills/{name}/` via
  `write_file`; the live dir resolves at the next run — agent-local wins
  precedence, `live:<sha256>` pinned in the execution manifest.
- **Use**: `skills_load` serves it; a forced slash skill injects its full
  body directly. The manifest records which revisions the skill menu
  *pinned* — availability and provenance of the offered set, not proof
  that any skill was actually activated.
- **Review**: operator feedback is a user message; the agent sees it in
  conversation and session-close extraction may persist the correction —
  durable retention is best effort, not guaranteed.

## Landed architecture — three pieces

1. **Skill activation evidence** — `SkillActivation` immutable event rows
   (`models/skill_usage.py`), written by `skills/usage.py` on an isolated
   session so a failed write never poisons the run's transaction. An
   activation is a successful `skills_load` (each explicit load counts,
   deduped per call id) or a successfully assembled forced/slash injection
   (once per run). Menu listings, resource reads, manifest pins, inherited
   context, **and reflection-run inspection** are not activations — the
   writer skips `is_test` and `trigger="reflection"` runs. The event key is
   SHA-256 over structured parts (no delimiter collisions); history keeps
   no FK to the skill row so deletion can't erase evidence.
   `skills_usage` (subject-scoped, no egress) reports the caller's own
   recorded activation evidence — counts, not effectiveness. The Skills
   list shows "Used N times" / "Last used …" / "Not recorded" — list-level
   summary only, no drill-down UI in this slice.

2. **Session-close skill reflection** — `agentos/reflection.py`
   (`reflect_session`) is the platform orchestrator, invoked from
   `episodic.close_session` **after** the conditional close commit lands.
   A failed reflection never reopens the session or rolls back memory
   learning; close itself never fails because reflection failed.

   - **Dedup**: one `SkillReflection` row per
     `(session_id, source_fingerprint)` — the fingerprint is SHA-256 over
     the frozen parent-message id set, so a restart or duplicate close
     claims nothing new.
   - **Frozen evidence**: non-test, non-reflection terminal runs of the
     session. The model gets a bounded tail-first view (recent parent rows,
     12k chars) plus `search_history` paging constrained to the frozen
     `run_ids`/`message_ids` via `history_scope` — it cannot browse other
     sessions or unbounded history.
   - **Restricted execution**: a real `Harness` run
     (`trigger="reflection"`, system prompt `REFLECTION_SYSTEM_PROMPT`)
     driven through the real `SyscallHandler` narrowed by
     `ExecutionRestrictions` — only capabilities the agent is granted
     *without approval* among {`read_file`, `write_file`, `skills_list`,
     `skills_load`, `skills_read_resource`, `skills_usage`,
     `search_history`}; anything else is denied by mediation, and
     approval-needing calls are denied outright (a background reflection
     cannot block on HITL). ≤4 concurrent tool calls (oversized batches drain through bounded slots, no extra reasoning turns), ≤8 turns, output tokens
     capped, no compaction retry — inspect/edit only, never task replay.
   - **Staged edits**: `read_file`/`write_file`/`skills_load`/
     `skills_read_resource` under `skills/{name}/` delegate to
     `SkillEditSession` (`skills/service.py`) — bytes are captured at
     inspection, edits stage in memory, nothing touches the live dir
     mid-run. On publish: source re-resolution, local-baseline hash check,
     drifted pre-edit bytes snapshotted first, then an immutable
     `SkillRevision` with `source_run_id` = the reflection run. A newer
     external edit is a `conflict`, never overwritten. Shared/built-in
     sources become agent-local overrides — original bytes are never
     mutated.
   - **Observability**: reflection model calls are ledgered with
     `purpose="reflection"` + `session_id`; the run's timeline carries
     `skill_reflection` (outcome, source run ids, revision ids, safe error)
     and one `skill_revision` event per saved revision. Denied tool calls
     persist as tool_call records in the run. Startup reconcile marks
     orphaned `running` reflections `failed`.
   - **Isolation**: `trigger="reflection"` runs are excluded from chat
     history, close-learning selectors, and activation accounting.

   - **Drift coverage**: `snapshot_agent_local_drift`
     (`skills/reconcile.py`) runs at session close (post-commit, before
     reflection) and inside startup `reconcile_skills`. It hashes each live
     agent-local dir with `hash_skill_dir` — the same digest `live:` pins
     and `_publish_one` use — and snapshots any dir whose bytes differ from
     the recorded revision. Bytes written outside a tracked edit session
     (mid-run `write_file`, manual edits) get an immutable revision with
     honest provenance: `source_run_id` NULL, summary states the change was
     made outside a tracked edit. A never-versioned dir gets rev-1 on first
     sighting; deletion leaves history intact. Serialized per agent through
     the same edit lock publishes take.

3. **`evolve` built-in skill** (`skills/evolve/SKILL.md`) — the Evolution
   Workflow as an ordinary versioned, progressively-disclosed skill. The
   reflection run injects its body as the method; agent-local precedence
   means an agent shadows `evolve` to revise the procedure itself — the
   recursion hook. Platform limits (restricted capability set, turn/byte
   bounds, conflict rules, no-replay) live in the orchestrator and cannot
   be changed by the procedure.

## Tests

- `tests/test_skill_reflection.py` — ScriptedModel through the real
  Harness + mediator: read → staged write → publish → `changed` with a
  source-linked `SkillRevision` and `purpose="reflection"` ledger rows;
  `no_change` + fingerprint dedup (second pass never reaches the model);
  out-of-restriction capability denied + provider failure finalizes
  `failed`; reflection `skills_load` produces no `SkillActivation`.
- `tests/test_skill_edit_session.py` — capture/stage/publish, global
  override preserving resources, mid-await publish conflict, snapshot of
  drifted pre-edit bytes.
- `tests/test_skill_activations.py` — load/forced counting, dedup,
  reflection/test exclusion.
- `tests/test_skill_evidence_queries.py` — frozen-scope evidence reads.
- `tests/test_skill_drift.py` — first-sighting rev-1, unchanged → no new
  revision, modify/delete → next revision with prior bytes intact,
  tracked publish → scanner sees no drift (hash functions agree).

## Done when

An agent can create a skill, use it, receive conversational feedback, and —
at session close — the reflection pass can inspect that evidence and
publish a conflict-safe, source-linked local revision (or honestly report
no change), all visible as a distinct activity in the existing trace
surface. The Skills list exposes activation count + last used. Usage
counts alone do not claim improvement — evaluation stays the operator's.

## Explicitly out of scope (v1)

- Proposals/approval gates on agent-local skills — review is feedback, not
  a publish gate. Promotion to global keeps the existing operator-only
  `promote` path.
- Revisions of `task`/`persona`/`soul` or config — identity-adjacent.
- Automated evaluation/scoring of revisions; replaying task actions to
  test a revision.
- Attributing drift snapshots to a specific run or writer — provenance is
  honestly unknown, not inferred.
- Tools-page statistics or capability-usage analytics — a future surface,
  deliberately not designed or pre-built here.
