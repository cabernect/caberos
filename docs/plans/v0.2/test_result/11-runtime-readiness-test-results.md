# W11 Runtime Readiness — Test Results

**Current closeout status (2026-10-13):** confirmed B1/B30 residual defects, B48 notification gap, and B49 cancellation bookkeeping fixed. The prior full backend gate passed 1121 tests before B49; the frontend gate passed 164 tests. B49's focused verification is recorded below. The independent report records approved real Node/uv installs on macOS ARM64; Git real-install verification remains incomplete. Install-dialog UI is operator-verified; no additional UI rerun is required. Historical slice reports below are retained and do not define remaining scope.

**Scope of this report:** Track A — model catalog foundation, execution
accounting glue, and receipt read projection. This is a *slice* result, not
whole-W11 completion: dependency installation, remaining catalog/accounting
acceptance items, and the remaining defect inventory are still pending.

## Verified slice

| Area | Evidence | Result |
|---|---|---|
| Catalog store/discovery/offering reads/revisions | `backend/tests/test_catalog.py`, `test_catalog_policy.py`, `test_model_catalog.py` | green — included in the combined gate below (no standalone count claimed) |
| Execution accounting glue — capture-before-RPC, frozen receipts, canonical usage (chat complete/stream, responses complete/stream, embeddings, compaction summary, provider probe) | `backend/tests/test_call_accounting_glue.py` (14 tests) + `test_system_accounting.py`, `test_harness.py`, `test_compaction.py` | green |
| Receipt read projection — `services/accounting_projection.project_call_detail` whitelists `cost_assessment`/`rate_authority` for run-detail `model_calls[].detail` and timeline `model_call` events | `tests/test_observability_timeline.py::test_receipt_projection_whitelist_run_detail_and_timeline` + `test_observability*.py` | green; canary never leaks at either seam |
| Combined backend gate | `.scratch/w11/final-slice-gate2.log` | **217 passed** (call_accounting, cost_assessment, usage_receipts, catalog, catalog_policy, model_catalog, harness, system_accounting, compaction, platform_spend, providers, observability ×3, glue) |
| Backend static checks | Ruff check and format check | clean; 258 files already formatted |
| Frontend catalog UX | `ModelCatalog/ModelCatalogCard/SettingsOverlay/api` focused Vitest + build + lint | 31/31 green; isolated-stack browser QA at 375/1440 light+dark, no overflow, 0 console errors (`.scratch/w11/ui/catalog-375-card-v3.png`, `catalog-1440-dark-v3.png`) |

## Known limitations

- **Receipt safety:** run-detail and timeline expose projected rate provenance
  and nullable usage counters. Only model-call events use the scoped sanitizer
  allowance; nested credentials and unapproved fields remain redacted.
- **Tier basis:** native OpenAI catalog pricing now captures
  `context_tier_basis == "aggregate_input"` (see the cost regression below);
  other unsupported bases, audio
  billing, and nonstandard cache lifetimes assess as `unknown` rather than
  guessed.
- **Unknown budget policy:** unresolvable input budgets allocate the
  documented `32768` fallback; known context/output conflicts raise
  `ValueError` (422 on the manual API) instead of silently allocating.

## Verified slice (continued)

| Area | Evidence | Result |
|---|---|---|
| Dependency readiness — status/resolve for nodejs/uv/git/libreoffice/chromium; override→system→managed order; strict managed-pointer validation; bounded health probes; macOS git-shim guard; Windows cli.js wrapper policy | `backend/tests/test_dependencies.py` | **27 passed** — `.scratch/w11/dependency-readiness-tests.log` |
| Operator API `GET /api/dependencies` + `POST /recheck` (operator-only, 401 unauth) + General "Optional Tools & Runtimes" card | `tests/test_dependencies.py::test_dependencies_api_*`; `frontend/src/components/OptionalToolsAndRuntimes.test.tsx` | 6 component tests green; build+lint clean; 375/1440 browser QA, 0 console errors (`.scratch/w11/ui/deps-{375-actual-light,1440-actual-dark}.png (theme-verified; see deps-theme-evidence.json)`) |

