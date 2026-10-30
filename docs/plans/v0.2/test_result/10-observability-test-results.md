# W10 Test Results — Observability

**Run:** 2026-10-07
**Branch / tested code:** `feat/v0.2.0-observability` @ `d4de121` (includes merged W8 scheduler + W9 notifications) + uncommitted W10 worktree (37 modified + new `services/model_ledger|observability_*|redaction|tool_status`, frontend `RunTimeline`/`TraceInspector`/`TraceWaterfall`/`traceLayout`, spend view).
**Environment:** macOS; real stack restarted on W10 tree — backend `:8081` (real DB, read-only) + isolated QA backend `:8082` on a SQLite-backup copy (`/tmp/w10-qa/agentos.db`) per plan §Safety-2; frontend `:5173` (vite, live worktree). Browser via agent-browser. No paid model calls made; no approvals/terminal/notification actions or scheduled jobs sent from the browser session.

## Verdict

**CLEAN.** All gates green; ledger, spend coverage, filters, correlation, redaction, timeline, and both spend scopes verified against real data and a migrated real-data copy. No defects filed. Boundaries (uncaptured bodies, derived placement, unmergeable legacy rows) are honestly disclosed in UI and API.

## Gates

| Command | Result |
|---|---|
| backend `pytest` W10 files (migration, system_accounting, correlation, timeline, redaction, platform_spend, run_filters, observability) | **90 passed** |
| `test_harness.py -k 'responses_cost_recipe or responses_stream_no_completed_event_unknown_cost or response_cost_rejects_nonfinite'` | **4 passed** |
| frontend vitest (RunTimeline, traceLayout, Observability.spend, api, toolStatus, DashboardSidebar) | **42 passed** |
| `ruff check` + `ruff format --check` | clean |
| **full backend suite** | **950 passed** (109 s) |
| `npm run test` (all) | **104 passed / 18 files** |
| `npm run lint` | warnings only (pre-existing exhaustive-deps in previews/) |
| `npm run build` | ✓ built 6.4 s |

## API acceptance

