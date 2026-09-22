# v0.2.0 Browser Automation

## Outcome

Agents research and interact with dynamic websites through a CaberOS-managed browser, with isolated defaults, opt-in persistent profiles, visible provenance, and side-effect-aware approval.

## Open implementation decision

The product browser automation engine/protocol has not been selected. Workstream 0 must evaluate and prove it before implementation. The plan must not assume Playwright. The selected engine and compatible browser runtime are pinned and hidden behind the Browser module interface.

## Managed runtime

CaberOS never depends on Safari, Chrome, Edge, or another personal browser installation and never reads a personal browser profile.

Desktop installs the compatible automation browser explicitly on first use:

1. Explain isolation and required disk/download size.
2. Download an exact approved artifact.
3. Verify hash/signature.
4. Install under CaberOS application data.
5. Run a health check.
6. Support cancel/retry/reinstall/remove/diagnostics.

A tool call never silently downloads the runtime or invokes `terminal` to install it. Compatible runtime versions survive app updates; incompatible versions install side-by-side before new sessions switch. Docker bundles the same pinned compatible runtime.

## Browser modes

- **Headless:** default for routine and scheduled work.
- **Visible:** login, MFA, CAPTCHA, consent, user takeover, debugging, or explicit Watch Browser.

The managed browser uses separate isolated/persistent profiles regardless of mode.

## Profiles

- Isolated profile: default, fresh per run, discarded.
- Persistent profile: operator-owned, named, domain-scoped, assigned explicitly to agents/schedules.
- One active owner per persistent profile; additional runs queue.
- Cookies/storage never enter model context.
- Browser binary and profile storage are separate.

## Capability distinction

`web_fetch` and the Browser module have separate, explicit purposes:

```text
web_fetch       -> static HTTP retrieval and readable-content extraction
Browser module  -> JavaScript rendering, dynamic-page observation, and interaction
```

The agent-facing descriptions must state:

- `web_fetch`: "Fetch and extract readable content from a static URL over HTTP. Does not execute JavaScript, interact with the page, or start the managed browser runtime."
- `browser_open`: "Open a URL in the managed browser for JavaScript-rendered content or page interaction. Starts or reuses a browser session."

Neither capability silently changes into the other. The agent may explicitly use `web_fetch` for a cheap static read and open the same URL in the Browser module only if rendering or interaction is required. Browser observations remain semantic by default and become visual only when layout or imagery matters.

## Performance and context efficiency

The browser engine and protocol affect startup cost, memory, and reliability, but the Browser module implementation owns most avoidable latency and model-token usage. Headless execution alone does not make automation token-efficient.

The implementation must:

- keep one persistent protocol connection for an active session;
- reuse a managed browser process and safe isolated contexts instead of launching a browser per action;
- use event-driven, bounded waits rather than fixed sleeps;
- support a research mode that blocks unnecessary media, fonts, advertisements, and trackers, with a normal-load fallback when the page breaks;
- keep browser state, full page trees, network logs, and extracted resources outside model context;
- stage large extracts and downloads as traceable resources and return only bounded previews and handles;
- shut down idle browser processes and enforce page, tab, memory, download, and concurrency limits.

Performance work optimizes total latency and total tokens required to complete a task, not the size of one observation at the cost of extra turns or failed actions.

## Browser module interface

The Browser module is a deep module with a compact agent-facing interface:

```text
browser_open(url, profile?, mode?)
browser_observe(scope?, detail?, token_budget?)
browser_act(action, target?, value?)
browser_extract(scope?, format?, query?)
browser_close()
```

`browser_open` returns the initial observation. `browser_act` performs exactly one state-changing browser action and returns its post-action observation, preserving `reason -> act -> observe -> repeat` without requiring a redundant snapshot call. Click, type, select, scroll, navigation, screenshot, and download mechanics remain hidden inside the module and are mediated according to their actual effects.