## Test cleanup — retired catalog card + focused coverage (W11 follow-up)

- `ProvidersSettings.tsx`: the unmounted `ModelCatalogSettings` function is deleted
  (General already carried no card); `ModelCatalogCard.test.tsx` (11 tests) retired
  with it — the General page test (2) still proves the card is gone.
- `test_catalog.py`: `TestIdentity` helpers + the two `resolve_fields` unit tests
  removed; their unique assertions moved into `test_catalog_policy.py`
  (proxy/custom mapping, catalog-model-only-≠-mapping, explicit alias, vision/think
  override wins + per-authority provenance, input-limit catalog field, unknown
  provenance) — `test_model_catalog.py`'s projection cases kept (different public
  contract).
- `notificationStore.test.ts`: the fallback test rewritten — attempt 1 HELLO→EOF,
  attempt 2 held pending; fallback ticks exactly once per 5 s while unhealthy,
  then HELLO lands → one catch-up → silence; proves the poll only runs between
  disconnect and HELLO.
- Counts: backend catalog/model-catalog/policy **35**; frontend (ModelCatalog +
  General + store + api) **45**. Logs: `.scratch/w11/test-cleanup-{backend,frontend,build,lint}.log`.
- Mutant negative control: the lead's FIXED standalone config disables the
  store's fallback via a vitest-only transform — running the rewritten test
  under it fails `expected 2 to be 3` (the fallback GET never fires → the
  test genuinely exercises the poll; `.scratch/w11/test-cleanup-new-mutant-fixed.log`).
  The earlier config draft failed at load (Tailwind plugin interop) — no
  old-test-pass proof exists; the lead's fix is what produced this evidence.
  Normal config: green.
- General UI verified read-only: no catalog heading/refresh control; Optional
  Tools intact; identical layout to the accepted screenshots.
- Recovery incident: during this cleanup an accidental `git checkout` reverted
  ~370 lines of uncommitted W11 edits on `ProvidersSettings.tsx`. Recovery was
  mechanical from frozen artifacts (`.scratch/w11/ProvidersSettings.earlier-w11.diff`
  + `ProvidersSettings.original-guards.patch` + frozen tool-history rows): the
  ModelsTab `mounted` ref/guards, ProviderCard `discoveryLifecycle`/generation
  guards, and OptionalTools mount are restored — the EXACT pre-clobber byte
  image is unavailable, so the file is restored-to-known-hunks, NOT
  byte-identical. `ProvidersSettings.pre-cleanup.tsx` is the earlier
  intermediate state, not a true snapshot.

## Unused catalog UI cleanup (W11 follow-up)

- Retired the orphaned maintenance helpers — `api.ts`: `getModelCatalogStatus`,
  `setModelCatalogAutoRefresh`, `refreshModelCatalog` + `ModelCatalogStatus`
  import; `types.ts`: the `ModelCatalogStatus` DTO. Backend
  `/api/settings/model-catalog*` stays public/operator (daily worker, offline
  pinned snapshot, honest state); only the dead client-side card surface went.
- `ProvidersSettings.general.test.tsx`: removed the 3 dead-method mocks + the
  tautological "endpoints never called" test; added a
  `queryByLabelText(/refresh catalog/i)` null assert to the existing UI test.
- Recovered `ProvidersSettings.tsx` frozen first:
  `.scratch/w11/ProvidersSettings.recovered-before-orphan-cleanup.tsx`.
- Final counts: **44 frontend tests** (4 files); the label assertion is
  consolidated into the existing General UI test rather than a separate case.
  Backend **35** remains unchanged. Final frontend log:
  `.scratch/w11/catalog-orphan-cleanup-final-frontend.log`; build/lint:
  `.scratch/w11/catalog-orphan-cleanup-{build,lint}.log`.

## Dependency job monitor + MCP stale-runtime guard (W11 follow-up)

