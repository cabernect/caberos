# W10 Test Plan - Observability

## Scope And Status

Branch: `feat/v0.2.0-observability`.

This is a test plan, not a test-results report. Creating it does not authorize
running paid model calls, modifying real data, restarting services, committing,
or pushing. Record the tested commit and working-tree state when executing.

Cover the unified model ledger, pricing coverage, exact call correlation,
redacted run detail, filters, trace explorer, and Agent/Platform spend views.
Release hardening remains the final workstream: security workflows, signed
artifacts, updater delivery, release packaging, and release gates are excluded.

Current capability boundaries must remain visible:

- Model-call request/response bodies and instrumented span boundaries are not
  captured, including for new calls. Run messages are not the full model prompt.
- Waterfall placement inferred from receipt timestamps and latency is derived,
  not an observed start/end pair. Unknown timestamps stay unpositioned.
- Fast tools do not have durable generic pending/running records.
- Legacy unlinked records cannot be joined or merged by timestamp guesses.
- Plan linkage, model fallback events, and browser-session filters are deferred.
- Unknown historical prices cannot be reconstructed from a custom model alias.

## Safety And Environments

1. Reuse the real web stack only for read-only inspection: frontend `:5173`,
   backend `:8081`, database `backend/data/agentos.db`.
2. Do not replace the normal backend with a QA database. Use an isolated test
   database and a different backend port, such as `:8082`, for mutations.
   Ensure the QA frontend/API proxy targets that port; otherwise do not proceed.
3. Unit/API fixtures use disposable databases and mocked/scripted providers.
   Do not send model requests, approvals, terminal commands, notification
   actions, or scheduled jobs from the real browser session.
4. Never touch the desktop application's separate database. A desktop smoke
   test needs a separately approved build and an isolated application profile.
5. Migration testing runs against an SQLite backup copy, never the live source.
   Use SQLite's backup API for a consistent WAL-aware snapshot, not a lone
   filesystem copy of an active `.db` file.
6. Do not put tokens, API keys, private prompts, or real tool bodies in reports.
   Protect screenshots and captures; keep private artifacts out of Git.

## Execution Order

1. Targeted backend and frontend regressions.
2. Disposable-fixture API checks and copy-only migration checks.
3. Real-data read-only reconciliation and browser QA.
4. One final CI-equivalent gate on the exact candidate tree.
5. Publish results separately; ask before committing or pushing.

Stop on a secret leak, incorrect cost classification, wrong database connection,
misjoined events, migration data loss, or fabricated input/output or timing.

## Automated Commands

Run from the repository root; the subshells keep directories unambiguous.

```bash
(cd backend && uv run pytest -q \
  tests/test_model_call_migration.py \
  tests/test_system_accounting.py \
  tests/test_correlation.py \
  tests/test_observability_timeline.py \
  tests/test_observability_redaction.py \
  tests/test_platform_spend.py \
  tests/test_run_filters.py \
  tests/test_observability.py)

(cd backend && uv run pytest -q tests/test_harness.py \
  -k 'responses_cost_recipe or responses_stream_no_completed_event_unknown_cost or response_cost_rejects_nonfinite')

(cd frontend && npx vitest run \
  src/components/RunTimeline.test.tsx \
  src/lib/traceLayout.test.ts \
  src/pages/Observability.spend.test.tsx \
  src/lib/api.test.ts \
  src/lib/toolStatus.test.ts \
  src/components/DashboardSidebar.test.tsx)
```

Final gate, matching `.github/workflows/test.yml` plus frontend unit tests:

```bash
(cd backend && uv run ruff check src/ tests/)
(cd backend && uv run ruff format --check src/ tests/)
(cd backend && uv run pytest -v --tb=short)
(cd frontend && npm run test)
(cd frontend && npm run lint)
(cd frontend && npm run build)
```

Use the existing lockfiles and documented CI environment. Linux sandbox tests
require the CI system dependencies. A local platform skip is not a pass; record
skips and verify the applicable Linux gate in CI. Rust/Tauri checks are additional
only if gateway, bindings, or desktop code changes; no release build is implied.

## Fixture Matrix

Use deterministic timestamps and fresh disposable fixtures. Extend existing
fixtures if a required case is missing; the presence of a test file is not proof
that every case below is covered.

### Pricing Fixture

The existing `test_platform_price_and_thinking_coverage_preserve_reported_zero`
provides this six-call, runless matrix:

| Call | Cost | `detail.cost_source` | Thinking | Kind | Expected pricing |
|---|---:|---|---:|---|---|
| Provider zero | 0 | `provider` | 0 | chat | Priced |
| LiteLLM zero | 0 | `litellm` | NULL | embedding | Priced |
| Legacy positive | 2 | Absent | 2 | chat | Priced, recorded value retained |
| Legacy zero | 0 | Absent | NULL | chat | Unpriced |
| Unknown zero | 0 | `unknown` | NULL | chat | Unpriced |
| Unclassified zero | 0 | Unrecognized source | NULL | chat | Unpriced |

