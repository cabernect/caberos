# Page: Agents

> **Route:** `/agents`
> **Overrides:** `design-system/caberos/MASTER.md`
> **Breadcrumbs:** Workspace › Agents

## Anatomy

PageHeader ("Agents" + subtitle + ⌘K command bar, actions: **Import** (outline)
+ **New agent** (primary)) → `PageIntro` → 4 `StatCard`s → `FilterPills`
(segmented) + Sort select → `CardGrid` of `AgentCard`s.

```
┌──────────────────────────────────────────────────────────┐
│ Agents                         [Import] [+ New agent]    │
│ ──────────────────────────────────────────────────────── │
│ PageIntro strip (first-run guidance)                     │
│ ┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐                      │
│ │Active│ │Runn..│ │Sess..│ │Needs │   ← 4 StatCards      │
│ └──────┘ └──────┘ └──────┘ └──────┘                      │
│ ( All | Active | Needs setup | Disabled )      Sort: ▾   │
│ ┌─────────┐ ┌─────────┐ ┌─────────┐                      │
│ │ ◉ Caber │ │ ◉ Scout │ │ ◉ …     │   ← AgentCard grid   │
│ │ gpt-5   │ │ No model│ │         │                      │
│ │ status  │ │ status  │ │         │                      │
│ │ spark   │ │         │ │         │                      │
│ └─────────┘ └─────────┘ └─────────┘                      │
└──────────────────────────────────────────────────────────┘
```

## StatCards

`grid grid-cols-2 lg:grid-cols-4`, `gap-3`: **Active agents** (of N),
**Running now** (names sublabel), **Sessions this week** (± vs last week),
**Needs attention** (warning-colored value when > 0).

## Filter row

- `FilterPills variant="segmented"` — All / Active / Needs setup / Disabled,
  each with count.
- Right side: `Sort:` label + `Select` (recent activity | name A–Z).

## AgentCard

- `rounded-[16px] border-line bg-surface p-5`; paused → `opacity-70`.
- Header: `IconTile`-style avatar — 44px `rounded-[12px] bg-accent-tint`
  first-letter (17px semibold accent) → name (16/24 semibold) + model
  (12px mono muted, "No model" if unset) → `StatusWord`.
- Body: persona/task line + 7-day session sparkline + session count.
- `…` menu → Settings (opens `SettingsOverlay`), Enable (paused agents).
- Click → `/agents/{id}/chat`.

## Empty state

`EmptyState` — "No agents yet" + "New agent" action; filtered-empty variant
says "No agents match this filter".

## Related surfaces

- `CreateAgentModal` — form | yaml modes; created → navigate to chat.
- `SettingsOverlay` — per-agent config (model, permissions, limits, heartbeat).
