# Page Override: Agent List (Landing)

> **Overrides:** `design-system/caberos/MASTER.md`
> **Route:** `/`
> **Purpose:** The landing page. The operator sees their fleet of agents and clicks one to enter a conversation.

---

## Layout

```
┌──────────────────────────────────────────────────────────────┐
│  CaberOS                              [Add Agent]  [⚙]      │  ← top bar
├──────────────────────────────────────────────────────────────┤
│                                                              │
│  Your Agents                                                 │
│                                                              │
│  ┌────────────────────┐  ┌────────────────────┐             │
│  │  ◉ Personal        │  │  ◉ Research        │             │
│  │    Assistant       │  │    Agent           │             │
│  │                    │  │                    │             │
│  │    GPT-4o · $0.42  │  │    Claude · $1.20  │             │
│  │    today           │  │    today           │             │
│  │                    │  │                    │             │
│  │    ♢ heartbeat 30m │  │                    │             │
│  └────────────────────┘  └────────────────────┘             │
│                                                              │
│  ┌────────────────────┐                                     │
│  │  + New Agent       │                                     │
│  │                    │                                     │
│  └────────────────────┘                                     │
│                                                              │
└──────────────────────────────────────────────────────────────┘
```

### Grid

- **Card grid:** responsive — 1 column on mobile (375px), 2 on tablet (768px), 3 on desktop (1024px+), 4 on wide (1440px+)
- **Card size:** fixed min-width 280px, min-height 160px
- **Gap:** `--space-md` (16px) between cards

### Agent Card

- **Agent icon:** Lucide icon (Bot, Brain, Search, etc.), `--text-2xl` size, AI accent color
- **Agent name:** `--text-lg` weight 600
- **Meta line:** model name + today's spend, `--text-sm` secondary color
- **Heartbeat badge:** if heartbeat is enabled, show "♢ heartbeat {interval}" in heartbeat purple. The ♢ is a Lucide icon (Activity), not an emoji.
- **Hover:** card background transitions to `--color-surface-hover`, border transitions to AI accent
- **Click:** navigates to `/agents/:id/chat` (conversation view)
- **Disabled agent:** opacity 0.5, "disabled" label

### New Agent Card

- **Dashed border** in secondary color
- **Plus icon** (Lucide Plus) centered
- **"New Agent" text** below icon
- **Click:** opens create agent form (modal or new route)

### Top Bar

- **Logo/name:** "CaberOS" left, `--text-xl` weight 700
- **Add Agent button:** AI accent outline button
- **Settings icon:** ⚙ (Lucide Settings), navigates to system settings

---

## Overrides from Master

### Theme

Dark mode (same as master dark mode palette).

### Empty State (no agents yet)

```
┌──────────────────────────────────────────┐
│                                          │
│         [Bot icon]                       │
│                                          │
│         No agents yet.                   │
│         Create your first agent.         │
│                                          │
│         [Create Agent]                   │
│                                          │
└──────────────────────────────────────────┘
```

- Centered, `--text-2xl` for heading
- Single CTA button (AI accent)
- Lucide Bot icon, large

---

## Accessibility

- **Agent cards:** `role="button"`, `tabindex="0"`, Enter/Space to activate
- **Grid:** `role="list"`, cards are `role="listitem"`
- **Keyboard:** Tab moves between cards, Enter opens conversation
- **Screen reader:** each card announces "Agent {name}, model {model}, {spend} today, heartbeat {on/off}"
