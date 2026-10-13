# W11 Runtime Readiness — Independent Test Results

Tester: independent verification agent (not the implementing agent).
Date: 2026-10-13
Commit under test: `f4c323c` on `feat/v0.2.0-runtime-readiness`
(verified in worktree; `3a77cca`, `0d1267a`, `c7b7be2` all ancestors of HEAD).
Platform: macOS ARM64 (darwin-arm64).

## Environment

Handoff-provided isolated QA environment, reused as instructed:

- Backend `http://127.0.0.1:18081` (uvicorn from repo `.venv`; restarted twice
  under my control for H04/H11 — current PID is my restart, same env.sh).
- Frontend `http://127.0.0.1:15173` (vite proxying `/api` → :18081).
- QA DB `/tmp/w11-qa/handoff/data/agentos.db`; all roots under `/tmp/w11-qa/`.
- `AGENTOS_MODEL_CATALOG_AUTO_REFRESH=false`, offline proxy `127.0.0.1:9`.
- No providers/secrets in QA DB (fresh env — live catalog/provider calls N/A).
- Automated tests ran against a separate `mktemp` root per the handoff.
- Main services on :8081/:5173 never touched; production DB never touched.

## Gates (independent)

| Suite | Result |
|---|---|
| Focused handoff list (`test_mcp`, `test_mcp_oauth_refresh`, `test_scheduler`, `test_call_accounting`, `test_runtime_installer`, `test_dependencies`, `test_mcp_stdio_resolver`) | **178 passed**, 1 aiosqlite loop-close warning |
| Catalog/accounting files (`test_model_catalog`, `test_catalog`, `test_catalog_policy`, `test_providers`, `test_call_accounting_glue`, `test_system_accounting`, `test_platform_spend`, `test_model_call_migration`, `test_compaction`, `test_browser_settings`) | **120 passed** with `AGENTOS_MODEL_CATALOG_AUTO_REFRESH` unset |

Env note: with the QA env var *set* (as env.sh provides), 2 catalog tests fail —
`test_status_never_fetches` (expects default `auto_refresh=True`) and
`test_toggle_and_explicit_refresh` (PUT → 409 "pinned by
AGENTOS_MODEL_CATALOG_AUTO_REFRESH"). Both failures are the pin behaving as
designed — the PUT correctly refuses to manage an env-pinned setting. Not
defects. Regression invocations should unset the var (or the handoff command
should note it).

Full-gate (1121/156) was the implementer's prior claim and was not re-run —
per the handoff's "do not rerun a costly full gate merely to restate".

## Priority cases

### H01 — Settings → General exposes Optional Tools & Runtimes — PASS

Headings on `/settings` General tab: Operator, Appearance, Notifications,
Search Provider, **Optional Tools & Runtimes**. No Model Catalog maintenance
card (`catalog` absent from page text). Readiness rows rendered:
Node.js Ready 22.22.3·system, uv Ready 0.9.6·system, Git Ready 2.50.1·system,
Chromium Ready·system, LibreOffice Missing + "Guided setup" link, plus the
honest footer that missing tools only gate their own features.

### H02 — Truthful readiness + Re-check + reopen — PASS

`GET /api/dependencies` returns status/source/version/executables per tool;
`managed_recipe_available` true for Node/uv/Git, false for LibreOffice with
`guidance_url` to libreoffice.org. Re-check click re-fetches (observed in
backend log); statuses remain truthful before/after close/reopen. System
candidates precede managed (verified: fixture-committed managed Node 24.21.0
did **not** displace system 22.22.3 — deliberate precedence, correct).

### H03 — No recurring jobs polling while idle — PASS

20 s idle on Settings → **0 requests** in backend log (no `/api/dependencies`,
no `/api/dependencies/jobs`, no notification inbox poll). One initial fetch
per mount; explicit Re-check fetches again.

### H04 — SSE health vs fallback polling — PASS (residual noted)

Controlled disconnect (kill QA backend) → leader fallback polls during
outage; restart → stream reconnects → single catch-up `GET /api/notifications`
→ quiet again (0 recurring requests). Emit during healthy stream → instant
delivery (`toast/delivered` row + rendered toast).

**Residual (now identified as B48):** a notification emitted during the
post-restart transition window (`w11h04probe1`) was never delivered by any
path — 0 delivery rows, still unread, permanently stranded after the next
baseline sweep. Initially recorded here as "B38-class"; the implementer
triaged it as **B48** — the initial-baseline path marking post-mount rows
seen — distinct from B38's follower-promotion mechanism (already fixed via
`deferredReports`). The B48 fix (`watchStartedAt` baseline cutoff) exists in
the worktree uncommitted at report time; `notificationStore.test.ts` 32/32
green including the eight "subscribe-transition gap repro (H04)" probes.

