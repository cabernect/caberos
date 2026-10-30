# Page: Notifications

> **Route:** `/notifications`
> **Overrides:** `design-system/caberos/MASTER.md`
> **Breadcrumbs:** Observability › Notifications

"What your agents need from you, and what they finished."

## Anatomy

PageHeader → `FilterPills` (All | Unread) → `grid-cols-1 lg:grid-cols-3`:
inbox list (col-span 2) + preferences column.

## Inbox rows

`ListRow`: `IconTile` tone by severity (warning/danger/sunken) + title +
`agent_name · detail` + local date (`toLocaleDateString` with month/day) +
trailing read-state dot + dismiss. Unread gets a filled dot — the word
"Unread"/shape carries state, not color alone. Click deep-links via
`action_path` and marks read. Retro-marks read when the focused entity is
open (`markReadForFocusedEntities`).

## Alerts right now

`SectionCard` — live attention roll (same needs-you set as Today).

## Preferences column

`NotificationPrefsForm` — delivery toggles + quiet hours (with local-time
explanation) + type filters.

## Toasts

`NotificationToasts` — transient top-right, SSE-first; dedupe is by
type+entity+unread.
