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
