# W11 Runtime Readiness - Test Plan

Status: partially executed; outstanding acceptance cases remain. See the
[test results](../test_result/11-runtime-readiness-test-results.md).
Branch: `feat/v0.2.0-runtime-readiness`.
Scope: [combined W11](../11-bug-fixes.md) and its
[dependency track](../12-dependencies.md).

## Safety

- Default tests use temporary databases, temporary app-data directories, mocked
  HTTP/subprocesses, and scripted providers. Fail unexpected network requests.
- Do not change `backend/data/agentos.db`, the desktop profile, system PATH,
  Homebrew state, installed applications, real MCP servers, or provider prices.
- Live downloads/installs need explicit permission naming dependency, version,
  source, verification level, size where known, and isolated destination.
- Never exercise removal against an existing system or user-owned installation.
  Retain logs without credentials, arbitrary command bodies, or private aliases.
- Gate each confirmed bug with a failing regression before changing code.

## Catalog Acceptance

| ID | Scenario | Required result |
|---|---|---|
| C01 | Same model name on two providers | Distinct offerings; no shared availability, override, or pricing by name alone |
| C02 | User/provider/catalog disagreement | Applicable field precedence respected; provenance identifies the selected source |
| C03 | Unknown limits/capabilities | Unknown/assumed visible; no invented verified 200K limit or reasoning support |
| C04 | Outage, incomplete discovery, stale cache | Retain observations; distinguish stale/unknown from confirmed unavailable |
| C05 | Refresh, config changes, concurrent misses | Deduplicated bounded jobs, revisions/invalidation, local reads without remote waits |
| C06 | Picker vs runtime | Same resolved vision/limits used; old independent fuzzy/cache paths no longer control behavior |
| C07 | Custom model name without overrides | Missing fields remain missing/assumed; not all user-verified |
| C08 | Provider identity/config changed | New offering facts do not silently reinterpret old call snapshots |
| C09 | Credentials/egress/offline | No credentials or private aliases sent to unrelated sources; no network or paid validation on a read |
| C10 | Offline bundled/local snapshot and daily refresh | Reads require no remote catalog; one 24-hour/overdue refresh is deduplicated; failed validation/HTTPS keeps last-known-good snapshot; overrides preserved |
| C11 | LiteLLM execution-only ownership | CaberOS discovery/metadata/limits/accounting never invoke LiteLLM catalog/cost helpers; SDK remote cost-map loading disabled before first import; execution still works |

Exercise the existing provider/model-list contract with legacy clients; added
provenance must not silently change exact request IDs into display names.

## Accounting Acceptance

| ID | Scenario | Required result |
|---|---|---|
| P01 | Responses/chat, streaming/non-streaming | Shared cost classification; valid reported zero wins; malformed/nonfinite rejected |
| P02 | Provider amount vs generated metadata | Reported amount distinguished from estimate; source not inferred from a hidden field alone |
| P03 | Input/output/cache/reasoning | Preserve reported counters; missing differs from zero; no cached/reasoning double billing |
| P04 | Tiered or unsupported pricing | Correct supported recipe and threshold; unresolved when required dimensions are unavailable |
| P05 | Exact arithmetic/snapshot | Decimal amount and currency; stable rate/calculation version; no live-rate drift on reread |
| P06 | Historic vs later price | **Excluded — historical backfill not in W11 (operator decision 2026-10-13)** |
| P07 | Preview/apply/concurrent retry | **Excluded — historical backfill not in W11 (operator decision 2026-10-13)** |
| P08 | Migration and rollback | Original IDs, usage, and monetary values preserved on a copy; failure restores baseline |
| P09 | Runless/system calls and unknown totals | Embedding/probe/title/extract supported; incomplete/unknown totals remain labelled |
| P10 | Catalog updated after a cost assessment | Existing stored usage, reported amounts, and rate-versioned estimates remain unchanged (snapshot invariance) |

Use deterministic rates, usage, and times. Author independent expected amounts
for each recipe before testing; do not compare an implementation to itself.
Do not assert that an estimated amount equals a provider invoice.

## Dependency Acceptance

