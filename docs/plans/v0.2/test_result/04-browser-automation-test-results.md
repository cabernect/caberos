# W4 Test Plan — Browser Automation Results

Initial W4 run 2026-09-23; independent recheck 2026-09-24 on `feat/v0.2-browser` — macOS, backend `:8081`, frontend `:5173`, managed Chrome for Testing `145.0.7632.6`. Fixture agents: `browser-test` (`5b93f207`, OpenAI `gpt-5.6-luna`, vision), `browser-test-41mini` (`12caf4f4`, `gpt-4.1-mini`), plus earlier fixture `browser-test` (`3eb4feef`). UI cases driven via Playwright MCP; visible-window "human hand" steps driven by a second CDP client attached to the debug port (credentials typed straight into the browser, never through the agent).

This supersedes an earlier same-day draft (fixture `3eb4feef`, wrong path — since removed). That draft judged `/` rather than `/inventory.html`. Later `/inventory.html` checks were run after SauceDemo's ~16-minute session cookie had expired; those login redirects are expected and are not valid R4 failures.

**Coding-agent run: all executable cases passed except R1 (Reddit CAPTCHA).** Six real defects were found and fixed during that run (see **Findings**). The recorded within-window R4 pass stands; the later expired-session probes and their timestamps are documented under **Independent post-report verification**.

## §1 Operator API

| case | result | actual |
|---|---|---|
| A1 | PASS | `status:ok`, absolute managed binary path, `source`/`managed_binary`/`install_progress:null` present |
| A2 | PASS | Fresh install via `POST /api/browser/runtime/install`; `INSTALL.json`: sha256 `3dbf04e2…bdb2`, `signature: adhoc (cdhash b91481bf0d4d538e…)`, `health: Google Chrome for Testing 145.0.7632.6`. First pass reported `signature: unreadable` — see Findings 1 |
| A2a | PASS | Live progress polled mid-install: `preparing → downloading → verifying` with `downloaded`/`total` bytes; UI showed `Downloading… 11 / 162 MB — keep this tab open.` |
| A2b | PASS | Second concurrent `POST /install` → `"an install is already in progress"` |
| A2c | PASS | `GET /api/settings/browser` → `detected`: Google Chrome + Microsoft Edge with absolute paths; `resolved_binary`, `override_source` correct |
| A2d | PASS | PUT pin Chrome → `override_source:persisted`, runtime `source:override`; clear → `source:system` |
| A2e | PASS | Backend restarted with `AGENTOS_BROWSER_BINARY` → `source:override`, env binary; PUT → **409** `"browser_binary is pinned by AGENTOS_BROWSER_BINARY — remove it from the environment or .env to manage it here"` |
| A3 | PASS | `POST /api/browser/profiles` `hn` → 201, allowed domain echoed |
| A4 | PASS | Duplicate `hn` → 409 |
| A5 | PASS | `GET /api/browser/profiles` lists `hn` |
| A6 | PASS | `DELETE` `hn` → 200 |
| A7 | PASS | Unauthenticated runtime/profiles/settings/profile-create → 401 |

## §2 Suite gate

| case | result | actual |
|---|---|---|
| B1 | PASS | `uv run pytest tests/test_browser.py tests/test_browser_settings.py -v` — **49 passed** (56.08s post-fix re-run) |
| B2 | PASS | `uv run ruff check src/ tests/` — clean; `ruff format --check` clean (206 files, after reformatting 3 — Findings 6) |
| B3 | PASS | `cd frontend && npm run build` (`tsc -b && vite build`) — clean. **Note:** `npx tsc --noEmit` on the root tsconfig is a no-op (references-only file); `tsc -b` is the real gate and was **FAIL** before today's type fixes — Findings 5 |

Supplemental gates: `npm run lint` (oxlint) 0 errors / 9 warnings · `npx vitest run` **33/33** · `npm run build` ✓ 2.76s.

## §3 Real-world E2E

