# v0.2.0 Notifications v2

## Outcome

CaberOS delivers in-app, browser, and Tauri/system notifications without duplicates and suppresses every surface when the exact related work is already focused and visible.

## Delivery model

```text
NotificationEvent
  → in-app inbox
  → in-app toast
  → browser Notification API
  → Tauri/system notification
```

External-channel delivery remains separately configured and audited. Browser and Tauri must not both create duplicate local desktop alerts.

## Exact-related-view suppression

Suppress all surfaces only when:

- document/window is visible and focused;
- current route is relevant;
- the exact session, run, approval, Plan, Schedule, or Artifact is selected.

A generic route match is insufficient. Suppressed views must update inline so no state change is hidden.

## Required behavior

- Permission onboarding without repeated prompts
- Separate browser/system permission state
- Per-event and per-delivery preferences
- Quiet hours
- Deep links
- Event-level idempotency/deduplication
- Cross-tab coordinator
- Delivery/read/dismiss state
- Fallback to in-app inbox
- Stale-link recovery
- Retry only failed delivery adapters

## Events

At minimum: run completion/failure/interruption, approval required/timeout, elicitation, Plan deviation/approval, Schedule failure, browser takeover/login, artifact completion/failure, Skill publication failure, Vault/index degradation, and update availability.

## Tests first

- Exact visible selection suppresses all.
- Different selected entity does not suppress.
- Hidden/minimized app produces native/browser notification.
- Multiple tabs produce one browser delivery.
- Browser and Tauri do not double-deliver.
- Permission denial preserves inbox.
- Deep links open exact entities/revisions.
- Stale targets degrade safely.
- Successful adapter is not repeated when another retries.

## Done when

The scheduled acceptance story creates exactly one attention request when needed and none while the exact related state is already visible.

---

## Design (locked 2026-10-05 — grilling session)

**Core rule: the inbox is the floor.** Every event writes a `notifications` row; suppression never deletes the record — it kills attention-requesting surfaces (toast/browser/system) and auto-marks the row read. "None while the exact related state is already visible" means zero attention requests, not zero records.

- **Idempotency:** `notifications.event_id` — deterministic emitter key (`{type}:{entity}:{occurrence/attempt}`), unique index, INSERT-or-ignore. Replaces the `(type, entity, unread)` collapse (which hid repeat failures). Content-hash fallback when no natural key.
- **Entity refs:** `entity_type` + `entity_id` + `action_path`. `entity_type` feeds suppression matching; `action_path` resolves at click time; stale target → entity's list page + "no longer exists" toast.
- **Delivery state:** `notification_deliveries(notification_id, adapter, state: delivered|suppressed|failed, attempts, updated_at)` — per-surface audit, drives "retry only failed adapters".
- **Preferences:** JSON blob on a singleton `notification_prefs` row — `{defaults, overrides:{event_type:{toast,browser,system,inbox}}, quiet_hours:{start,end,tz}, permissions:{browser_asked,tauri_asked}}`. Client enforces; quiet hours suppress all pings uniformly (no severity bypass), inbox still records.
- **Transport:** `GET /api/notifications/stream` (SSE) emits on create; 5 s poll stays as reconnect fallback. Required so suppressed rows are marked read before the badge can flicker.
- **Delivery coordinator (frontend):** SSE event → suppression check (union across tabs via BroadcastChannel) → prefs matrix → quiet hours → fire adapters → `POST /{id}/delivery` per outcome.
- **Cross-tab:** BroadcastChannel leader election — leader owns browser/system delivery + delivery reporting; toasts render per visible tab.
- **Adapters:** `isTauri()` → `tauri-plugin-notification`, else browser Notification API — never both.
- **Permissions:** opt-in — Settings toggle + one dismissible banner; `asked` flag means deny = permanent silence, degrades to inbox+toast.
- **Retry:** failed adapters retried once on SSE-connect/app-start, only if the row is still unread; then `failed` permanently.
- **Events:** real sources only — existing run/approval/elicitation/MCP/provider + new `schedule_failed` (heartbeat alert path; `schedule_*` names reserved for W8 merge), `artifact_completed/failed`, `skill_publish_failed`, `vault_index_degraded`, `browser_takeover_required`, `update_available` (`event_id=update_available:{version}`). `plan_*` deferred — no Plan entity.