| ID | Result | Evidence |
|---|---|---|
| A01 receipts | PASS | Run `880fba86` (real): 5 ledger rows ↔ 5 generation spans; ledger tokens 99,976/1,113 = run totals exactly; call latencies (25.0 s) < run latency (73.0 s) — tool time accounts for the gap. Kinds/purposes/status recorded (`chat`/`reasoning`/`ok`). Embedding-kind receipt path is unit-covered (test_system_accounting); not exercised live (no paid calls). |
| A02 cost precedence | PASS (unit) | `test_system_accounting` + harness cost `-k` tests cover provider-zero / hidden-response-cost precedence / unknown stays unknown. |
| A03 bad cost/usage | PASS (unit) | Same suites: nonfinite/malformed rejected; NULL vs reported-zero distinct (verified live too: `thinking_tokens:null` surfaced as "Not reported", not 0). |
| A04 failure/bookkeeping | PASS (unit) | system_accounting covers receipt-write failure isolation; live: 51 failed runs retain `status=failed` + `run_completed{status:failed}` tail item. Some legacy failed runs have `error:null` — faithful reporting of unrecorded errors, not fabrication. |
| A05 spend scope | PASS | `GET /api/spend?scope=platform&days=7` → 31 calls / 12 runs / 436,561 in / 5,728 out / $0.00 recorded / 0 priced / 31 unpriced — **matches `.scratch/w10-spend-evidence.json` exactly**; footer states run-vs-ledger scopes count different things. |
| A06 pricing coverage | PASS | Response reconciled 1:1 against a direct read-only ledger query on the QA copy (identical filters): 31 calls, 12 distinct run_ids, 436,561/5,728 tokens, cost 0.0, thinking NULL→"Not reported", cached 302,329. Breakdowns by_kind/by_provider/by_model each partition the same 31 calls. Six-call fixture matrix is unit-verified (test_platform_spend). |
| A07 filters/boundaries | PASS | `since` inclusive, `until` exclusive (probed at a run's exact `started_at` ±1 ms — included/excluded/included correctly); combined `agent+status+trigger` → 123 runs all matching. |
| A08 domain filters | PASS | `provider_id`/`model`/`kind`/`capability`/`tool_status`/`artifact_format=pdf`/`is_test`/`status` all apply correctly (real values match, bogus values → 0). `channel`/`effect`/`browser_profile`/`retrieval_*`/`schedule_id` accepted, 0 rows (no matching real data). `/api/audit` paginates. Full param matrix is unit-covered (test_run_filters). |
| A09 exact correlation | PASS (mixed) | Timeline `model_call:{ledger_id}` ids join **exactly** to `model_calls[].id` (5/5). Legacy runs show audit-sourced + event-sourced tool spans separately — audit `call_id` is NULL for all 441 existing rows → documented "unlinked … not merged" boundary (no timestamp guessing). New-call joins unit-covered (test_correlation); not exercised live. |
| A10 durable timeline | PASS | Deterministic insertion ordering stable across refetches; completed run ends `run_completed`; failed run keeps `failed` status; real transitions only. |
| A11 redaction | PASS | Planted `sk-ant-…`-shaped canary in audit args (incl. nested), result, message body, and model_call detail on the QA copy → **0 occurrences** in `GET /api/runs/{id}` (walked entire payload). Non-secret-shaped strings pass through by design (pattern-based redaction — correct scope). |
| A12 bounding/malformed | PASS | `truncated`/`redacted` flags present on bounded payloads; secrets scrubbed before bounding per contract; no 500s on legacy/malformed rows. |
| A13 access control | PASS | Unauthenticated `/api/runs`, `/api/runs/{id}`, `/api/spend`, `/api/audit`, `/api/operator-audit` → all **401**; unknown run → **404**. |

## Migration (M01–M08)

Run against a byte-level copy of `backend/data/agentos.db.bak-w7retest` (pre-W10 schema: `model_calls` 266 rows, 17 cols, FK `run_id→runs`) via the app's own `init_db()` — never the live file.

| ID | Result | Evidence |
|---|---|---|
| M01 exact preservation | PASS | 266→266 rows, identical ids, **0 value mismatches** across all 17 shared columns; new cols `kind/purpose/thinking_tokens/detail` added. |
| M02 orphan refs | PASS (schema) | `model_calls` FK removed (post-migration `foreign_key_list` empty), `run_id` still indexed (`ix_model_calls_run_created`); runless inserts allowed. Backup had 0 orphan rows — injected-orphan case is unit-covered. |
| M03 idempotent | PASS | Second `init_db()` — 266 rows, no changes. |
| M04 savepoint rollback | PASS (unit) | test_model_call_migration injects create/copy failure → savepoint restores. |
| M05 indexes/integrity | PASS | `integrity_check=ok` post-migration; expected indexes present. |
| M06 embedding_calls | PASS | Table absent post-migration (`DROP IF EXISTS`); was already absent in the W7 backup — drop verified on live DB too. |
| M07 source untouched | PASS | Migration ran only on `/tmp/w10-qa/pre-migration.db`; `.bak` source not opened by the app. |
| M08 cascade delete | PASS (unit) | Conversation-delete still removes model_call rows (test suite). Live PostgreSQL path: **not executed** (mock-tested only, per plan). |

## Browser QA (agent-browser, real :5173)

| ID | Result | Evidence |
|---|---|---|
| T01 | PASS | Run `880fba86`: envelope "Run 1.2m" + 5 recorded generations (`OpenAI / gpt-6-luna`), no invented tools; inspector shows model/provider/usage/status. |
| T02 | PASS | Generation Input/Output: "Per-call request/response was not recorded — only usage metadata is captured…" + "View run messages" link; root shows run messages as labelled messages, not model prompt. |
| T03 | PASS | Durations preserved (2.28 s/7.70 s/19.83 s/17.99 s + generations 3.18–6.75 s); ruler ticks 0 ms→1.2 m share `extentMs` with bar math (no independent check detected drift); waterfall scrolls locally at 375 px. |
| T04 | PASS | Unlinked `web_fetch` span: status `complete`, `truncated` flag, projected fields (OFFSET/URL/MAX_CHARS) + Output tab projects CONTENT/TITLE/HAS_MORE/TOTAL_CHARS — structured fields, not raw JSON; no secrets. |
| T05 | PASS | Root collapses/expands; Arrow keys move selection; `aria-selected` tracks inspector; hidden rows can't stay selected (`effectiveSelected` falls back to first visible). |
| T06 | PASS | Search "web_fetch" → root + 2 matching descendants; "zzz" → "No matching observations."; clear restores full tree (17 items with events on). |
| T07 | PASS | "Show events" reveals manifest/lifecycle markers without dropping domain spans. |
| T08 | PASS | 4 audit-only tool spans render "unlinked · Unknown time" — `at:null`, `estimated_time:true`, no fake zero bars; active-run fabrication absent (no active runs in data; boundary covered by timeline code path). |
| T09 | PASS | Rapid A→B→A run switching — header/inspector show the final run (`303c1b8d`, correct token totals), no stale B payload. |
| S01 | PASS | Platform scope: "**Actual spend is unknown: 31 of 31 calls lack pricing data.**" + SPEND `Unknown` with `$0.000000 recorded` separately — never implies free. |
| S02 | PASS | Empty selection (`model=nonexistent-model-xyz` → Apply) renders `RECORDED COST $0`, `CALLS 0`, `none` rows — distinct from missing-data state; fully-priced-zero case unit-covered. |
| S03 | PASS | THINKING TOKENS "Not reported" (NULL≠0); "THINKING REPORTED 0 of 31 calls" coverage line — no subset-of-output claim. |
| S04 | PASS | BY MODEL/PROVIDER/KIND tables with human labels, `unpriced` pricing column, Thinking column; filters submit `model=`/`provider_id=` params (verified in request URL). |
| S05 | PASS | Draft edits stage locally; Apply submits; `requestKey` guard prevents stale-payload-under-new-labels; loading state clears `view` immediately. Failed-request path → "Couldn't load spend data." (code-verified). |
| S06 | NOT RUN (env) | Older-backend missing-coverage-fields fallback is unit-covered (`Observability.spend.test.tsx`); no old backend was stood up. |
| U01 | PASS | `documentElement.scrollWidth == innerWidth` at 1440/1024/768/375 on both Overview and Traces — no page-level overflow; waterfall keeps local horizontal scroll; cell-pair overlap check: 0 touching cells. |
| U02 | PASS | Labelled controls (aria-labels/roles present), visible focus, keyboard tree nav works, back/list/detail nav works, **0 console errors** across the whole session. Both themes verified via DOM: `data-theme=dark` bg `rgb(21,24,17)` and `data-theme=light` bg `rgb(245,245,243)`. |

## Real-data read-only check

- `GET /api/spend?days=7&scope=platform` on the QA copy reproduced the reference capture **exactly**: 31 calls, 12 runs, 436,561 in / 5,728 out, recorded cost 0.0, all 31 lacking pricing provenance. Independent ledger SQL on the same copy returned identical totals — no unexplained accounting difference. (The capture's `since` instant rolled forward from `02:28` to `03:18` — sliding 7-day window; selection contents unchanged.)

## Scope notes / not run

- No paid/provider model calls; receipt-write paths for *new* calls (post-call-id-instrumentation joins) are unit-covered but not live-exercised — all real rows predate `audit_records.call_id`.
- `is_test` exclusion verified by unit tests; QA data contained 0 test runs post-W8 cleanup.
- Live PostgreSQL migration path not executed (per plan — mock-tested only).
- QA instance `:8082` shares the real config → it connected to real MCP servers at startup (no DB writes result; noted, killed at cleanup).
- `error:null` on some legacy failed runs = faithfully unrecorded errors, not a UI defect.

## Cleanup

- `:8082` QA backend killed; `/tmp/w10-qa/` (QA DB copy + pre-migration copy) deleted — all canary/mutation state confined to disposables.
- Real DB: only writes were the minted `w10-real-*` operator session (deleted → 401 verified) and the W10 schema migration itself (expected — required to serve the feature; 266→266 rows verified preserved).
- WAL checkpointed, `integrity_check` ok, `:8081` healthy on the W10 tree. Browser session closed. Theme restored to System. Nothing committed.