| case | result | actual |
|---|---|---|
| R1 | BLOCKED (env) | Reddit served a "Prove your humanity" CAPTCHA; `.json` endpoint 403; `old.reddit` same. Agent honestly reported the block — no fabricated titles. Run also exposed the navigate-URL-in-`target` crash — Findings 2 |
| R2 | PASS | Login → sort `lohi` → `browser_extract` inventory → add to cart. Agent answer: **"Sauce Labs Onesie — $7.99"**; cart verified via delta `~ e89 button 'Cart, 1 items'` + `Remove` button |
| R3 | PASS | AAPL **$339.75 (+0.23%)**, pre-market $340.27, "slightly bullish" chart description from visual observation. Screenshots staged `artifacts/browser/shot-1790156034.png`, `shot-…039.png` |
| R4 | PASS (within session window) | The coding-agent log `w4run-6daf…` records `/inventory.html` with product cards after the visible login. SauceDemo's `session-username` cookie expires around 16 minutes after login; later independent redirects occurred outside that window and are expected. See Independent post-report verification. |
| R5 | PASS | Click on the local download link staged `downloads/data.csv` (23 B, real CSV) via the browser download path; agent also `web_fetch`ed a copy to workspace root (allowed). No file executed |
| R6 | PASS | Both directions: navigate with `allow_domain:false` → Chrome "twitter.com is blocked" + `blocked_navigations`; `allow_domain:true` → approval-gated widening navigated. Open of an out-of-scope URL on the `saucedemo` profile is refused at open |
| R7 | PASS | `visible:true` opened a real managed window on BBC News; page loaded clean — no consent wall on this network, so the human-click path was N/A. Takeover mechanics verified via external CDP attach (type/click in the visible window) |
| R8 | PASS | `mode:research` on Wikipedia → accurate 3-bullet Chromium summary; resource blocking in effect; initial observation 2,563 chars with `omitted` marker. Required the 4.1-mini fixture — Findings 4 |
| R9 | PASS | the-internet login: `type` e4 `tomsmith`, e5 `SuperSecretPassword!`, `click` e6 → `/secure` "Secure Area" + Logout. Agent self-corrected after typing both creds into one field; password field observed masked `•••` — values never echoed into observations |
| R10 | PASS | Nonexistent domain → Chrome "This site can't be reached" in the observation; agent: "The browser cannot reach the site … The page shows a 'This site can't be reached' error." |
| R11 | PASS | Prompt did not name a profile; agent picked `profile:"saucedemo"` from the injected saved-logins section and used it unprompted |
| R12 | PASS | Full UI flow live in Playwright: engine picker → remove built-in → option reads "(not installed — downloads on select)" → "Download & install (~160 MB)" → live progress `Downloading… 11 / 162 MB` → "Browser installed — agents can now browse the web." + auto-pin → pin detected Chrome ("Your own browser / Ready") → "Custom path…" reveals path input → reset to Automatic |

## §3b Boundary / abuse