- `OptionalToolsAndRuntimes.tsx` + `api.ts`: install-job monitor now runs **one**
  jobs snapshot on mount/revision and polls at 2 s **only while active jobs exist** —
  an idle card holds zero timers; a failed GET retries at 4 s only when known-active
  jobs remain; explicit Re-check re-runs readiness + one jobs snapshot; `onStarted`
  (non-terminal) restarts the monitor. `listDependencyJobs` accepts an `AbortSignal`.
- `mcp/client.py`: a stale cached runtime pointer (operator removed the managed
  install after the health check) is detected post-warm — one forced `status(force=True)`
  re-check; the ready-guard now requires a **current, executable** verified file, so
  a removed managed runtime fails actionably instead of silently falling back to a
  legacy/incompatible system binary.
- Final polish: per-request `AbortController` + 15 s release on jobs GETs (timeout
  → error + 4 s retry only while active); integrated card+dialog flow test (install
  wakes monitor → queued → terminal → stops); MCP companion sweep — ANY stale
  cached runtime (removed git while uvx valid) → one forced re-check, env drops
  the dead dir; ready-guard moved before the resolver.
- Tests: backend `test_dependencies` 27 + `test_mcp_stdio_resolver` 17 + `test_mcp` 32
  = **76** (3 stale-path connect tests, red on pre-fix); frontend card/dialog/General
  = **24** (5 new monitor tests; idle-failure spec updated to explicit Re-check).
- RED proof: `.scratch/w11/dependency-poll-{red,mcp-red}.log`; gates:
  `.scratch/w11/dependency-poll-{backend,frontend,build,lint}.log`.
- Limitations: no managed "Uninstall" UI exists — removal is per-user and the
  readiness card shows last-checked status until Re-check/reopen; readiness is
  a snapshot, not a watcher; TOCTOU between guard and SDK is best-effort.

## Full pre-commit gate (2026-10-12)

- Backend: **1106 passed, 0 failed**; Ruff check passes and Ruff format check
  reports 263 files formatted. Evidence: `.scratch/w11/full-final-backend.log`
  and `full-final-backend-ruff-{check,format}.log`.
- Frontend: **156 passed across 24 files**; lint has no errors and the production
  build passes. Nonfatal hook/generator lint warnings and dependency deprecation
  warnings remain. Evidence: `.scratch/w11/full-final-frontend{,-lint,-build}.log`.
- The first full backend run found three failures. The existing embedding-ledger
  assertion expected only the old detail fields; it now checks those fields,
  exact normalized usage, unknown monetary assessment, and captured authority.
  Missing pricing remains `amount: null`, not a claim of free execution.
- Two live-browser tests timed out under an artificial temporary `HOME`.
  A control that previously passed also reproduced the timeout. Changing only
  `HOME` to the normal macOS home made all three browser tests pass; proxies,
  temporary app-data roots, and temporary Chrome profiles stayed unchanged.
  This proves the environment trigger, not a particular Chrome internals cause.
  Evidence: `.scratch/w11/browser-{control,normal-home}-comparison.log`.
- Final commands: backend `uv run --frozen --no-sync pytest -v --tb=short`,
  `uv run --frozen --no-sync ruff check src/ tests/`, and
  `uv run --frozen --no-sync ruff format --check src/ tests/`; frontend
  `npm run test`, `npm run lint`, and `npm run build`.
- Mutable `AGENTOS_*` roots point at disposable data, with local-only test
  servers and dead external proxies. No browser tests were skipped, no production
  browser code was changed for these failures, and no real binaries were installed.
  The temporary diagnostic plugin was removed; raw logs remain gitignored.
- This is an implementation checkpoint, not W11 closeout. Existing pending work
  remains. Review follow-ups include provider deselection during model loading,
  alignment of install-plan TypeScript fields with the public backend response,
  and explicit handling of invalid input-budget configuration in the harness.

## Model catalog — internal daily refresh (W11 follow-up)

- `pages/ProvidersSettings.tsx`: the General tab's `<ModelCatalogSettings/>` mount
  is removed — the catalog card, refresh button, and status/status-poll traffic
  are gone from the user-facing Settings screen. The exported component remains
  for now (unmounted).
