# W9 Test Plan — Notifications v2 (durable operator notifications)

**Audience:** an agent executor. Every case has an exact command + a
machine-checkable assertion. Branch under test: `feat/v0.2.0` (W9, uncommitted).

**What W9 added:** `Notification.event_id`/`entity_type` (idempotent emit,
deep-linkable target), `NotificationDelivery` (per-adapter outcome audit),
`NotificationPrefs` singleton (surface matrix + quiet hours + permission
flags), `POST /api/notifications/emit`, `GET /stream` (SSE fan-out, one event
per committed row), `POST /{id}/delivery`, `GET /deliveries/failed` (retry
candidates), `GET|PUT /prefs`. Frontend: delivery coordinator (SSE + 5 s
poll fallback → suppression → prefs → quiet hours → adapters → delivery
report), cross-tab leader election with BroadcastChannel gossip (only the
leader holds the SSE socket + reports deliveries + fires OS pings),
focus/visibility suppression, one master toggle in Settings → General,
one-shot permission banner, deep-link fallbacks, `import.meta.hot.dispose`
cleanup (HMR must not leak streams).

**Fixtures:** one working agent (`$AGENT`), one browser at
`http://localhost:5173` (web path) — Tauri desktop path is a separate
manual pass (§6.5, §8.4). DB: `backend/data/agentos.db`.

---

## 0. Setup

```bash
cd backend
uv run uvicorn agentos.main:app --host 127.0.0.1 --port 8081 &
# wait for: curl -s http://127.0.0.1:8081/health → {"status":"ok"}

cd ../frontend && npm run dev &   # :5173

TOKEN=$(curl -s -X POST http://127.0.0.1:8081/api/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"<operator>","password":"<password>"}' \
  | python3 -c 'import json,sys;print(json.load(sys.stdin)["session_token"])')
H="Authorization: Bearer $TOKEN"
API=http://127.0.0.1:8081/api/notifications
DB=data/agentos.db
```

Clean slate: `POST $API/read-all` so nothing is unread; note the starting
row count via `GET $API`.

---

## 1. Inbox durability + event-level idempotency

The inbox is the audit floor — every emit lands exactly once, no matter
how the caller retries.

**1.1 Emit → durable row**

```bash
curl -s -X POST $API/emit -H "$H" -H 'Content-Type: application/json' \
  -d '{"notification_type":"run_failed","severity":"error",
       "title":"Run failed","message":"boom","event_id":"test:e1",
       "entity_type":"run","entity_id":"r1","action_path":"/agents/x/chat?session=s1"}'
```

Assert: response is a `Notification` with `id`, `event_id:"test:e1"`,
`read:false`. `GET $API` lists it first. Row exists in sqlite:
`uv run sqlite3 $DB "SELECT event_id FROM notifications WHERE event_id='test:e1'"`.

**1.2 Same event_id twice → one row**

```bash
# repeat the exact same curl twice
curl -s $API -H "$H" | python3 -c 'import json,sys;print(sum(1 for n in json.load(sys.stdin) if n["event_id"]=="test:e1"))'
```

Assert: `1`. Both calls returned a row (the second returns the winner),
but only one exists. No new unread badge delta on the second.

**1.3 Concurrent same-event_id → one row (race)**

```bash
for i in 1 2 3 4 5; do
  curl -s -X POST $API/emit -H "$H" -H 'Content-Type: application/json' \
    -d '{"notification_type":"mcp_connection_failed","title":"MCP down",
         "message":"x","event_id":"test:race1"}' &
done; wait
curl -s $API -H "$H" | python3 -c 'import json,sys;print(sum(1 for n in json.load(sys.stdin) if n["event_id"]=="test:race1"))'
```

Assert: `1` — all five calls succeed, exactly one row survives. (Savepoint
+ bounded retry inside `create_notification`.)

**1.4 No event_id → content-hash dedup**

```bash
curl -s -X POST $API/emit -H "$H" -H 'Content-Type: application/json' \
  -d '{"notification_type":"update_available","title":"Update",
       "message":"v0.2.0 is available"}'   # twice
```

Assert: identical bodies → one row (hash-deduped); different `message` →
a second row. This is why re-checking for the same update can't re-notify.

**1.5 Mark read / read-all**