Observations use short-lived stable element references and bounded accessibility/DOM semantics rather than raw HTML, full page trees, generated selectors, or coordinates. The default initial observation targets at most 2,000 model tokens and a post-action delta at most 800 model tokens; the implementation spike must validate and tune these provisional budgets against task success. Omitted regions are reported and can be inspected through a targeted `browser_observe` call.

Screenshots are on-demand visual observations stored as traceable artifacts, never base64 text in ordinary tool output. Visual observations are sent to a vision-capable model only when the task requires them. Repeated observations return changed semantic regions where possible; full bounded observations remain available for recovery. Element references are invalidated safely when their underlying page state disappears.

## Agent view and live browser

Agent observation and human visibility are separate interfaces over the managed browser session:

- The agent receives compact semantic observations, stable references, and bounded deltas.
- The operator sees rendered pixels through the visible managed browser runtime or a future streamed viewer.
- Live frames, pointer movement, and unchanged pixels never enter model context automatically.
- Credentials entered during takeover travel directly to the managed browser and never through the model.

Tauri can launch or resume a persistent profile in the visible managed browser runtime. A truly headless browser process cannot be assumed to become headed in place; visible takeover may require a headed session or a controlled relaunch using the same persistent profile followed by mandatory re-observation. Web and Docker retain the v0.2 screenshot, URL, status, and trace experience unless the implementation spike proves an interactive streamed viewer without destabilizing scope.

## Implementation spike and budgets

Candidate engine/protocol adapters are compared on the same representative dynamic-site tasks. The spike records:

- runtime and dependency footprint;
- cold start and warm action latency;
- idle and one-page memory usage;
- initial and post-action observation tokens;
- model turns and total tokens per successful task;
- extraction, recovery, and task-completion reliability.

The adapter is selected on successful-task efficiency, not framework popularity or the smallest individual snapshot. A lightweight protocol adapter is preferred, but reliability is not traded away for negligible client-library savings because the managed browser process and page content dominate runtime cost.

## Authority and trust

- Public read navigation follows policy.
- Login, upload, form submission, publishing, deleting, purchasing, and uncertain external writes require appropriate approval.
- Redirect beyond profile domains pauses.
- Plan Mode permits passive inspection and blocks external writes.
- Web content is untrusted and cannot modify system policy.
- MFA/CAPTCHA/consent pauses for user takeover.
- Downloads enter run staging, never execute, and require explicit workspace/Vault promotion.

## Client behavior

- Tauri may launch the managed browser visibly for takeover.
- Web/Docker guarantee headless execution, screenshots, URL, action trace, and status.
- A fully interactive streamed remote-browser viewer is not required for v0.2.0 unless the implementation spike proves it without destabilizing scope.
- Scheduled work never opens surprise windows; it pauses and notifies.

## Recovery

A reopened persistent session must re-observe before acting. Browser crashes become explicit interrupted/failed events. Missing/expired login produces actionable reauthentication, never credential prompts to the model.

## Tests first

- Safari-only clean-machine installation
- Corrupt/interrupted runtime install recovery
- Tool descriptions distinguish static `web_fetch` from rendered, interactive browsing
- `web_fetch` never executes JavaScript or starts the managed browser runtime
- Explicit transition from static fetch to browser use for the same URL
- Initial observation and post-action delta budgets
- Targeted expansion after bounded content omission
- One state-changing action per `browser_act`
- Browser process, context, and protocol-connection reuse
- Event-driven timeout and idle-process cleanup
- Research-mode resource blocking with normal-load fallback
- Semantic default without automatic screenshot/vision input
- Live-view frames and takeover credentials excluded from model context
- Isolated cookie separation
- Persistent state across runs/restart/update
- Profile lock/queue
- Domain redirect pause
- No cookie/password model exposure
- Prompt-injection resistance
- Plan Mode external-write denial
- Screenshot/download provenance
- Missing runtime actionable state
- Docker runtime parity
- Repeatable spike benchmark for latency, memory, turns, tokens, and completion reliability

## Deferred (v0.2.+)