- `backend/config.py`: `model_catalog_auto_refresh` defaults to **True** (lead-authored) —
  the catalog refreshes internally on the existing daily loop; `AGENTOS_MODEL_CATALOG_AUTO_REFRESH`
  or the persisted `app-settings.json` opt-out still wins (operator's saved `false` honoured).
- Tests: backend `test_catalog.py` 29 + `test_config.py` 18 = **47** (toggle fixture
  restores prior value; new default/env-opt-out/persisted/pin-priority tests);
  frontend General page test **2** + catalog card/component legacy 37 = **39**.
- Logs: `.scratch/w11/catalog-internal-{backend,frontend,build,lint}.log`;
  QA artifact `.scratch/w11/catalog-internal-qa.json` + screenshots
  `.scratch/w11/ui/general-no-catalog-{375-light,1440-dark}.png` — zero catalog
  status/refresh requests on General load.
- Limitations: real backend on :8081 not restarted (lead owns); the `ModelCatalogSettings`
  component stays in the bundle (dead path, tree-shaken candidates aside);
  Optional Tools' 2 s job poll is unchanged out-of-scope behavior.

## Notification polling — SSE-first (W9 follow-up fix)

- Backend `notifications.py` + `api/notifications.py`: `notify_inbox_changed()` posts a
  typed `inbox_changed` frame after commit on REST read/read-all (SQL unchanged);
  queue overflow posts a bounded invalidation marker instead of silently dropping.
- Frontend `api.ts`, `notificationStore.ts`, `crossTab.ts`, `pages/Notifications.tsx`:
  `streamNotifications(signal, onConnected, onInboxChanged)`; transport-epoch-guarded
  SSE loop + owned/abortable snapshot requests; sequential `setTimeout` fallback (5 s,
  15 s-bounded fetch) runs only while the leader stream is not HELLO-healthy;
  followers never poll; live rows merge into in-flight snapshots (no lost rows);
  the page uses `useNotifications()`/`useNotificationsLoading()` with no local timer.
- Tests: backend `test_notifications.py` **21**; frontend narrow **51**
  (store 23, api 9, page 3, prefs+focus 16).
- Logs: `.scratch/w11/notifications-sse-{backend,final-frontend,final-build,final-lint}.log`
  + raw network `.scratch/w11/notifications-sse-network.json` (isolated :15173/:18081,
  temp QA DB only; one real emit ever fired, on that QA DB).
- Limitations: leader crash/reconnect and cross-tab read sync are unit-covered,
  not live-verified; real backend on :8081 not restarted (lead owns).

## Managed installer slice

| Area | Evidence | Result |
|---|---|---|
| Installer engine `runtime_installer.py` — frozen plans, consent-gated jobs, bounded download + SHA-256 trust gate, safe tar.gz/zip extraction (traversal/device/symlink-escape/case-collision rejection), health-before-pointer, atomic activation, crash reconcile, cancel, per-dep locking | `backend/tests/test_runtime_installer.py` | **35 passed** |
| Operator API — `POST /plan`, `POST /install`, `GET /jobs`, `GET|POST /jobs/{id}[,cancel]` (owner-scoped, extra-forbid) | same file | API seams green; unauth 401 verified |
| MCP stdio wiring — registry-verified paths, `child_environment`, Windows cli.js wrappers, actionable missing-runtime error, remote untouched | `tests/test_mcp_stdio_resolver.py` | **44 passed** (incl. `test_mcp.py`) |
| Install dialog + card — consent gate, sequential polling, cancel, install buttons on installable rows only | `OptionalToolsAndRuntimes.test.tsx` + `RuntimeInstallDialog.test.tsx` | **16 passed** (9 dialog + 7 card); build+lint+prettier clean |

| Browser QA — mocked plan→consent→install→progress→cancel→terminal via intercepted REST | `.scratch/w11/ui/install-modal-375-preview-light.png`, `install-modal-1440-progress-dark.png` | verified, 0 console errors |
| Browser QA (isolated 18081/15173) — card renders, jobs list 200, 0 console errors, no overflow | live reload | verified |

Log: `.scratch/w11/installer-backend-tests.log`. **No real downloads or installs were performed** — all publisher/archive/health I/O is injected fixtures.

## Pending tracks (historical checkpoint — superseded by closeout status above; not active obligations)

- Dependency runtime installation for the approved recipes
  (`12-dependencies`) — recipe metadata is lead-authored and fixed;
  readiness/detection shipped here, but install path is
  implemented and consent-gated behind publisher checksums; **no real
  downloads/installs were exercised in QA** (all fixtures/mocks).
- Observability spend/metrics beyond the priced-source enum
  (`models_dev`/`user_rate`/`provider_rate`), whose 6 golden tests pass —
  no new metrics queries are planned in this slice.
- Backfill preview/apply is **excluded from W11** (operator decision
  2026-10-13) — existing receipts remain unchanged. Broader unsupported
  tier-basis pricing remains a stated limitation (honestly unresolved), not
  new mandatory math expansion. Real installer runs are **NOT exercised**
  pending operator consent.
- Remaining defect-inventory items in `11-bug-fixes.md` — B1 and B30 residual
  are now fixed (below); B2 startup reconcile and B3 native-tier fix verified.

## Caber zero-cost regression (2026-10-12)

- The latest real Caber run's frozen receipts contain valid token usage and
  OpenAI catalog rates, but assess as unknown with
  `reason: unsupported_context_tier_basis`. The legacy run scalar remains zero.
- Reproduced through real local catalog resolution and `capture_call_rates`,
  not a calculator test that manually supplies its missing basis. Runtime capture
  had never passed the basis that the existing tier arithmetic required.
- Native OpenAI catalog pricing now freezes aggregate prompt input as its
  context-tier basis, including cached input. Custom proxies, cross-provider
  mappings, and undeclared routing overrides do not inherit that billing basis.
  Unsupported pricing and usage remain unresolved.
- Three endpoint cases cover the default native endpoint, the official explicit
  API endpoint, and an explicitly mapped proxy; recorded cached/uncached usage
  and an above-threshold example use independent expected Decimal amounts.
- Full backend suite: **1109 passed**, before the final cross-provider guard
  tightening (`.scratch/w11/caber-cost-full-backend.log`). Final-code accounting
  suites: **19 passed** (`caber-cost-final-accounting.log`). Ruff check and format
  check pass (`caber-cost-final-ruff-{check,format}.log`). Frontend is unchanged.
- Frozen offline replay estimates the two main agent turns at **USD 0.00369824**
  and the auxiliary call at **USD 0.0004824**. These are catalog-based estimates,
  not provider invoices. No production costs were changed or model calls made.
- The running backend has not been restarted; it needs to load the fix before
  new tasks benefit. Existing unknown receipts are not automatically repriced.
  The conversation intentionally keeps its shared zero display — unresolved and genuine zero both render as $0.000 per the user's explicit choice; the unknown-vs-priced distinction lives in receipt-level accounting/observability.

## B1 undeclared-OAuth + B30 reconcile-note fixes (2026-10-13)

- **B1:** an HTTP MCP server with no declared `oauth_config` that answers the
  initialize POST with `401 + WWW-Authenticate: Bearer resource_metadata=…`
  is now observed (response hook on the existing SDK request — no extra probe,
  no metadata/token fetch, no browser redirect). On failure, the registry
  persists a default consent config (`scope: ""`, localhost callback
  `redirect_uri`), surfaces `OAuth authorization required — connect via
  dashboard` as the connect error, and emits an `Authorize {name}` warning
  notification — distinct from the expired-refresh `Reconnect {name}` error.
  A configured-OAuth server with no stored token gets the same clean guidance
  instead of a silent `False`. Negative challenges (Basic, bare 401, invalid
  or credentialed metadata URLs, 403/500) persist nothing.
- **B30:** `_reconcile_stale_occurrences` now appends the restart reason to an
  existing error note instead of overwriting it; running rows only, so a
  second startup does not re-append.
- Tests: `test_mcp.py` + `test_scheduler.py` + `test_mcp_oauth_refresh.py` —
  **93 passed** (`.scratch/w11/w11-b1-b30-fix-tests.log`); Ruff check/format
  clean on the five touched files. Excludes: no PATCH-auth metadata edit path,
  no auto OAuth flow, Git-MCP prep, backfill — unchanged.

## Explicit W11 exclusions (unchanged scope)

- **Backfill** (historical unknown-cost receipts): excluded — P10 snapshot
  invariance stays authoritative; existing receipts are not repriced.
- **Git MCP prep**: excluded.

## W11 closeout gate (2026-10-13)

- Full backend: **1121 passed** (`.scratch/w11/final-gate-backend.log`).
- Ruff `check src/ tests/` clean; `format --check` — 263 files already
  formatted (`final-gate-ruff-{check,format}.log`).
- Frontend: **156 tests passed**, lint warnings only (pre-existing),
  `npm run build` succeeded (`final-gate-frontend-{test,lint,build}.log`).
- Browser QA (real isolated QA stack :18081/:15173, current code): an
  oauth-configured HTTP server row presents `Connect OAuth` +
  `Reconnect`/`Remove` — consent control only, no automatic authorization
  or redirect. Desktop verified at 1440. At 375px the existing MCP header
  row pushes action controls off-screen — mobile consent usability is NOT
  verified; this layout limitation is recorded for the upcoming frontend
  rework. No frontend layout code was changed in W11. Screenshots:
  `.scratch/w11/qa-mcp-oauth-consent-desktop.png` (1440) and `-mobile.png`
  (375). No console errors. Real-API evidence (`GET /api/mcp/servers`):
  `auth_type:"oauth"`, persisted `oauth_config` with default scope +
  localhost callback `redirect_uri`.
- NOT exercised: real installer downloads — awaiting operator consent for
  Node 24.21.0 / uv 0.12.24 / Git 2.53.0 under `/tmp/w11-live-install-qa`.

## B48 notification baseline gap (2026-10-13)

- Following independent H04 review, black-box probes exposed a startup
  gap with the same stranded-notification symptom in
  `frontend/src/lib/notificationStore.test.ts` (A–H): offline-failed
  baseline → recovery and in-flight baseline carrying the transition row
  both stranded delivery; established-session reconnect was already green.
  Red: `.scratch/w11/notif-gap-red-final.log` (5 failed). Fix in
  `notificationStore.ts` — `watchStartedAt` marks only historical baseline
  rows; fresh rows run the existing delivery pipeline. Green:
  `notif-gap-frontend-test.log` (164), lint 0 errors, build OK.
  The original H04 probe was deleted; its precise cause remains unproven.
- Live QA proof (isolated :18081/:15173, held fetch+stream via init-script):
  emitted `2a1f6213` during the hold → release → exactly one toast +
  `toast|delivered|1` delivery row; 30 s idle → zero recurring inbox GETs.
  The saved screenshot `.scratch/w11/qa-h04-gap-toast.png` was captured
  after dismissal and does not prove visible toast rendering. The QA-only
  recipe `/tmp/w11-qa/handoff/notif-intercept.js` also holds preference
  GETs, so this live check covers delayed startup, not solely an in-flight
  inbox request. The focused regressions cover that precise request race.

## B49 cancel-job dependency statuses (2026-10-13)

- Scratch probe proved parent `cancelled` vs dep `pending` mismatch
  (`.scratch/w11/check-cancel-dependency-state.log`); fix adds
  `_finalize_cancelled_dependencies` for both the in-flight and queued-cancel
  paths. Red: `cancel-dep-state-red.log` (4); green:
  `cancel-dep-state-green.log` + **83 passed** on the three installer-focused
  files; Ruff clean/format on the two touched files.
- API fixture evidence (QA `:18081`, canned persisted job — no real
  install): `GET /api/dependencies/jobs/{id}` returns `git:cancelled,
  nodejs:not_started`. This cancellation check uses fixtures without
  downloading anything; the independent report separately records approved
  real Node/uv installs.