Each call has 10 input and 5 output tokens. Expected totals: 6 calls, 0 run IDs,
recorded cost 2, 60 input tokens, 30 output tokens, 3 priced, 3 unpriced,
thinking sum 2, and 2 calls reporting thinking. Thinking is not added to output.
Filtering to embedding leaves one priced zero-cost call and no reported thinking.
An empty selection has zero coverage counts and NULL thinking.

Also exercise isolated all-unpriced, fully priced zero, and partial-pricing
responses. Add excluded test-run and out-of-window rows, a runless call, an
orphaned run reference, and the same model name served by different providers.
Count distinct non-null recorded run IDs, including orphan references; do not
describe that count as the number of surviving run rows.

### Trace Fixtures

| Fixture | Required observations |
|---|---|
| Simple run | Start, manifest, one generation, finish, user/assistant messages |
| Concurrent tools | Same capability with distinct call IDs and overlapping recorded durations |
| Nested domains | Approval/decision, terminal/completion, retrieval/citation, artifact, notification/delivery |
| Parent/sub-agent | Same call ID in different sub-agent scopes |
| Legacy/ambiguous | NULL call IDs, absent timestamps, duplicate audit roots, missing parent |
| Non-success | Denial, runtime error, timeout, interruption, failed run |
| Active run | Start and available observations, no fabricated completion |
| Malformed/private | Non-object payloads, large nested structures, planted canary secrets |

## Backend And API Acceptance Cases

| ID | Scenario | Required result | Existing test surface |
|---|---|---|---|
| A01 | Chat, embedding, validation probe, memory extraction, title | Exactly one receipt per actual request; correct kind/purpose/provider/model/context | System accounting, harness; embedding integration must also be verified |
| A02 | Cost precedence | Provider zero wins; accepted hidden response cost precedes LiteLLM fallback; unavailable pricing remains unknown | System accounting, harness cost tests |
| A03 | Bad cost/usage | Negative/nonfinite/malformed cost rejected; no token estimates; NULL and reported zero remain distinct | System accounting, harness |
| A04 | Failure and bookkeeping | Timeout vs error preserved; receipt-write failure does not fail the primary operation | System accounting; add failure-injection coverage if absent |
| A05 | Spend scope | Default Agent response unchanged; Platform includes runless/orphan rows, excludes identified test runs | Platform spend, observability |
| A06 | Pricing/usage coverage | Six-call matrix matches; each breakdown partitions the same selected calls | Platform spend |
| A07 | Filters and boundaries | Combined model predicates match one call, not different calls; no duplicated runs; inclusive since/exclusive until | Run filters, platform spend |
| A08 | Domain/audit filters | Agent, trigger, schedule, channel, capability, status, effect, browser profile, artifact format, retrieval mode/degradation, time, audit outcome/call/sub-agent | Run filters, timeline API tests; verify each supported parameter |
| A09 | Exact correlation | Join only exact call/sub-agent pairs within the run; no cross-scope or ambiguous attachment | Correlation, timeline |
| A10 | Durable timeline | Deterministic order; real transitions; active run has no finish; failed run keeps failed status | Timeline |
| A11 | Read-boundary privacy | Canary absent from the entire response, including flat lists, labels, messages, manifest, model detail, args/results/browser data | Redaction, timeline API tests |
| A12 | Bounding and malformed input | Secrets removed before bounding; valid structured JSON; recursive secret extras removed; counters retained; no 500 | Redaction, timeline |
| A13 | Access control | Unauthenticated detail/spend/audit requests rejected; unknown run returns documented not-found behavior | Observability; add missing endpoint assertions |

For A06, reconcile counts and recorded costs independently for `by_kind`,
`by_provider`, `by_model`, and `by_agent`. Do not add the different breakdowns
together. Do not require Platform spend to equal historic Agent/run spend.

## Migration And Lifecycle Acceptance

Run `test_model_call_migration.py` first, then repeat against a backed-up real
development database copy without starting the application scheduler/providers.

- M01: Capture original model-call IDs and every common legacy column. Rebuild
  nullable run/agent references; compare all captured values exactly.
- M02: Preserve orphaned run references. `run_id` stays indexed but has no
  enforced run foreign key. Runless inserts succeed.
- M03: Initialize twice; the second initialization changes neither rows nor IDs.
- M04: Inject create/copy failures in disposable fixtures. The savepoint restores
  the original schema and data; no half-migrated table survives.
- M05: Verify indexes and `PRAGMA integrity_check = 'ok'`. Compare foreign-key
  violations before/after; do not attribute pre-existing violations to migration.
- M06: The pre-release `embedding_calls` table is removed as agreed. This is not
  a promise to migrate its rows; retain the backup for inspecting old dev data.