```bash
curl -s -X POST $API/<id>/read -H "$H"
curl -s "$API?unread_only=true" -H "$H"
```

Assert: the row leaves `unread_only`. `POST /read-all` clears the rest.

---

## 2. Delivery audit + retry semantics

The backend can't see adapter outcomes — the leader tab reports them;
these endpoints are the audit + retry contract.

**2.1 Upsert per adapter, attempts increment**

```bash
NID=<notification id>
curl -s -X POST $API/$NID/delivery -H "$H" -H 'Content-Type: application/json' \
  -d '{"adapter":"browser","state":"failed","error":"denied"}'
curl -s -X POST $API/$NID/delivery -H "$H" -H 'Content-Type: application/json' \
  -d '{"adapter":"browser","state":"delivered"}'
uv run sqlite3 $DB "SELECT adapter,state,attempts FROM notification_deliveries WHERE notification_id='$NID'"
```

Assert: one row per `(notification_id, adapter)` — two reports →
`attempts=2`, `state=delivered` (latest wins).

**2.2 `/deliveries/failed` filter — only retry candidates**

```bash
# unread + failed + attempts<2 → listed
curl -s $API/deliveries/failed -H "$H"
# now mark the notification read → it must drop out
curl -s -X POST $API/$NID/read -H "$H"
curl -s $API/deliveries/failed -H "$H"
# and a row that already retried once (attempts=2, still failed) is out too
uv run sqlite3 $DB "UPDATE notification_deliveries SET state='failed' WHERE notification_id='$NID' AND adapter='browser'"
curl -s -X POST $API/$NID/delivery -H "$H" -H 'Content-Type: application/json' \
  -d '{"adapter":"browser","state":"failed"}'   # attempts → 3
curl -s -X POST $API/read-all -H "$H"
```

Assert: unread+failed+attempts<2 listed; read rows excluded; attempts≥2
excluded. Retry is bounded — the inbox row is the floor.

---

## 3. Preferences

**3.1 Defaults on a fresh DB**

```bash
curl -s $API/prefs -H "$H"
```

Assert: `defaults:{inbox:true,toast:true,browser:false,system:false}`,
`overrides:{}`, quiet hours `22:00→07:00` disabled, both `*_asked` false.

**3.2 Overrides replace wholesale (regression: deleted keys must not
resurrect)**

```bash
curl -s -X PUT $API/prefs -H "$H" -H 'Content-Type: application/json' \
  -d '{"defaults":{"inbox":true,"toast":true,"browser":false,"system":false},
       "overrides":{"run_failed":{"toast":false,"browser":false,"system":false}},
       "quiet_hours":{"enabled":false,"start":"22:00","end":"07:00","tz":null},
       "permissions":{"browser_asked":false,"tauri_asked":false}}'
# then send the same blob with overrides {} — the key must be gone
curl -s -X PUT $API/prefs -H "$H" -H 'Content-Type: application/json' \
  -d '{"defaults":{"inbox":true,"toast":true,"browser":false,"system":false},
       "overrides":{},
       "quiet_hours":{"enabled":false,"start":"22:00","end":"07:00","tz":null},
       "permissions":{"browser_asked":false,"tauri_asked":false}}'
curl -s $API/prefs -H "$H" | python3 -c 'import json,sys;print(json.load(sys.stdin)["overrides"])'
```

Assert: `{}`. (This is the "Default option in the dropdown snaps back"
bug — merged overrides resurrected the key.)

**3.3 Prefs survive a gateway restart** — PUT a non-default blob, restart
uvicorn, GET → identical blob.

---

## 4. SSE contract

**4.1 One event per committed row**

```bash
curl -N -s $API/stream -H "$H" > /tmp/notif-sse.log &
sleep 1
curl -s -X POST $API/emit -H "$H" -H 'Content-Type: application/json' \
  -d '{"notification_type":"elicitation_required","title":"Q","message":"?","event_id":"test:sse1"}'
sleep 1; grep -c 'test:sse1' /tmp/notif-sse.log
```