## Implementation plan

**Backend**

1. `models/notification.py` — `+ event_id VARCHAR(50)`, `+ entity_type VARCHAR(50)`; new `models/notification_delivery.py`; new `models/notification_prefs.py` (singleton JSON row).
2. `db_backends/sqlite_backend.py` — patches: `notifications.event_id`, `notifications.entity_type`; `CREATE UNIQUE INDEX IF NOT EXISTS ux_notifications_event_id` (ALTER can't add UNIQUE; index + INSERT-or-ignore gives idempotency). New tables via `create_all` + model registration in `models/__init__.py`.
3. `notifications.py` — `create_notification(event_id=, entity_type=)`: INSERT-or-ignore on `event_id` (IntegrityError → return existing), then emit to SSE broker. Emitters pass deterministic keys.
4. `api/notifications.py` — `GET /stream` (SSE, asyncio.Queue fan-out, 5 s poll fallback client-side), `POST /{id}/delivery` (upsert delivery row), `GET /deliveries/failed` (retry candidates: failed/undelivered, unread only), `GET|PUT /prefs`.
5. **Emitters** — `scheduler.py` heartbeat threshold → `schedule_failed` (`event_id=schedule_failed:{agent}:{day}` — one per agent per day, not per-failure-spam); artifact service → `artifact_completed/failed`; `api/skills.py` publish 4xx/5xx → `skill_publish_failed`; `knowledge/indexing.py` generation→`failed`/degraded → `vault_index_degraded` (`event_id=vault_index_degraded:{gen_id}`); browser registry takeover point → `browser_takeover_required` (`:{profile}:{session}`); `api/notifications.py POST /emit` for `update_available:{version}` (UpdateChecker routes through the pipeline).

**Frontend**

6. `lib/notificationPrefs.ts` — types + fetch/put + matrix resolution (override→default→`{inbox:true, toast:true, browser:false, system:false}`); quiet-hours predicate (local-time window, tz-aware).
7. `lib/focusRegistry.ts` — focused-view registry: pages register `{entity_type, entity_id}` on selection (route+params); `isSuppressed(type,id)` union across tabs via BroadcastChannel gossip.
8. `lib/crossTab.ts` — leader election (claim/heartbeat/release), leader owns OS adapters + delivery reporting; gossip messages: `focus`, `delivered`, `dismissed`.
9. `lib/notificationStore.ts` → **delivery coordinator**: SSE subscribe (+poll fallback) → per event: suppressed? → `POST /{id}/delivery {suppressed}` + `mark-read` : prefs×quiet-hours → per enabled adapter → fire → report delivered/failed. Toasts render in every visible tab.
10. `lib/notifAdapters.ts` — `toastAdapter` (existing toast layer), `browserAdapter` (`window.Notification`, permission gate), `tauriAdapter` (`tauri-plugin-notification`, permission gate); pick system adapter: `isTauri() ? tauri : browser`.
11. `NotificationCenter.tsx` — dismiss/read; click → navigate `action_path`; route handlers 404 → list-page fallback + toast.
12. Settings → Notifications: per-event × per-surface matrix, quiet hours, browser/system permission toggles (separate states), one-time banner.
13. Tauri: `tauri-plugin-notification` dep + capability `notification:default`.

**Test plan** (maps to "Tests first")

| Plan test | Implementation |
|---|---|
| Exact visible selection suppresses all | vitest `focusRegistry` + coordinator: SSE event → 0 adapter calls, delivery=`suppressed`, row marked read |
| Different entity does not suppress | vitest: focused `{session:A}` vs event `{session:B}` → toast+browser fire |
| Hidden/minimized → native/browser | vitest `document.hidden` → system adapter fires; Playwright real check |
| Multiple tabs → one browser delivery | vitest: two coordinator instances sharing fake channel → leader only |
| Browser + Tauri no double-deliver | vitest: adapter picker returns exactly one system adapter per runtime |
| Permission denial preserves inbox | vitest: `Notification.permission='denied'` → row + delivery=`failed`, inbox intact |
| Deep links open exact entities | pytest: action_path route map; Playwright click-through |
| Stale targets degrade safely | vitest: click handler 404 → list route + toast |
| Successful adapter not repeated | vitest: `delivered` adapter skipped on reconnect retry; pytest `GET /deliveries/failed` returns only failed/unread |

---

## Implementation status (landed)

**Backend — done**
- `models/notification.py`: `Notification.event_id` + `entity_type`; `NotificationDelivery` (unique per `(notification_id, adapter)`, `state`/`attempts`/`error`); `NotificationPrefs` (singleton JSON row).
- `db_backends/sqlite_backend.py`: idempotent patches for `event_id`/`entity_type` + partial `UNIQUE` index on `event_id`.
- `notifications.py`: `create_notification(event_id=)` — deterministic key or content-hash fallback; savepoint + bounded retry so a unique-index race returns the winner without poisoning the caller's txn; broadcast fires on `after_commit` and is disarmed on `after_rollback` (no phantom SSE for rolled-back rows).
- `api/notifications.py`: `GET /stream` (SSE), `POST /{id}/delivery` (upsert + attempt counter), `GET /deliveries/failed` (unread + attempts<2 only), `GET|PUT /prefs` (defaults + shallow merge), `POST /emit`.
- Emitters wired: `schedule_failed` (heartbeat threshold, `:{agent}:{day}`), `vault_index_degraded` (index build fail + stale-reconcile, `:{gen_id}`), `browser_takeover_required` (visible-browser refusal, `:{run_id}`), `skill_publish_failed` (422 + SkillError, `:{skill}:{digest}`), `update_available` (`POST /emit` from UpdateChecker, `:{version}`). `artifact_*` intentionally skipped — synchronous tool calls already visible in-run; `run_completed/failed` covers the background case.

**Frontend — done**
- `lib/crossTab.ts` — BroadcastChannel leader election (min tab-id, heartbeat, stale eviction); focus + visibility gossip.
- `lib/focusRegistry.ts` — `setFocusedEntities()` per page; `isSuppressed()` = exact entity focused in any *visible* tab (local or peer union).
- `lib/notificationPrefs.ts` — cached prefs blob, `surfaceEnabled()` matrix resolution, `inQuietHours()` (overnight windows wrap midnight, no severity bypass).
- `lib/notifAdapters.ts` — `isDesktopMode() ? tauri-plugin-notification : window.Notification` — never both; permission state + request inside user gesture.
- `lib/notificationStore.ts` — delivery coordinator: SSE (`api.streamNotifications`) + 5 s poll fallback → suppression → prefs → quiet hours → adapters → per-adapter `POST /{id}/delivery`; failed-adapter retry on start/reconnect while unread; suppressed → auto-read (quiet-hours stays unread).
- `lib/notificationLinks.ts` — `notificationTarget()` action_path → entity-type list-page fallback.
- Components: `NotificationPrefsPanel` (on /notifications), `NotificationPermissionBanner` (one-shot opt-in, persists `asked`), Conversation registers `agent:`/`session:` focus keys, UpdateChecker emits `update_available`.
- Tauri: `tauri-plugin-notification` (Cargo + npm) + `notification:default` capability + plugin init.

**Tests — 11 pytest + 7 vitest, all green**
- pytest (`test_notifications.py`): event_id idempotency, distinct events not collapsed, two-connection race collapses (file-backed SQLite + real unique index), delivery upsert/attempts, failed-delivery filtering (unread + attempts<2), prefs defaults/merge, broadcast only after commit, rollback never broadcasts, `/emit` dedup.
- vitest (`notificationStore.test.ts`, `notificationPrefs.test.ts`, `focusRegistry.test.ts`): toast delivery+report, suppression kills all pings + auto-reads + records, quiet-hours stays unread, follower toasts but never reports/fires OS, leader-only OS delivery, failed adapter retried once while delivered is not, baseline rows never deliver; quiet-hours windows; suppression key union incl. peer tabs.

**Gates**: backend 765 passed · ruff clean · frontend 53 vitest · tsc clean · vite build · cargo check (tauri-plugin-notification).

**Deferred**: Playwright permission/suppression/deep-link flows; per-page stale-target toasts (pages currently degrade by ignoring unknown params); `plan_*` events (no Plan entity); artifact events (covered by run lifecycle).