**B48 live retest (this pass, on the uncommitted fixed tree):** fresh
browser session, single authed leader tab — pipeline confirmed via prefs +
snapshot + stream + failed-deliveries requests in the backend log. Probes
emitted at 0/1/2/4/7s offsets around a reload **all** produced
`toast:delivered` rows (~10 ms after creation, `attempts=1`) and stayed
unread in the inbox. Emit-while-browser-closed rows correctly took the
baseline-suppression path (unread, zero deliveries — history semantics).
Two-tab leader-close → promotion continuity verified: a probe emitted 1s
after closing the leader tab was delivered by the promoted follower within
8s. The exact "created after `watchStartedAt` but present in the first
snapshot" slice is a ~40 ms window on localhost — covered by the eight
unit probes rather than a live hit. Verdict: **B48 verified fixed**; no
stranding observed across reload/close/promotion boundaries — precisely
the transitions that stranded `w11h04probe1` pre-fix. Harness caveat: an
earlier browser profile on this machine developed a stuck network state
where *only* `/api/notifications/*` fetches hung indefinitely (all other
endpoints normal; backend answered the same requests in ~2 ms via curl);
a fresh browser session eliminated it — environmental, not an app defect.

### H05 — Install preview before consent — PASS (simulated discovery)

Fixture per handoff: `RuntimeDependencyRegistry(data_dir=qa_runtime_root,
finder=lambda _: None)` → all deps missing → `installer.plan(["nodejs"])`
returned action=`install`, version 24.21.0, real download_url +
`metadata_url` (SHASUMS256), sha256, destination under
`managed-runtimes/nodejs/versions/...`, verification=`publisher_checksum`,
license text. `start(plan_id, consent=False)` → **422 "explicit consent
required"**; zero bytes staged before consent. API-level: plan for
`libreoffice` → `"unsupported dependencies"` (no invented recipe).

### H06 — Consent/progress/cancel/failure/retry/reload — PASS (mocked I/O)

Download callable injected; extraction/health/activation/pointers all real:

- Happy path: job `downloading→extracting→verifying→activating→completed`,
  progress_bytes tracked; registry then reports nodejs `ready · managed`
  24.21.0 with managed executables.
- Reload: fresh registry+installer on the same root → managed install
  rediscovered; `list_jobs` shows the completed job (durable).
