# W9 Test Results — Notifications v2 (inbox, prefs, SSE, cross-tab delivery)

**Run:** 2026-10-05 (first pass + fix re-verification same day; B38 fix + W8-merge rebase same day)
**Branch / tested code:** `feat/v0.2.0` — passes 1–2 ran @ `dcac96a` + uncommitted W9 worktree; pass 3 + B38 fix ran on the post-pull tree incl. W8 merge `141ab98` (scheduler v2, `schedule_failed` emitter rewrite — the merge's missing `event_id` was restored under B38)
**Environment:** macOS; backend `127.0.0.1:8081` (uvicorn, restarted on the W9 build); frontend Vite `:5173`; real browser via Playwright MCP (headed Chromium, profile `mcp-chrome-0ed652a`). Auth via a temporary minted operator session `w9-*` (revoked at cleanup — verified 401).
**Gates:** `test_notifications.py` **12/12**; `test_knowledge_rag.py` **34/34**; `test_scheduler.py` **45/45** (post-W8-merge); frontend Vitest **60/60** (incl. B35/B36/B38 regressions); `tsc --noEmit` clean.

## Verdict

**PASSING after fix verification.** First pass found **B34** (degraded-active index build never notifies) and **B35** (prefs lost-update via full-blob PUT). The re-verification pass fixed both and surfaced two more real defects in the same run — **B36** (peer tabs never learn prefs changes; leader pinged through quiet hours on a stale cache) and **B37** (`ERR_INSUFFICIENT_RESOURCES` reproduced live: unbounded 5 s poll + store re-instantiation could still exhaust the socket pool). **All four fixed and re-verified live** — see "Fix re-verification (2026-10-05, second pass)" below. Backend contracts and the browser delivery coordinator pass end-to-end.

## Results by case

| Case | Result | Evidence |
|---|---|---|
| §1.1 emit durability | PASS | `POST /notifications/emit` → row persisted with `event_id`, `entity_type`, `action_path`, `read:false`. |
| §1.2 event_id dedup | PASS | Duplicate `event_id` emit → same notification id returned, no second row. |
| §1.3 concurrent emit race | PASS | 5 parallel emits same `event_id` → exactly **1** row. |
| §1.4 content-hash dedup | PASS | Same content → deduped; changed content → new row. |
| §1.5 read / read-all | PASS | `mark-read` flips `read`; `read-all` clears the badge set. |
| §2.1 delivery upsert | PASS | Second report for same `(notification, adapter)` updates the row, `attempts` increments (observed up to 3). |
| §2.2 failed-delivery filter | PASS | `unread + failed + attempts<2` listed; read rows excluded; `attempts>=2` excluded. Response shape `{notification, adapter, attempts}`. |
| §3.1/§3.2 prefs defaults + wholesale overrides | PASS | Defaults `{inbox,toast:true; browser,system:false}`; `overrides` replace wholesale (empty map removes key). |
| §3.3 prefs persistence | PASS | Server blob survives backend restart unchanged. |
| §4 SSE contract | PASS | First frame `{"type":"hello"}`; one `notification` frame per committed row; duplicate `event_id` → no second frame; keepalive observed. |
| §5.1 `schedule_failed` | PASS | Heartbeat 1min/threshold 3 on `caber` → `schedule_failed:caber:2026-10-05` fired **once** (agent+day dedup) despite continued failures. |
| §5.2 `vault_index_degraded` | **FAIL → B34** | Corrupted embedding key → `POST /index/rebuild` returned **200**, generation `active` with `failed:6552`, reason "embedding resource not ready" — **no notification emitted**. `_notify_index_degraded` is only reached on the exception path and stale-build reconcile, not on degraded-but-successful activation. |
| §5.3 `skill_publish_failed` | PASS | Invalid draft publish → 422 + `skill_publish_failed:{draft}:{digest}`; identical repeat publish deduped. |
| §5.5 `update_available` | PASS | Real-shape event dedupes on `update_available:{version}`. |
| §6.1 toggle grant path | PASS (grant-arm simulated) | Real `Notification.permission` already `granted` in the test profile. Toggle OFF→ON → `toast:true browser:true`, `browser_asked:true`; emit → `toast/delivered` + `browser/delivered` rows (real OS ping fired). |
| §6.2 denied degradation | PASS | `Notification.permission` overridden to `denied` → settings shows "Browser alerts are blocked — enable them in browser site settings"; toggle writes `browser:false`; with `browser:true` forced, emit → `browser/failed` `error=permission_denied`, toast unaffected. |
| §6.3 toggle-off silence | PASS | `toast:false browser:false` → emit lands unread inbox row, **zero** delivery rows. |
| §6.4 one-shot banner | PASS w/ env caveat | On a fresh origin (`127.0.0.1:5173`, permission `default`, `browser_asked:false`) the banner appeared after the first real notification: "Enable browser notifications?". "Not now" → `browser_asked:true` persisted, banner closed, never re-shows. **Enable-arm:** headless Chromium leaves `requestPermission()` pending — the grant path inside the banner wasn't exercised to completion (the identical `requestOsPermission` path via the settings toggle was). |
| §7.1 entity suppression | PASS | Viewing session `dff17739` → emit `run_completed` with `entity_type=session` + `action_path` pointing at it → row auto-`read:true`, `toast/suppressed` + `browser/suppressed`, no toast in DOM. |
| §7.2 quiet hours | PASS | Window containing local now → emit → `read:false` + `toast/suppressed` + `browser/suppressed`. Outside-window run delivered normally. **Note:** quiet hours evaluate in *browser local time* (UTC+7 here) while backend logs are UTC — a window test must be authored against local time. |
| §8.1 single leader / one stream | PASS | `lsof` upstream conns to :8081 stayed at **2** when a second same-origin tab joined — the follower holds no SSE; notification gossip rides `BroadcastChannel("agentos-notifs")`. |
| §8.2 per-tab toasts | PASS | Toast renders in the visible tab; hidden tab stays silent; leader reports aggregate `toast/delivered` when any peer is visible. |
| §8.3 failover | PASS | Closed the leader → survivor promoted, opened its own SSE (conn count stable), next emit delivered `toast` + `browser`. |
| §8.4 poll fallback | PASS | During backend restart the 5s `GET /api/notifications` poll was observed filling the SSE gap in the backend log. |
| §9 deep links | PASS | "Open related page" on a real session link → `/agents/caber/chat?session=…` rendered the conversation; a dead-session link degraded gracefully to the chat/session-list view (no crash, per `notificationTarget` design). |
| §10.1 restart durability | PASS | Prefs blob + unread set unchanged across `kill -9` + restart. |
| §10.2 baseline no-refire | PASS | Page reload with 100 unread rows → **0** toasts (baseline marks existing ids seen). |
| §10.3 retry once on reconnect | PASS | Unread failed `browser` delivery (`attempts=1`) got a fresh attempt after the reconnect (`error` updated `permission_denied → permission_default`); a **read** failed row was correctly skipped. |

## Defects filed

| # | Summary | Status |
|---|---|---|
| B34 | `vault_index_degraded` never fires for a degraded-but-active generation; notify path only ran on exceptions/stale reconcile. | FIXED — re-verified live (below) |
| B35 | Notification prefs lost-update: `saveNotificationPrefs` PUT the caller's full cached blob; stale writer reverts newer fields. | FIXED — re-verified live (below) |
| B36 | Peer tabs never learn prefs changes — leader kept delivering through quiet hours on a stale cache until it happened to reload. Surfaced in the re-verification run. | FIXED — re-verified live (below) |
| B37 | `ERR_INSUFFICIENT_RESOURCES` reproduced in Playwright: unbounded 5 s poll (`setInterval` on async fn, no fetch timeout) + store/crossTab re-instantiation could still exhaust the socket pool. | FIXED — re-verified (below) |

## Operational notes / caveats

- **Cross-origin tabs are independent leader groups.** `localhost:5173` and `127.0.0.1:5173` do not share a BroadcastChannel — each elects a leader, each reports deliveries, last write wins per `(notification, adapter)` row. Rare in production, but it made delivery rows look wrong until diagnosed (B35-adjacent, same root: reporting is per-tab-idempotent but not per-origin-deduplicated).
- **Graceful shutdown wedges on open SSE.** `SIGTERM` left uvicorn draining >90 s with the notification stream attached; `kill -9` required — same behavior noted during W8.
- Browser `requestPermission()` pending-forever in headless Chromium limited §6.4's Enable arm and §6.1's real prompt motion; the equivalent code path was verified through the settings toggle and a fresh-origin banner.
- All `toast`/`browser` delivery rows come from the client-reported `POST /deliveries` audit — the OS-level ping itself can't be asserted in headless automation; `delivered` means the adapter executed `new Notification()` without throwing.

## Cleanup

35 test notifications (`test:*`, `w9-*`, probe emitter rows) + 39 delivery rows deleted; 185 pre-existing notifications preserved. Caber heartbeat probe disabled, `consecutive_failures` cleared, all 6 managed heartbeat schedules disabled at baseline. Provider `encrypted_key`s verified decryptable (Fernet) — earlier corruption restored. Notification prefs reset to `{toast:true, browser:false, quiet disabled}` + `browser_asked:true`. `w9-*` token revoked → 401. `PRAGMA wal_checkpoint(TRUNCATE)` → 0 WAL, `integrity_check` ok, `/health` ok. Playwright browser closed; `Notification.permission` override removed.

Second-pass cleanup: `test:*` / `update_available:*` probe rows + their delivery rows deleted (the real `vault_index_degraded` row for generation `5618f6f0` kept — genuine signal). Second minted sessions (`w9test-*`, `w9test-ka`) revoked → 401 verified. Prefs restored to `{toast:true, browser:false, quiet_hours disabled, browser_asked:true, tauri_asked:false}`. Backend left running on the fixed build (PID 82503); `/health` ok.

---

## Fix re-verification (2026-10-05, second pass)

The fixes were exercised live against a restarted backend on `:8081` (PID 63073 → 82503) — not taken on trust. Gates: `test_notifications.py` **12/12** (+`test_prefs_patch_merges_onto_stored`), `test_knowledge_rag.py` **34/34**, Vitest **58/58** (+null-delete override regression, +B36 gossip-reload test), `tsc` clean.

| Bug | Live re-verification evidence |
|---|---|
| B34 | `POST /api/knowledge/index/rebuild` with the still-`unvalidated` embedding resource → generation `5618f6f0` committed `status=active`, `0/6552` embedded, reason "embedding resource not ready" → `vault_index_degraded` notification emitted immediately: title "Knowledge index degraded", message `activated degraded — 0/6552 chunks embedded`, `event_id=vault_index_degraded:{generation.id}`, `action_path=/knowledge`. Observed fanning out live over SSE to a connected stream, and the leader tab reported `toast\|suppressed`. A second rebuild would dedup per-generation via `event_id`. |
| B35 | New `put_prefs` merges onto the **stored** row. Live sequence: `{"quiet_hours":{enabled:true,14:00-16:00}, "overrides":{run_failed:{toast:false}}}` → then `{"permissions":{"tauri_asked":true}}` → quiet hours + override **survived** (previously wiped to defaults). `{"overrides":{"run_failed":null}}` → key deleted, sibling override kept. Omission never deletes. Frontend callers all send owned keys only (toggle, quiet-hours inputs, override selects `null`/partial, banner `markAsked`). |
| B36 | Reproduced first: quiet hours enabled covering now via PUT → leader tab still reported `browser\|delivered` + `toast\|delivered` (stale cache). After `prefs` gossip wired (`saveNotificationPrefs` → `broadcastPrefsChanged` → peers `loadNotificationPrefs()`), a prefs-reloaded re-emit → `toast\|suppressed` + `browser\|suppressed`, row stays `read:false`. Vitest asserts the gossip→refetch hook. |
| B37 | Playwright console captured `net::ERR_INSUFFICIENT_RESOURCES @ /api/notifications` in ~4/sec bursts — the poll failing against an exhausted pool; navigation timed out (the user's original symptom). Causes fixed: poll now serialized (`pollInFlight`) + bounded (`AbortSignal.timeout(15s)`); `notificationStore`/`crossTab` register `globalThis` cleanups so a re-instantiated module always kills the previous timers/socket/channel even when `import.meta.hot.dispose` is bypassed. Post-fix live emits each produced exactly one delivery row per adapter (leader-only reporting holds); `lsof` stream count = one per browser instance, not per tab. |

### Re-verification scope notes (honest)

- The **second** pass re-ran §1–§4 API contracts end-to-end (emit/dedup/race/hash/upsert/retry-filter/patch-merge/SSE hello+frame+keepalive): all PASS, consistent with first pass.
- The `vault_index_degraded` degraded-rebuild path (plan §5.3) is the newly live-verified one; §5.1 `schedule_failed` and `skill_publish_failed` results stand from the first pass.
- §6.1 re-confirmed (toggle OFF→ON in a `granted` browser → `browser:true` persisted → `browser|delivered` + `toast|delivered` rows); §6.2/§6.4 stand from first pass.
- §7.3 re-run is where B36 was caught; §7.1/§7.2 stand.
- §8.4's HMR regression is where B37 was caught and fixed; socket counts stayed flat after the singleton guards.
- Not re-run (stand from first pass or environment-limited): §5.4 `browser_takeover_required`, §6.5 Tauri desktop path, §8.3 leader failover live, §8.5 kill-backend poll-gap, §9.3 OS-notification click, §10.3 retry-on-reconnect (unit-covered).

---

## Independent re-verification (2026-10-05, third pass — agent-browser)

The "all fixed" claim was re-tested from scratch against the running build (backend PID 82503), not taken on trust. Tooling: `agent-browser` (3 same-origin `localhost:5173` tabs), direct API + DB inspection. Gates re-run: `test_notifications.py` **12/12**, frontend Vitest **58/58**.

| Bug | Verdict | Independent evidence |
|---|---|---|
| **B34** | **FIXED** | Fresh `POST /api/knowledge/index/rebuild` against the still-`unvalidated` embed resource → generation `6cec83e3-2da1-42d5-a40a-d182049468f9` committed `status=active`, `embedded=0`, `failed=6552`, "embedding resource not ready" → new notification row `vault_index_degraded:6cec83e3-…`, title "Knowledge index degraded", message carries `0/6552` + reason, `action_path=/knowledge`, unread. Emission is per-generation (`event_id` keyed by gen id) so each degraded gen surfaces once — correct dedup shape. |
| **B35** | **FIXED** | Live merge sequence: seed `{"quiet_hours":{14:00-16:00,on},"overrides":{run_failed,elicitation_required}}` → PUT `{"permissions":{"tauri_asked":true}}` → quiet hours + **both** overrides survived (previously wiped). PUT `{"overrides":{"run_failed":null}}` → only that key deleted, sibling kept. `saveNotificationPrefs` sends the patch, not the blob — whole-blob last-writer-wins is no longer reachable from any caller. |
| **B36** | **FIXED** | 2 same-origin tabs; tab A's cache held quiet `14:00–16:00` (excludes 16:0x). Widened the window to `14:00–17:00` **via tab B's settings UI** → `broadcastPrefsChanged` → tab A's `onPrefsChanged → loadNotificationPrefs()`. Emit `test:v2gossip1` → tab A showed **no toast** (its cache refreshed — a stale tab would have toasted) and the leader reported `toast\|suppressed`, `attempts=1`, row stays unread. No reload anywhere. |
| **B37** | **FIXED** | 3 same-origin tabs → exactly **1** upstream `:8081` TCP connection (leader-only SSE, held across a third tab joining + re-election). `pollInFlight` serialization + `AbortSignal.timeout(15s)` confirmed in source; no poll bursts or `ERR_INSUFFICIENT_RESOURCES` in console/network across the whole session. Live emit → exactly one delivery row per adapter, `attempts=1`. Global `__agentosNotifStoreStop`/`__agentosCrossTabStop` cleanup hooks present in source. |

### New defect found this pass

**B38 (FIXED 2026-10-05):** notifications first poll-seen while a tab is a follower were permanently never reported. `process()` marked `seenIds` before the `leader` gate — a follower that polled a new item during election churn marked it seen and skipped reports; `retryFailedDeliveries` only retries existing `failed` rows, so the items stranded with zero delivery rows. Reproduced: `test:v2burst1-5` emitted during tab-join/reconnect churn → 0 delivery rows minutes later, still unread. **Fix:** `deferredReports` — follower-processed unread ids replay through `process(n, reportsOnly=true)` on promotion (leader-side pass incl. OS adapter; no duplicate toast). Covered by two regressions in `notificationStore.test.ts` (promotion reports deferred items; promotion skips already-read items) — 12/12 file green, tsc clean. **Same-commit follow-up:** `schedule_failed` emitter regained a deterministic `event_id` (`{type}:{schedule_id}:{day}`) after the W8 merge dropped it — identical errors on new streaks notify again.

### Scope notes (this pass)

- B34 verified on a **fresh** generation (the prior `5618f6f0` row was the agent's own evidence); both degraded notifications kept in the DB — genuine system state, index remains degraded.
- SSE frame-level assertion for the degraded emit not re-run (SSE contract proven earlier; emit path is the same `create_notification` fan-out).
- HMR re-instantiation path verified by source + singleton-guard behavior (conn count stayed 1 through tab churn), not by a forced Vite dependency reload.
- Headless environment caveat stands: `Notification.permission=default` in the fresh profile; OS-level pings unassertable.
- Poll-while-follower gap (B38) only reachable under multi-tab churn — single-tab and settled-leader flows report correctly.
