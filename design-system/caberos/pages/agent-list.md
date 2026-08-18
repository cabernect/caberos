# Page: Agent List

> **Route:** `/agents`
> **Overrides:** `design-system/caberos/MASTER.md`

## Layout

```
┌──────────────────────────────────────────────────────┐
│  Sidebar       │  Your Agents                        │
│  (nav)         │                                     │
│                │  ┌──────────┐ ┌──────────┐ ┌──────┐│
│  Agents  ←    │  │ ◉ Caber  │ │ ◉ Agent  │ │  +   ││
│  Providers    │  │   $0.42  │ │  Builder │ │ New  ││
│  MCP          │  │   today  │ │   $0.00  │ │      ││
│  Channels     │  │   3 sess │ │   1 sess │ │      ││
│  Observability│  └──────────┘ └──────────┘ └──────┘│
│  Skills       │                                     │
│  Scheduler    │                                     │
│                │                                     │
└────────────────┴─────────────────────────────────────┘
```

### Grid

- **Tailwind:** `grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3`
- **Gap:** `gap-4` (16px)
- **Card min-height:** ~180px

### Agent card

- Background: `--white`
- Border: 1px `--border`
- Radius: `--radius-lg` (6px)
- Padding: `p-4`
- Hover: border darkens, cursor pointer
- Content:
  - Status dot (8px, `--success` if enabled, `--ink-3` if disabled)
  - Agent name (18px, font-semibold, `--ink`)
  - Spend today (13px, `--ink-2`)
  - Session count (13px, `--ink-3`)
  - Heartbeat badge if configured (13px, `--accent`)
- Click → navigates to `/agents/{id}/chat`
- Settings gear → opens `SettingsOverlay`

### New agent card

- Dashed border, `--border`
- Centered "+" icon and "New Agent" text
- Click → opens `CreateAgentModal`

### Empty state

- "No agents yet" message
- "Create your first agent" button
