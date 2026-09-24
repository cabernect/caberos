# W4 Test Plan — Browser Automation Results

Executed 2026-09-23 on `feat/v0.2-browser`, HEAD `3c424c0` plus the uncommitted W4 working tree. Environment: macOS, backend `:8081`, frontend `:5173`, managed Chrome for Testing `145.0.7632.6`, fixture agent `browser-test` (`3eb4feef`). **Overall: not fully green** — R4 did not preserve the SauceDemo login across a fresh headless run, and `npm run build` fails on current `ProvidersSettings.tsx` types. R1 was blocked by Reddit’s challenge; other executed browser cases are reported below.

No personal account credentials were entered. The only login actions used public demo-site credentials; the user entered SauceDemo’s public demo credentials manually for R4.

## 1. Operator API

| case | result | actual |
|---|---|---|
| A1 | PASS | Runtime `ok`; absolute managed binary path, `managed=true`, version `145.0.7632.6`, `source=override`, `install_progress=null`. |
| A2 | SKIP | Managed runtime was already installed and usable; no download/reinstall attempted. |
| A2a | SKIP | No install was in progress; progress endpoint was `null` at rest. |
| A2b | SKIP | No concurrent install to exercise; runtime already installed. |
| A2c | PASS | Settings returned detected Google Chrome + Microsoft Edge and the absolute resolved binary. |
| A2d | PASS | API pinned Google Chrome, cleared to Automatic (resolved to system Chrome), then restored the original persisted managed-browser override. |
| A2e | SKIP | `AGENTOS_BROWSER_BINARY` was absent in the running backend environment. |
| A3 | PASS | Created `hn`; HTTP 201 and allowed domain echoed. |
| A4 | PASS | Duplicate `hn` rejected with 409. |
| A5 | PASS | Profile list contained `hn`. |
| A6 | PASS | Deleted `hn`; HTTP 200. |
| A7 | PASS | Unauthenticated runtime, profiles, settings, and profile-create requests returned 401. |

## 2. Suite gates

| case | result | actual |
|---|---|---|
| B1 | PASS | `uv run pytest tests/test_browser.py tests/test_browser_settings.py -v --tb=short` — **49 passed** in 35.24s. |
| B2 | PASS | `uv run ruff check src/ tests/` — clean. |
| B3 | PASS | `cd frontend && npx tsc --noEmit` — clean. |

## 3. Real-world E2E

| case | result | actual |
|---|---|---|
| R1 | BLOCKED | `www.reddit.com/r/codex/` returned a `js_challenge=1` security page with only “File a ticket”; no post titles/scores were available. Agent reported the block and did not invent content. |
| R2 | PASS | Logged into SauceDemo, added Sauce Labs Onesie for $7.99, and verified cart count 1 via browser observations. |
| R3 | PASS | TradingView observation showed AAPL at $339.75 (+$0.77, +0.23%); the chart description matched the screenshot. Evidence: `backend/data/workspaces/3eb4feef/artifacts/browser/shot-1790151922.png`. |
| R4 | **FAIL** | User confirmed the visible session reached inventory after manual login. After closing that window, two fresh headless runs using profile `saucedemo` both opened `https://www.saucedemo.com/` at the login form, not `/inventory.html`. The visible and headless processes used the same `data/browser-profiles/saucedemo` path. A separate local probe showed a persistent cookie + `localStorage` value surviving `browser_close` and a fresh run, so the profile can preserve durable state; the exact SauceDemo auth-state cause remains unresolved. Closing the visible window also left its Chrome process holding the profile lock; I gracefully terminated only that managed test process before the headless check. |
| R5 | PASS | The initial natural-language run chose `web_fetch` + `write_file` and produced `downloads/data.csv`. A supplemental run explicitly clicked a local browser download link; W4 staged `downloads/browser-download.csv` (27 bytes) and `read_file` verified `sku,label\n7,browser-staged\n`. No file was executed. |
| R6 | PASS | With `saucedemo` scoped to `saucedemo.com`, navigation to `twitter.com` displayed “twitter.com is blocked” and returned `blocked_navigations: ["https://twitter.com/"]`. |
| R7 | PASS (conditional path N/A) | Visible managed browser opened BBC News and the page loaded. No consent prompt appeared, so no manual click was needed; user closed the test window afterward. |
| R8 | PASS | `browser_open` used `mode=research`; agent gave a correct three-bullet Chromium summary. Initial observation was 2,563 chars and contained an omitted-elements marker. |
| R9 | PASS | `browser_act` typed the test-site credentials and clicked Login; post-action observation showed `/secure`, “Secure Area”, and “Logout”. |
| R10 | PASS | Invalid domain produced Chrome’s “This site can’t be reached”; agent reported the failure honestly. |
| R11 | PARTIAL | Prompt did not name the profile; `browser_open` args showed `profile: "saucedemo"`, confirming saved-login discovery. The profile was not logged in (R4); this run was constrained to headless, so the visible reauthentication fallback was not tested. |
| R12 | PARTIAL | Built-in browser was already installed, so the download/progress flow’s “not installed” precondition was false. In Settings → Browser, selecting Google Chrome changed the header/path to “Your own browser” / Chrome / Ready; selecting CaberOS browser restored the original managed setting; “Custom path…” revealed the path field. |

