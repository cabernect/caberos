# Page: Today

> **Route:** `/`
> **Overrides:** `design-system/caberos/MASTER.md`
> **Breadcrumbs:** Workspace › Today

Landing page — "What your agents did, and what they're waiting on."

## Anatomy

PageHeader (title + subtitle + ⌘K trailing) → **ask bar** → 2-col grid
(`lg:grid-cols-3`, content `mx-auto max-w-6xl`):

- **Left (`lg:col-span-2`):** *Needs you* `SectionCard`-style card →
  *What happened* card.
- **Right rail:** *What can leave this machine* → *Your agents*.

## Ask bar

Rounded `border-line bg-surface` form: auto-growing textarea ("Ask an agent to
do something…") + agent `Select` (defaults to latest-run agent) + primary
`Send`. Enter submits, Shift+Enter newline. Sends → navigates to
`/agents/{id}/chat?session=…`.

## Needs you

Unread, live-verified attention items (approvals, elicitations, failed runs,
browser takeovers). `ListRow`: `IconTile` (tone by kind — warning/danger/sunken)
+ title + `agent_name · detail` + trailing buttons — deep-link action
(`navigate(item.action_path)`) + outline **Dismiss**. Empty → `EmptyState`
"Nothing needs you".

## What happened

Terminal runs grouped agent × **local day** × outcome (7-day lookback).
`ListRow`: `IconTile` (`accent` completed / `danger` failed / `warning`
stopped) + "Caber finished 3 runs" + trailing `Oct 6, 9:19 AM–9:41 AM`
(local). Click → `/traces/{agent_id}`. Footer line when idle: "Nothing is
running right now." Header link → Traces.

## What can leave this machine

Egress honesty card — `ListRow`-style rows: prompts→providers (names), tool
requests→MCPs (names), channel messages (live count / "Paused"). Footer:
"**Stays here:** configuration, memory, credentials, workspace files and run
history."

## Your agents

`ListRow` per agent: first-letter `accent-tint` tile + name + status word
("Running" / "Idle · last run Oct 6" / warning "Needs a model"). Click → chat.
Footer: running count.