- M07: Prove the source was never opened for migration or writes. Compare the
  captured source baseline where the source is quiescent; active-user writes
  must be distinguished from test mutations, not silently ignored.
- M08: In an isolated fixture, deleting a conversation still explicitly deletes
  associated model-call rows. Removing the FK does not preserve deleted receipts.

Record the source/copy paths, baseline capture, row comparison, integrity result,
idempotence result, and failure-injection evidence. Existing historical evidence
is reference material, not a substitute for checking the candidate migration.
PostgreSQL constraint removal is mock-tested; mark live PostgreSQL verification
as unexecuted unless it is actually run against an isolated PostgreSQL database.

## Browser QA

Use the actual Traces and Overview pages at desktop widths 1440 and 1024, tablet
768, and mobile 375. Exercise both light and dark themes, and confirm the resolved
theme in the DOM/computed styles rather than trusting screenshot filenames.
Use browser automation and inspect screenshots, network failures, and console
errors. Capture the component under test in view, not just the top of the page.

| ID | Action | Expected result |
|---|---|---|
| T01 | Open a simple real run | Run envelope plus recorded generation; no invented tools; default inspector shows model/provider/usage |
| T02 | Select root Input/Output and generation Input/Output | Root shows labelled run messages; generation explicitly states request/response not recorded |
| T03 | Inspect overlapping/nested fixture | Durations preserved; ruler and bar tracks align within 1 CSS pixel; nesting uses explicit parent IDs |
| T04 | Select tool/domain Input/Output | Projected args/results and actual decision status; no raw secret/private extras |
| T05 | Expand/collapse, parent jump, arrow keys, Enter | Selection and inspector agree; root collapses; focus visible; hidden rows do not remain selected |
| T06 | Search under collapsed parent; search no match | Matching descendants and ancestors visible; no-match feedback; clearing restores normal tree |
| T07 | Show events | Manifest and lifecycle markers appear without losing ordinary domain observations |
| T08 | Unknown/legacy/active records | Unknown time has no fake zero bar; legacy tool hints visible; model is not falsely unlinked; active run has no fabricated end |
| T09 | Switch run routes rapidly | No previous run's inspector, messages, or selected span shown as the new run |
| S01 | Platform, all-unpriced response | Primary spend Unknown, recorded amount separate, explicit unpriced count; never imply free |
| S02 | Fully priced zero / partial / empty | Valid zero shown as zero; partial amount labelled incomplete; empty selection distinguished from missing data |
| S03 | Thinking NULL / zero / partial reporting | Not reported vs 0; reporting-call coverage visible; no unsupported subset-of-output claim |
| S04 | Provider/model tables and filters | Human labels; distinct provider/model pairs; same-name providers disambiguated; filters submit IDs |
| S05 | Edit drafts, Apply, rapidly switch scopes/ranges, fail request | Applied labels match data; no stale totals; loading/errors distinct; Agent default unchanged |
| S06 | Older backend missing coverage fields | Recorded cost plus coverage-unavailable fallback; no guessed coverage |
| U01 | All widths/themes | No page-level horizontal overflow or overlapping text; local table/waterfall scroll usable; selected inspector accessible |
| U02 | Keyboard/navigation/console | Labelled controls, visible focus, readable status beyond color; back/list/detail navigation works; no unexpected console errors |

Measure text/header bounds for Calls, Cost, Pricing, and Thinking; checking only
page `scrollWidth` misses touching or overlapping table columns. Include long
model/provider names and multiple rows, not only a short single-row fixture.

## Real-Data Read-Only Check

Reference capture: `.scratch/w10-spend-evidence.json`. Its historical seven-day
selection had 31 calls, 12 recorded run IDs, 436,561 input tokens, 5,728 output
tokens, zero stored cost, and no pricing provenance on all 31 calls.

For replay, use that capture's exact `since` boundary and a stable snapshot.
For a current browser check, record the returned API window and verify the UI
against that response. Do not hard-code the historical counts as today's
expected totals; the sliding window and new activity can change them.

Inspect real data read-only. Reconcile the current API with a read-only ledger
query using identical filters, test-run exclusion, timezone, and boundaries.
Keep row bodies/private content out of evidence. This check must not reprice
rows or invoke providers. Paid/provider-reported billing checks are optional,
require separate permission and an isolated environment, and cannot prove
historic zero-cost calls were free.

## Completion And Results

Write execution results to
`docs/plans/v0.2/test_result/10-observability-test-results.md` only after testing.
For each case record PASS, FAIL, BLOCKED, or NOT RUN, with environment, actual
result, command/log/screenshot reference, and any missing automation.

Acceptance requires applicable automated gates and browser cases passing, no
unexplained accounting differences, preserved migration data, no secret leaks,
no fabricated telemetry, and explicit disclosure of remaining capture gaps.
No release or live-PostgreSQL verification may be claimed from this plan alone.