## 3b. Boundary and abuse cases

| case | result | actual |
|---|---|---|
| B1 | PASS* | `web_fetch` was used for `https://example.com`; no `browser_*` call or browser process was started. Fetch failed with TLS `WRONG_VERSION_NUMBER`; agent reported that and only added the reserved-domain description from known information. Static-vs-browser behavior passed, but live retrieval was unavailable in this environment. |
| B2 | PASS | Rejected `browser_open`; tool event status was `denied`, agent said it could not browse, and no browser was spawned for that run. |
| B3 | PASS | After HN → example.com navigation, clicking the old HN ref failed with `DOM.resolveNode: No node with given id found`. Agent re-observed and reported honestly; example.com itself hit this environment’s TLS error page. |
| B4 | PASS | The first run returned while its managed browser session still held `saucedemo`; a second run was refused with “profile 'saucedemo' is in use by another run”, with no crash. The unit lock test also passed. |

## 4. Non-functional

| case | result | actual |
|---|---|---|
| N1 | PASS | After an idle period exceeding 130 seconds, a fresh run’s `browser_observe` failed honestly with “no open browser session”; `agentos-browser` process count was 0. |
| N2 | PASS | Stopped a run immediately after `browser_open`; stop returned 200/`stopped`, and the run-specific browser process plus temp profile directory were gone. |
| N3 | PASS | Sampled initial observations were ~2.5–2.8k chars (under ~8k); large TradingView/Wikipedia pages included omitted-elements markers. |
| N4 | PASS | R9 post-login click returned a 499-char delta with 7 `+`/`~`/`-` lines, not a full page snapshot. |
| N5 | PASS | After restarting the backend, `saucedemo` remained in `GET /api/browser/profiles` with its allowed domain, and `data/browser-profiles/saucedemo/` remained on disk. Backend health returned 200. |

## 5. Additional verification

- Local profile differential probe: a temporary local page wrote a dummy `Max-Age` cookie and `localStorage` marker, then `browser_close` released the profile. A new headless run displayed `PERSISTED`. Probe profile and its directory were removed afterward.
- Settings UI was exercised in Orca because the Playwright MCP browser reported its shared profile was already in use. The managed-browser engine setting was restored and verified via API.
- R4 remains a reproducible acceptance failure for the SauceDemo scenario. Same profile path and generic durable storage passing narrow the cause to site-specific/session auth behavior or another R4-step detail; no implementation fix was attempted during this test run.

## 6. Additional repository gates

| command | result | actual |
|---|---|---|
| `uv run ruff format --check src/ tests/` | FAIL | Would reformat `backend/src/agentos/browser/runtime.py` and `backend/tests/test_browser.py`. `ruff check` itself is clean. |
| `cd frontend && npm run lint` | PASS | 0 errors, 9 warnings. |
| `cd frontend && npm run build` | **FAIL** | `ProvidersSettings.tsx`: TS2345 at lines 620/669 (`runtime.source` inferred as `string`, not the `BrowserRuntime` union) and lines 696/737 (`string` passed where `ConfirmOptions` is expected). |
| `cd frontend && npx vitest run` | PASS | 9 files, **33 passed**. |

## State left for follow-up

- Test agent `browser-test` (`3eb4feef`) remains configured with W4 browser capabilities, `agent_ask_user`, 30 turns/run and $5/run cap.
- Saved profile `saucedemo` remains in Settings and on disk for reproducing R4; it did not reopen logged in during headless verification.
- Workspace evidence remains under `backend/data/workspaces/3eb4feef/`: browser screenshots and the two R5 CSV fixtures.
- Backend remains healthy on `:8081`; frontend remained on `:5173`; no managed browser processes were left running after backend shutdown/restart cleanup.