- **Recorded browser flows** — capture an act sequence once, replay it
  deterministically without model turns (durable role+name targeting, not
  short-lived refs). Composes with Scheduler for repeated research runs.

## Implementation status (branch `feat/v0.2-browser`)

Built on raw CDP — no Playwright/Selenium dependency (decision: build from
scratch). Spike results in `scripts/spike_browser/RESULTS.md`.

**Implemented:**
- `browser/` module: `cdp.py` (session core — launch/attach/observe/act/
  extract/screenshot, dedicated reader task, event-driven waits, Fetch
  interception), `runtime.py` (managed install of pinned Chrome for
  Testing 145.0.7632.6 → `data/browser-runtime/`, sha256 + codesign +
  `--version` health check; binary resolution is exactly two auditable
  sources: `AGENTOS_BROWSER_BINARY`/`browser_binary` operator override or
  the managed install — no third-party cache scanning), `registry.py`
  (run-scoped ownership, 120s idle reaper, run-cancel + gateway-shutdown
  cleanup).
- Five capabilities: `browser_open` (egress+approval; `mode=research`,
  `profile`, `visible`), `browser_observe` (`scope` ref-or-CSS drill-in,
  `visual` screenshots → `artifacts/browser/`, vision-gated
  `_model_content`), `browser_act` (click/type/navigate/scroll →
  post-action delta), `browser_extract` (>20k staged to workspace),
  `browser_close`.
- Persistent profiles: `browser_profiles` DB table + operator CRUD at
  `/api/browser/profiles`; profile dirs under `data/browser-profiles/`;
  one live session per profile (honest lock refusal); `allowed_domains`
  enforced via Fetch interception armed before first navigation —
  out-of-scope Document requests are failed and recorded.
- Downloads → `Browser.setDownloadBehavior` into workspace `downloads/`,
  surfaced in deltas/observe, never executed.
- Research mode: `Network.setBlockedURLs` media/font/tracker blocklist
  with honest normal-load fallback.
- Token economics (spike-validated): interactive+landmark AX projection,
  80-element cap + omission marker, delta observations (~13 tokens),
  scoped observe, extract staging.
- Full action set: click/type/select/keypress/hover/navigate/scroll —
  real `Input.dispatch*` events, Enter submits forms (rawKeyDown→char→keyUp).
- Takeover: `browser_open(visible=true)` + `agent_ask_user` composes the
  pause-for-user flow; visible sessions exempt from the idle reaper;
  `visible` refused on non-interactive triggers (no surprise windows
  from scheduled work).
- iframe/shadow-DOM: shadow DOM is flattened into the default observation
  by a11y; `observe(scope=<iframe-ref|selector>)` swaps to the frame's own
  AX tree — works for same-origin AND cross-origin frames (browser-side
  a11y + backendNodeId routing); only JS extract stays top-frame-scoped.
- Domain redirect pause: out-of-scope navigation is blocked + recorded;
  `browser_act(navigate, url, allow_domain=true)` widens the session
  scope — the approval prompt is the operator's decision point.
- Crash: process loss → all pending/waiting calls fail with an honest
  BrowserError and the run can reopen; container flags
  (`AGENTOS_BROWSER_NO_SANDBOX` → --no-sandbox/--disable-dev-shm-usage)
  + Chromium shared libs in `backend/Dockerfile` for Docker parity.
- Untrusted-content stance is stated in `browser_open`/`browser_observe`
  descriptions (page text is never operator instruction).

**Still open:** visible-mode UI ("Watch Browser" — not required for
v0.2.0 per Client behavior; runtime/profile management UI lands with
W12 Dependencies). Remaining validation: real-world E2E runs against
live sites per `test_plan/04-browser-automation-test-plan.md`.

## Done when

An agent can research a JavaScript site headlessly within validated latency, resource, and context budgets; request visible takeover for a persistent login on desktop without sending the live visual stream or credentials to the model; resume safely; and produce auditable browser evidence without accessing personal browser data.