Assert: `data: {"type":"hello"}` arrives first, then exactly one
`{"type":"notification","notification":{...event_id:"test:sse1"...}}`.
Emitting the same `event_id` again produces **no** second SSE frame —
dedup happens before broadcast (idempotent emits don't ping).

**4.2 Keepalive** — leave the stream open 30 s → `: keepalive` comments
arrive, connection stays up.

**4.3 Rolled-back writes never broadcast** — covered by pytest
(`test_notifications.py` commit/rollback cases); manual skip acceptable.

---

## 5. Real emitters — events come from real failures, not `/emit`

**5.1 `schedule_failed` — heartbeat failure threshold (once per agent/day)**

Give `$AGENT` a heartbeat schedule (interval, e.g. 60 s) and break its
provider (delete key / point base_url at a dead port) so every tick fails.

Assert: after `consecutive_failure_threshold` (default **3**) misses, a
`schedule_failed` notification exists:
`GET $API | jq '.[] | select(.notification_type=="schedule_failed")'` —
exactly **one** for that agent+day even though failures continue
(`event_id` keyed on schedule+date). Restore the provider → next tick
succeeds → no new row.

**5.2 `skill_publish_failed`**

In Skills Studio (or API) publish a draft that fails validation/service
→ `skill_publish_failed` row with `entity_type:"skill"`, `action_path`
→ the skill. Repeating the same failed publish dedups (event_id contains
a content digest).

**5.3 `vault_index_degraded`**

With a hybrid retrieval profile + dead embedding provider:
`POST /api/knowledge/index/rebuild` → generation fails →
`vault_index_degraded` notification links to `/vault`. Same for a stale
build found at startup reconcile (`status → failed`).

**5.4 `browser_takeover_required`** (manual/heavier — optional)

Start a browser session in `visible` mode where the tool refuses without
operator takeover → `browser_takeover_required` row, deep link to the
browser settings/session.

**5.5 `update_available`** — UpdateChecker emits via `POST /emit` with
`event_id:"update_available:{version}"`; re-checks for the same version
can't re-notify (content-hash/event dedup).

---

## 6. The toggle + permission reality (web UX)

Settings → General → Notifications. One switch governs toasts + OS pings;
the inbox always records.

**6.1 Fresh permission (`default`) — one motion**

In a browser where `Notification.permission === "default"` for the origin:
flip **Enable notifications** on.

Assert: the browser's own permission prompt appears **inside the click**
(no separate enable step). Choose Allow → toggle stays on;
`GET /prefs` → `defaults.toast=true`, `defaults.browser=true`,
`permissions.browser_asked=true`. Emit a test event (`POST /emit`) →
toast in-tab AND a browser notification.

**6.2 Denied — honest degradation**

Browser state `denied` (block it in site settings first): flip the toggle
on.

Assert: toggle enables (toasts still work — `defaults.toast=true`,
`defaults.browser=false`); the inline hint "Browser alerts are blocked —
enable them in browser site settings" appears under the row. Emit → toast
but **no** OS ping; `POST /emit` + check `/deliveries/failed` later shows
the browser adapter failed (bounded retry, then inbox-only). The app
never re-prompts — browsers forbid it.

**6.3 Toggle off → silence**

Flip off → `GET /prefs` `defaults.toast=false`, `defaults.browser=false`.
Emit → inbox row appears, zero toasts, zero OS pings, **no** delivery
rows written for disabled surfaces:
`sqlite3 $DB "SELECT COUNT(*) FROM notification_deliveries WHERE notification_id='<id>'"` → 0.

**6.4 Banner is one-shot**

With `browser_asked=false` + permission `default` + at least one
notification: banner appears bottom-center. "Not now" / ✕ → closes
immediately **even if the prefs PUT fails** (disconnect backend to
prove it) — and never returns for that surface (`asked` persisted).

**6.5 Tauri desktop (manual)** — same section in the app: toggle label
says "desktop"; enabling asks the macOS notification permission;
granted → `defaults.system=true`; pings arrive as OS notifications.
Browser and Tauri adapters never both fire.

---

## 7. "I'm already looking at it" — suppression + quiet hours

**7.1 Focused entity suppresses everything except the record**

Open the conversation for `$AGENT`'s session (focused+visible tab).
Emit an event whose `action_path`/entity points at that session:
`POST /emit` with `action_path:"/agents/<a>/chat?session=<s>"`,
`entity_type:"session"`, `entity_id:"<s>"`.

Assert: **no toast, no OS ping**; inbox row appears already `read:true`;
deliveries report `suppressed` for each enabled surface.

**7.2 Suppression unions across tabs**

Tab A focuses the session, tab B is on another page (both visible —
two windows side by side). Emit the same-target event.

Assert: no pings in **either** tab — being looked at anywhere means no
attention request anywhere.

**7.3 Quiet hours — silent but unread**

Enable quiet hours covering the current time. Emit an event.

Assert: row lands `read:false`, no toast/ping; after the window ends (or
toggling quiet hours off) the row is still there unread — it waits for
you rather than waking you. Overnight window: `22:00→07:00` suppresses at
23:00 and 03:00, not at 12:00 (end-exclusive).

---

## 8. Multi-tab reality + the connection cap

This is the real-world failure W9 must not reintroduce: browsers cap
6 HTTP/1.1 connections per origin; every tab holding its own SSE socket
starves page loads.

**8.1 One OS ping per event across tabs**

Two tabs open, both enabled. Emit.

Assert: exactly **one** browser/OS notification; toast renders in every
*visible* tab; delivery rows report once per adapter (leader only).

**8.2 Only the leader holds the stream**

DevTools → Network on both tabs, filter `notifications/stream`.

Assert: exactly one tab has the stream open; the other shows none (it
receives events via BroadcastChannel gossip — close the leader tab and a
new event still appears in the follower, proving gossip works).

**8.3 Leader failover**

Close the leader tab → the follower re-elects, opens `/stream` within a
heartbeat, and picks up `retryFailedDeliveries`. New emits still toast.

**8.4 HMR must not leak connections (dev regression)**

`npm run dev`; open one tab; touch `notificationStore.ts` several times
(each triggers HMR). `lsof -nP -iTCP:5173 | grep -c ESTABLISHED` per
browser process stays flat — `import.meta.hot.dispose` kills the old
SSE + poll + BroadcastChannel. Page reloads never hang waiting for a
socket slot.

**8.5 Poll fallback covers SSE gaps**

`POST /emit` while the leader stream is down (kill backend briefly or
block the route) → within ~5 s the poll finds the row and the pipeline
still fires (toast + delivery report).

---

## 9. Deep links + stale targets

**9.1 Toast click → exact entity**

Toast for a run event → click → navigates to `/agents/{a}/chat?session={s}`
(the `action_path`), not the inbox.

**9.2 Stale target → safe fallback**

Emit a notification pointing at a session/agent, then delete the target
(delete the session or agent). Click the notification in the inbox.

Assert: the target page's loader fails → falls back to the entity's list
route — never a dead screen or blank route. (Per-page "no longer exists"
toasts are a documented gap, not a blocker.)

**9.3 OS-notification click** (web): browser ping click focuses/opens the
tab and navigates to `action_path`.

---

## 10. Durability + restart

**10.1 Rows survive restarts**

Note unread count → restart uvicorn → `GET $API` identical; the UI badge
matches.

**10.2 Baseline never re-pings old rows**

With existing unread notifications, **reload the page**.

Assert: zero toasts on load — the first fetch is a baseline; only events
*newer* than baseline deliver. (Reloading the app must never re-alert you
about things you already saw.)

**10.3 Failed delivery retries once on reconnect**

Force a failed adapter row (§6.2 path or §2), keep the notification
unread, restart the stream (reload tab).

Assert: the adapter fires **once** more (`attempts` ≤ 2 in
`notification_deliveries`); a second reload does nothing — bounded, and
only while unread.

---

## Known limits (honest)

- **Denied permission is unrecoverable in-app** — browsers hard-block
  re-prompting; the UI can only point at site settings. By spec, not a bug.
- **Quiet-hours `tz` field is stored but inert** — evaluation is always
  local time.
- **`artifact_*`/`plan_*` not emitted** — artifacts are synchronous
  in-run ops; Plan entity doesn't exist. Names reserved.
- **Follower tabs without the leader** get events via 5 s poll (gossip
  arrives only from a live leader).
- **Playwright e2e** for permission prompts/cross-tab/deep-link flows is
  deferred — §6–§9 above are manual/Playwright-MCP steps.
- **`/deliveries/failed` filter caps at attempts<2** — a permanently
  failing adapter goes quiet after one retry; the inbox row is the record.