- Cancel mid-download → job `cancelled`, no destination left behind, no
  orphan process. Minor: the in-flight dep row stays `pending` inside the
  cancelled job (task cancellation doesn't relabel the dep) — job-level
  terminal state is truthful; cosmetic granularity only.
- Checksum failure (sha256 `"0"*64` vs real archive) → job `failed`,
  detail "downloaded bytes do not match the recipe checksum", **no
  activation** (fail-closed, D07).
- Retry same dep with matching archive → `completed`.
- Simulated-discovery label applies: archive bytes were fabricated locally
  and recipe sha256 injected to match; this is NOT evidence of real-install
  success per the handoff.

### H07 — Remove fixture-owned executable → stale recheck — PASS

Deleted the managed `node` binary only → forced status re-probe → nodejs
flips to `status=error`, `detail="invalid managed runtime pointer"`,
`resolve("node")` → None. No silent reinstall, no incompatible fallback —
actionable missing-runtime state.

### H08 — Real Bearer challenge discovery — PASS

Fresh server (no `oauth_config`) → connect → client POSTs a real MCP
initialize (163-byte body) to the fake :18082 → gets
`401 + WWW-Authenticate: Bearer realm="mcp", resource_metadata="..."` →
`connected:false`. Backend persisted a default consent config
(`{"scope":"","redirect_uri":"…/oauth/callback"}`), emitted
`oauth_reauth_required` ("Authorize w11-fake-oauth"), and the UI shows
**Connect OAuth** + guidance text + Re-authenticate. Fake server saw
exactly one `POST /mcp` — **no** `/.well-known` fetch, no token endpoint,
no redirect. This is the `0d1267a` behavior, verified live.

Caveat discovered: a server row that already has `oauth_config` (e.g. the
seeded `qa-oauth-mcp`) short-circuits in `connect_server` ("OAuth
authorization required — connect via dashboard") without touching the
network — correct behavior, but it means the seeded row alone cannot prove
live discovery; the fresh-server path above is the real evidence.

### H09 — Non-Bearer/malformed/error variants — PASS

Against a live challenge (oauth_config cleared between runs):

| Mode | connected | oauth_config after | hits on fake |
|---|---|---|---|
| bare `Bearer realm` (no resource_metadata) | false | NULL | 1× POST |
| `Basic` | false | NULL | 1× POST |
| malformed `resource_metadata=%%%` | false | NULL | 1× POST |
| 403 | false | NULL | 1× POST |
| 500 | false | NULL | 1× POST |

No guessed OAuth configuration; no metadata/token probing on any variant;
existing operator configuration untouched.

### H10 — Scripted native vs proxy accounting — PASS

Direct `assess_usage` (per-million rates) with scripted receipts:

- Native tiered card (`size:0` base $3/$15 + `size:200000` $6/$30):
  150k/1k → **0.465** (tier `size:0`); 300k/1k → **1.83** (tier `size:200000`).
- Same card with `context_tier_basis="per_message"` → **unknown**,
  `unsupported_context_tier_basis`; basis `None` → same. Proxy unsupported
  tier basis stays unknown — never silently estimated.
- Genuine `reported_cost="0"` → amount **0** (not upgraded, not unknown);
  reported `0.000042` wins over estimate; flat-rate estimate exact
  (10k/500 → 0.000000011).

### H11 — Restart reconcile preserves skip note, twice — PASS

Seeded occurrence: `status=running`, `error='2 earlier occurrence(s)
skipped'`. Restart 1 → `cancelled`, `finished_at` set, error
`"2 earlier occurrence(s) skipped; Gateway restarted during execution"`
(pre-existing note preserved, reason appended once — the `c7b7be2` fix).
Restart 2 → row byte-identical — no duplicate restart reason.

### H12 — Responsive settings, light/dark — PASS

`/settings` (incl. runtimes card) at 1440/1024/768/375 → `scrollWidth`
equals viewport, zero page-level horizontal overflow in both dark and
light themes; runtime rows readable at 375. No console errors observed.
Install dialog UI could not be rendered (no missing recipe dep exists in
this env by design) — consent surface verified at API/fixture level (H05).
Known handoff limitation (375px MCP header pushing controls off-screen)
noted as pre-existing, not re-filed.

## Catalog (C01–C11) / Accounting (P01–P10) / Dependencies (D01–D20)

No live providers exist in the QA DB (fresh env, no secrets — by design),
so the catalog/provider tracks were verified by the suite above rather
than live calls: 120 catalog+accounting tests green (precedence,
provenance, snapshot invariance, LiteLLM isolation, spend accounting,
migration preservation). H-cases exercised the dependency track live
(D03 guided fallback, D04 consent gate, D05 lifecycle, D07 fail-closed,
D12 resolution precedence, D13 ownership boundaries). P-track additionally
verified by scripted `assess_usage` calls (H10).

## Real installer execution (approved 2026-10-13)

Operator granted explicit download approval for the pinned recipes.
Executed via the sanctioned standalone fixture — `finder=lambda _: None`
(missing state only); **no** injected `download=` or `recipes=` — so URL
fetch, checksum, extraction, health checks, and pointers are all real:

| Dep | Plan | Download | Result |
|---|---|---|---|
| uv | action=install, 0.12.24, github release asset, publisher_checksum | **14,650,202 bytes** — byte-exact with the handoff table | `ready · managed · 0.12.24`; job states downloading→extracting→verifying→completed; log "downloaded 14650202 bytes, sha256 ok" |
| Node.js | action=install, 24.21.0, nodejs.org tar.gz, sha256 `bed7eea…` | **52,909,993 bytes** (~50.5 MiB < 256 MiB cap) | `ready · managed · 24.21.0`; npm/npx resolved inside managed tree |

Post-install proof: managed `node --version` → `v24.21.0`, `node -e` runs
JS; `uv --version`/`uvx --version` → `0.12.24 (5411378eb)`. Fresh-registry
re-probe rediscovered both managed pointers (`ready · managed`). All bytes
confined to `qa_runtime_root` — no system/user installs created or
modified; fixture removed after evidence collection.

## NOT RUN / limitations
- **Windows/x64**: host coverage is macOS ARM64 only.
- **Install dialog UI** at the four widths: unreachable in this env.
- **Live catalog/provider behavior** (C-track live, OAuth real grant,
  paid model calls): excluded by design/env.
- Git MCP preparation + historical-cost backfill: excluded per handoff.
- Full 1121/156 gate: not re-run (prior green baseline accepted per
  handoff instruction).

## Defects

- **None filed by this pass.** The H04 stranded-notification residual was
  triaged by the implementer as **B48** (initial-baseline suppression of
  post-mount rows) — a new registry entry distinct from B38, whose
  follower-promotion gap is fixed via `deferredReports`. B48's
  `watchStartedAt` fix was uncommitted in the worktree at report time and
  is **verified fixed** by this pass's live retest (see H04 section).
- Cosmetic observation → filed by implementer as **B49** and fixed:
  `_finalize_cancelled_dependencies` marks the in-flight dep `cancelled`,
  untouched earlier deps preserved, later deps `not_started`. Re-verified
  this pass: 4 cancel regressions green on the worktree, plus a direct
  event-held-download probe printing `PARENT: cancelled | DEPS:
  {'git': 'cancelled'}` — no `pending` residue. **Verified fixed**
  (uncommitted at report time).

## Cleanup evidence

- Test notifications (`w11h04probe1/2`, `w11b48gap*`, `w11b48live`,
  `b48-*`, `b48pre-*`, `b48closed-*`, `b48-two-*`, two
  `oauth_reauth_required` rows) + their deliveries deleted; pre-existing
  rows untouched.
- `w11-fake-oauth` MCP server row deleted; `qa-oauth-mcp` seed retained;
  its `oauth_config` unchanged throughout.
- Seeded `w11h11-*` occurrence deleted (0 occurrences remain).
- Fixture `managed-runtimes/{nodejs,git,jobs,.staging}` removed; directory
  empty — no system/user installs touched (none created).
- Fake :18082 server killed; `mktemp` regression root and helper scripts
  under /tmp removed.
- QA backend left running on :18081 (handoff env, healthy); QA frontend
  :15173 up; browser session closed; no changes to :8081/:5173, production
  DB, system PATH, or `scripts/dev.sh`.