| ID | Scenario | Required result |
|---|---|---|
| D01 | Override/system/managed candidates | Deterministic compatible resolution; invalid override reported, not silently ignored |
| D02 | Detected but incompatible/incomplete | Not ready for the selected integration; missing npm/npx or required MCP environment identified; bundled gateway not assumed to be a standalone Python runtime |
| D03 | No verified recipe/unsupported architecture | Guided fallback; no invented one-click install or attempted download |
| D04 | First use, decline, startup, agent suggestion | No install without operator consent; decline persists; no surprise egress |
| D05 | Job progress/cancel/timeouts/restart | Truthful terminal state; no background orphan download/process after cancellation |
| D06 | Concurrent/repeated requests | One serialized install per dependency; idempotent job handling |
| D07 | Source/redirect/hash/signature failure | Fail closed; never activate unverified bytes; expose actual verification level |
| D08 | Local SHA-256 only | Fingerprint label, never authenticated-publisher claim |
| D09 | Malicious/oversized archive | Reject traversal, escaping symlink/hardlink and extraction bombs; safe in-root npm links still work |
| D10 | Failure during extraction/health check/activation | Old working version retained; staged files never selected as ready |
| D11 | Fixed subprocess recipe | Argument arrays only; arbitrary URLs/commands/paths rejected; associated process tree terminates |
| D12 | Resolution after install/config change | MCP gets selected Node/npm paths locally; browser/artifact callers agree with Settings |
| D13 | Managed vs system ownership | Repair/removal cannot modify system/user installations; in-use managed version protected |
| D14 | Feature without implementation | No actionable FFmpeg/Tesseract install prompts or false OCR/transcoding activation |
| D15 | Browser compatibility | Existing override/system/private-browser behavior and personal-profile isolation preserved |
| D16 | Docker/elevated/system fallback | Build-time dependencies respected; no runtime sudo/package-manager bootstrap |
| D17 | Packaged app / HTTP MCP / local-provider choice | Bundled app works without developer runtimes; HTTP MCP does not require local Node/uv; no silent model-server/model-weight installs |
| D18 | Host MCP runtime vs Windows shell sandbox | Managed runtime usable by the MCP launcher is not automatically claimed available inside MXC; sandbox permissions unchanged |
| D19 | Approved Git MCP preparation | **Excluded — combined Git MCP preparation not in W11 (operator decision 2026-10-13)** |
| D20 | General settings vs automatic installation | Optional tools visible in global General; explicit proactive installation permitted; workflow requests require approval; neither implies permission for later repository writes |

## Defect Inventory

Classify every retained B-item as confirmed open, fixed/regression-covered,
superseded by catalog/dependencies, or not reproduced. Record reproduction and
test references. Do not report every historical FIXED entry as newly repaired.
B3's catalog/pricing coverage is P01-P09, not a separate guessed-rate workaround.

## UI And Integration

- Global Settings -> General exposes readiness, installation ownership, source/version/location,
  verification level, progress, cancel, re-check, decline, and actionable errors.
- Picker shows availability/freshness and provenance without presenting assumed
  values as facts; reported vs estimated vs unknown costs remain distinguishable.
- At 375/768/1024/1440 widths, in light and dark themes, verify keyboard/focus,
  readable long labels, local scrolling, no page overflow, and no console errors.
- Delay/fail responses and switch views: no stale job, catalog, or cost payload
  under new labels. Reconnect/reload reflects durable job and catalog revisions.
- Use isolated QA ports/app data. Reuse the real web stack only for read-only
  checks; do not replace it with a disposable database.

## Gates And Results

Extend existing `test_model_catalog.py`, `test_providers.py`, `test_compaction.py`,
`test_harness.py`, `test_system_accounting.py`, `test_platform_spend.py`, and
`test_browser_settings.py`; add dependency/catalog-persistence/rate tests where
the new implementation requires them. Frontend suites cover the new Settings
controls and shared picker consumers. These are required coverage targets,
not claims that existing tests already cover the new behavior.

Before the final push, run backend Ruff check/format and full pytest, plus
frontend tests/lint/build. Run focused regressions during each implementation
slice. Installer tests on unverified platforms remain NOT RUN, not PASS.

Write actual outcomes to `../test_result/11-runtime-readiness-test-results.md`
only after execution: tested commit/tree, environment, each case's PASS/FAIL/
BLOCKED/NOT RUN, expected/actual result, and evidence paths. Record live installer
permission and restoration/cleanup explicitly. No claim of completion until
all three tracks pass or an explicit scope adjustment is approved.
