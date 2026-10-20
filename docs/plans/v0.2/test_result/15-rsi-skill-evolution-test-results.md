# W15 — RSI Skill Evolution — Independent Test Results

**Date:** 2026-10-19 · **Tester:** independent verification agent (results below are first-hand, not from implementation claims)
**Branch:** `feat/v0.2-rsi` (uncommitted worktree) · **Host:** macOS ARM64
**QA env:** backend :18082 + Vite :15174, fully isolated under `/tmp/agentos-qa-gPM8` (own DB, workspace/skills/knowledge roots; main DB only read for provider copy)

**Setup:** test agent `w15-rsi-test` (`d9a65f2e`, v2) on approved model `gpt-6-luna` via a provider row copied into the QA DB (shared `secret.key` decrypts). No-approval grants: `read_file`, `write_file`, `skills_load`, `skills_usage`. `session_idle_timeout_min=1`; close triggered by sweeper (5 min) or lazily at next message.

**Environmental note:** the reflection symlink guard rejects skill roots under any symlinked parent; on macOS `/tmp` → `/private/tmp` blocked all reflection runs until `AGENTOS_WORKSPACE_ROOT` was repointed at the resolved path. Environmental, not a defect — but hosts with symlinked temp roots hit this.

## A. Skill activation counting — PASS (5/5)

| Case | Result |
|---|---|
| A1 no-skill task | `skill_activations` 0 rows; API counts empty |
| A2 `skills_load evolve` | 1 row, `source=load`, `run_id`+`call_id` linked |
| A3 reload in new task | second `load` row, distinct run → count 2 |
| A4 forced (`skill` msg param) | exactly 1 `source=forced` row per run, not per model turn |
| A5 `skills_list`-only run | real `skills_list` call observed in audit; count unchanged |

## B. Reflection lifecycle — PASS

Task → corrective feedback → idle → lazy close at next message → separate `trigger=reflection` run linked to the session. Verified on multiple sessions:

- `generation` rows carry `purpose=reflection`, session linkage, aggregated tokens/cost, latency.
- `skill_reflection` run event + Traces UI show reflection runs distinctly (trigger column), incl. `interrupted` row.
- Restricted capability set enforced; no `denied` outcomes occurred (model stayed in scope — denied-call persistence exercised by unit tests, not live here).
- One `skills_load` error outcome recorded in a reflection trace (nonexistent name) — errors surface honestly.
- Original task timelines unchanged; reflection rows absent from session history.

## C. Reflection → revision — PASS with caveats

| Case | Result |
|---|---|
| C1 `changed` | `eta-estimator`: reflection run `1525838b` staged a corrected `SKILL.md`, published **rev 2** (`dd3e4b7e`), `source_run_id` = reflection run, live file updated with valid frontmatter + corrected procedure |
| C2 `no_change` | Trivial session → reasoned `no_change` with grounded final message; no file churn |
| C3 built-in → local override | **Partially verified.** Built-in flaw was diagnosed correctly by the reflection, but the model concluded `write_file` couldn't shadow a built-in → `no_change`. The override *machinery* is proven: the task run itself wrote `skills/skill-creator/` → drift scanner pinned `agent-local` rev-1; repo `skills/skill-creator/` bytes untouched (`git status` clean); `skill_revisions` holds both `built-in` seed and `agent-local` rows. Reflection-model-driven override authoring not demonstrated live — prompt-comprehension gap (see Notes) |
| C4 no activation from reflection | Reflection runs that called `skills_load` created **zero** `skill_activations` rows |

**Rollback integrity:** a reflection that staged body-only content (no YAML frontmatter) failed `validate_skill_dir` → outcome `failed`, `SkillError` recorded, original file restored byte-identical. Fail-closed confirmed live.

## D. Drift scanner — PASS (5/5)

| Case | Result |
|---|---|
| D1 mid-run `write_file` creates skill | `greeter` written by a task run → close pinned `agent-local` rev-1 "snapshot of live-dir change made outside a tracked edit", empty `source_run_id` |
| D2 manual edit + backend restart | Hand-appended line to `eta-estimator` → startup reconcile → **rev 3** snapshot logged `[skills] agent-local 'eta-estimator' drifted → snapshot rev-3` |
| D3 close with no changes | Repeated closes added no revisions to unchanged skills |
| D4 no dup after reflection publish | `eta-estimator` rev-2 (reflection-published) not re-snapshotted by later closes — hash match suppresses drift |
| D5 delete live skill dir | `rm -rf greeter/` → close → rev-1 history preserved, no new row, no error |

## E. Isolation / honesty — PASS

- Reopened sessions show task messages only; zero reflection content leaked into chat history.
- Session summaries cover task runs only.
- Reflection excluded from `skill_activations` (C4) and runs under `trigger=reflection`, out of normal memory learning.

## F. Failure resilience — PASS with plan divergence

| Case | Result |
|---|---|
| F1 provider broken before close | **Divergence from plan text:** close itself fails (`InternalServerError` in sweeper log), session stays `active`, **no** `skill_reflections` row created — consistent with documented memory semantics ("provider failures leave the session open"). Resilience holds via retry: after restoring the provider, the close committed and reflection ran (`no_change`). Plan text ("close still commits … reflection failed") does not match implementation; implementation is the safer behavior, plan doc should be corrected |
| F2 restart mid-reflection | Caught a live `running` row (`f1b4c6d7`), `kill -9` → restart → startup reconcile marked it `failed`/`interrupted` |

## Automated-only cases

Not attempted manually, per plan: publish conflict timing (`test_skill_edit_session.py`), per-turn caps + fingerprint dedup (`test_skill_reflection.py`), frozen-scope paging (`test_skill_evidence_queries.py`), drift hash consistency (`test_skill_drift.py`), activation rows (`test_skill_activations.py`).

## Reflection outcome histogram (live QA)

`changed` 1 · `no_change` 13 · `failed` 2 (frontmatter-validation publish fail + killed-mid-flight)

## Notes / follow-ups (not defects filed)

1. **Frontmatter prompt gap:** `skills_load` returns frontmatter-stripped `body`, and `REFLECTION_SYSTEM_PROMPT` never tells the model that a rewritten `SKILL.md` must keep required frontmatter → a correct-prose rewrite is structurally doomed to validation failure. Worth a prompt line or `skills_load` returning the raw file.
2. **C3 model behavior:** reflection correctly diagnosed the built-in gap but believed `write_file` couldn't create an agent-local override. The prompt states writes stage to `skills/{name}/` and shared skills may become local overrides — model comprehension gap, not implementation; machinery verified via the drift path.
3. **F1 plan/impl divergence** as detailed above.
4. Symlinked-root guard surprise under `/tmp` on macOS (setup only).

## Cleanup

QA backend + Vite killed; browser session closed; `/tmp/agentos-qa-gPM8` tree removed (QA DB, workspaces, skills-store, drafts, logs). Main DB/providers untouched (read-only copy source). Repo worktree unchanged by testing (all W15 modifications are the implementer's own uncommitted work).