| case | result | actual |
|---|---|---|
| B1 | PASS | Static page → `web_fetch` chosen; zero `browser_*` calls, zero browser processes. (Fetch itself hit this network's corp-proxy TLS `WRONG_VERSION_NUMBER` — reported honestly) |
| B2 | PASS | `browser_open` approval rejected → tool event `status:denied`, agent said it could not browse, no process spawned |
| B3 | PASS | Stale ref after navigation → `BrowserError DOM.resolveNode: No node with given id found` — recoverable tool error, run continued (verified at session level; agent-level run was diverted by the corp-proxy TLS error) |
| B4 | PASS | Second run on a live-held `saucedemo` profile → `"profile 'saucedemo' is in use by another run — try again after it finishes or use an isolated session"`; no queue, no crash |

## §4 Non-functional

| case | result | actual |
|---|---|---|
| N1 | PASS | Idle headless browser (pid observed) reaped at ~120 s — `IDLE_TIMEOUT_S=120`, `REAP_INTERVAL_S=15`; process gone after reaping. Visible windows are exempt by design (operator's window is never killed) |
| N2 | PASS | `POST /api/chat/<agent>/runs/<run>/stop` → `{"status":"stopped"}` while `browser_open`/`browser_observe` had executed; 0 browser processes afterward, no new temp-profile orphans. Two *pre-existing* `agentos-browser-*` dirs in TMPDIR predated the test (see Known limitations) |
| N3 | PASS | Wikipedia initial observation 2,563 chars with `omitted` marker — well under the ~8k-char/2k-token cap |
| N4 | PASS | Post-action results are bounded deltas, not re-observations — e.g. add-to-cart returned `~ e89 button 'Cart, 1 items'\n+ e316 button 'Remove'\n- e298 button 'Add to cart'` (~100 chars) |
| N5 | PASS | Backend killed + restarted (twice — once with `AGENTOS_BROWSER_BINARY` for A2e, once clean): profiles `default`/`saucedemo` still listed, `data/browser-profiles/{default,saucedemo}` intact on disk; clean restart restored `source:system` |

## Findings — fixed during execution

1. **Runtime signature check broken on paths with spaces + adhoc builds** (`browser/runtime.py`). `codesign -dv` emits no `CDHash`, and the fallback printed a path truncated at the space in `Google Chrome for Testing.app` → `signature: unreadable`. Now `codesign -dvvv`, parses key-value lines from stderr, reports `signature: adhoc (cdhash …)` — honest for CfT's adhoc signing (sha256 pin + live-render health check is the integrity story).
2. **`browser_act` URL-in-`target` crashed the whole run** (`browser/cdp.py`, `capabilities/tools/browser.py`). The model emitted `{"action":"navigate","target":"https://…","value":""}`; `int(ref[1:])` raised a raw `ValueError` that killed the run. Now: non-`eNN` refs → `BrowserError("unknown element ref: …")` (recoverable); navigate accepts the URL from `value` **or** `target`; domain-widening check looks at both fields.
3. **Stale UI label** (`browser/registry.py`): refusal said "Settings → Dependencies" — the tab is **Browser**. Fixed.
4. **`profile_not_found` was non-instructive and mislabeled** (`capabilities/tools/browser.py`, `capabilities/builtin.py`, `harness/context.py`). The error didn't teach recovery and surfaced as a tool-call `status:complete`. Now it lists available profile names and says to omit `profile` for a fresh isolated session; the `profile` param description says "Omit it entirely for a fresh isolated session"; the saved-logins prompt section notes profiles are optional. (The `status:complete` wrapper remains — Known limitations.)
5. **`npm run build` type errors** (`lib/api.ts`, `ProvidersSettings.tsx`). `runtime.source` widened to `string` — api.ts now exports `BrowserRuntimeInfo` with the `"override"|"system"|"managed"` union used by both settings endpoints; `confirm("…")` → `confirm({title, message, confirmLabel, danger})`. Build now passes — this resolves the earlier draft's FAIL.
6. **Formatting** — `ruff format` applied to the 3 touched files (`runtime.py`, `test_browser.py` among them); `--check` clean.

From the preceding UI session (same day, same workstream): zip extraction preserved `.app` symlinks + exec bits (was silently corrupting every managed install), health check does a real `about:blank` render instead of `--version` only, install progress phases backend-tracked, `--hover` CSS var defined, hover/cursor states added across the Browser tab.

## Test-harness incidents (executor error, not product defects)

- **Approval flood**: the first approval loop approved *every* pending approval system-wide (~40 belonging to other agents). Driver now filters `agent_id` — the approvals endpoint has no server-side filter param.
- **Approval gate silently off**: the fixture's capability PUT omitted `require_approval`, so grants defaulted `false` and overrode the built-in gate (zero approval rows generated). Grants corrected to `require_approval:true`; the test plan now warns about this.
- **Backend wedge**: an approval storm + auto-reload froze the event loop; the orphaned run was reconciled to `interrupted` at next startup — durable-runs working as designed.
- **Temp `default` profile**: both models repeatedly invented `profile:"default"` rather than omitting the arg; a throwaway unrestricted profile was created to unblock R10, then deleted.

## Deferred — behaves as designed (§5)

- **"Watch Browser" streamed viewer** — not built; desktop uses `visible:true` real windows, web/Docker get screenshots + trace.
- **Plan Mode write-denial** — Plan Mode doesn't exist; the `effects` classification it will consume does.
- **Profile queueing** — second run on a held profile gets an immediate honest refusal (B4), no wait queue.
- **Visible sessions refused on non-interactive triggers** — `visible_refused`, by design.

## Known limitations / sev-2

- `profile_not_found` (and similar honest-payload statuses) still surface as tool-call `status:complete` — the payload is truthful but the status semantics can mislead an executor reading only statuses.
- Both test models sometimes invent `profile:"default"` instead of omitting the optional arg — model quirk; `profile:""` works; error text now steers recovery.
- `agentos-browser-*` temp dirs can linger when a run crashes before `close()` (2 observed from the wedged-backend incident; OS cleaned TMPDIR — 0 at report time).
- A stale `locked` dir exists under `data/browser-profiles/` — predates this test round.
- Corp-proxy TLS breaks `example.com`/`the-internet` fetches intermittently on this network (B1 fetch, B3 agent-run) — environmental.

## Independent post-report verification (2026-09-23–24)

- The scratch run log `w4run-6daf3fc3-0b10-4f4a-a7d3-282b879028db.json` records a successful `browser_open` to `/inventory.html` with `profile:"saucedemo"` and product cards present; this supports the coding-agent R4 PASS at that time.
- Later, using the current saved profile (id `b5827446-f326-48b1-8515-d501f5134c6f`) without deleting it or entering credentials, fixture `5b93f207` checked at `2026-09-24 03:12` and `12caf4f4` at `03:16`; both `/inventory.html` checks redirected to `/`. The successful coding-agent check was `2026-09-23 09:43`, about 17.5 hours earlier. These late probes were well outside SauceDemo's ~16-minute `session-username` cookie lifetime, so the redirects are expected and do not contradict the within-window R4 pass. No profile files were deleted.
- A temporary pin to the managed CFT binary produced `browser connection lost` on the same profile. The setting was restored to Automatic/system Chrome; no profile files were deleted.
- Independently exercised the URL-in-`target` fix through the real browser capability on a local page: an empty `value` plus `target:http://127.0.0.1:<port>/next` navigated successfully and returned a bounded delta. A missing-profile probe returned `profile_not_found`, listed `saucedemo`, and instructed to omit `profile` for isolation.
- Re-ran the automated gates after the fixes: browser/settings tests **49/49**, `ruff check` + `ruff format --check` clean (206 files), `npm run build` passed, lint 0 errors/9 warnings, Vitest **33/33**. `INSTALL.json` reports the adhoc signature + sha256/health values documented above.
- Approval handling during these rechecks filtered by both `agent_id` and exact `run_id`; there were no pending approvals before or after, and no other agent approvals were acted on. Both fixture agents report `require_approval:true` for `browser_open` and `browser_act`.

## State left behind

- Agents `browser-test` `5b93f207`/`3eb4feef` and `browser-test-41mini` `12caf4f4` still configured with W4 capabilities (`browser_open`/`browser_act` gated at `require_approval:true`).
- Profile `saucedemo` kept in Settings + on disk for follow-up; the coding-agent run recorded a within-window `/inventory.html` pass. The later independent redirects occurred after the ~16-minute cookie expiry and are expected.
- Managed runtime `145.0.7632.6` installed at `backend/data/browser-runtime/145.0.7632.6/` with `INSTALL.json` above; engine back on **Automatic** → resolves `system` Chrome.
- Workspace evidence under `backend/data/workspaces/`: `5b93f207/artifacts/browser/shot-*.png`, `5b93f207/downloads/data.csv` (+ root `data.csv` from `web_fetch`), `3eb4feef/downloads/{data.csv,browser-download.csv}`.
- Backend left running on `:8081` under a session shell; no browser processes left.
