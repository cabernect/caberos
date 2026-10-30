# Page: MCP servers

> **Route:** `/mcps`
> **Overrides:** `design-system/caberos/MASTER.md`
> **Breadcrumbs:** Capabilities › MCPs

Connect external tools — "decide exactly what each one may do."

## Anatomy

PageHeader (+ ⌘K, actions: **Add server**) → `FilterPills` → master/detail:
server list (`mx-auto max-w-3xl`) left, sticky detail card right
(~380px `border-line bg-surface`).

## Server list rows

`ListRow`-style: `IconTile` (tone by health) + name/transport + tool count &
health word + `Toggle` (enable). **No destructive action on the row** —
removal lives only in the detail card (with confirm dialog). Selected row gets
accent-tint treatment.

## Server detail card

- Header: name, transport badge, connected dot + tool count.
- Tools: per-tool rows with `Toggle` (`tool_filter` allow/deny), approval
  defaults.
- Credentials: type (mono, wraps `break-all` — never overflows), label only
  when it adds info beyond the type, date, trash. Values are never echoed —
  no `••••••••` masks either.
- OAuth: connect/reconnect flow surfaces as buttons + status.
- Footer: danger-outline **Remove server** (confirm dialog).

## Add server modal

`max-w-lg` modal (`rounded-xl border-line bg-surface shadow-xl`): transport
(stdio/http), name, command/URL, env credentials fields, tool filter.

## Notes

- `is_server_connected` drives the health dot; connect failures surface in
  the detail card, not toasts.
- Credential rows must wrap, not overflow the 380px card.
