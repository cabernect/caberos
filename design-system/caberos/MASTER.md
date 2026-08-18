# CaberOS Design System — Master File

> **Source of truth:** `frontend/src/index.css` defines the actual CSS variables.
> This document describes the design language as implemented. If the code and
> this document disagree, the code wins.

---

## Design language

**Style:** Warm light, conversation-first, Claude/Linear-inspired

**Keywords:** warm, off-white, olive accent, minimal chrome, conversational, functional, professional

**Inspiration:** Claude (warmth, typography), Linear (clean surfaces, density)

**Philosophy:** The UI stays out of the way. The conversation is the product.
Surfaces are warm and paper-like. The olive accent is used sparingly — for
primary actions, active states, and focus rings. Everything else is muted
grays and warm off-whites.

---

## Color palette

Light theme only (v0.1). Dark mode is a future consideration.

| Role | CSS Variable | Hex | Usage |
|------|-------------|-----|-------|
| Surface | `--surface` | `#F5F5F3` | Full viewport background, warm off-white |
| Sidebar | `--sidebar` | `#EFEFED` | Sidebar, secondary surfaces |
| Border | `--border` | `#E0DFDC` | Subtle borders, dividers, input borders |
| Ink (primary text) | `--ink` | `#111110` | Headings, primary text, dark buttons |
| Ink-2 (secondary) | `--ink-2` | `#6B6B68` | Secondary text, labels, muted UI |
| Ink-3 (tertiary) | `--ink-3` | `#9B9B97` | Tertiary text, placeholders, scrollbar |
| Accent | `--accent` | `#6A8216` | Primary actions, active states, focus rings, links |
| Accent bg | `--accent-bg` | `#F0F2E2` | Accent-tinted backgrounds (sidebar active, hover) |
| Tool bg | `--tool-bg` | `#F0EDE8` | Tool call blocks, code blocks, inline code |
| Thinking bg | `--thinking-bg` | `#FFFBF0` | Thinking/reasoning blocks (warm cream) |
| Thinking border | `--thinking-border` | `#FDE68A` | Thinking block left border (amber) |
| Success | `--success` | `#16A34A` | Approved syscalls, enabled agents, heartbeat ok |
| Danger | `--danger` | `#DC2626` | Denied syscalls, errors, destructive actions |
| Warning | `--warning` | `#D97706` | Pending approvals, warnings |
| White | `--white` | `#FFFFFF` | Cards, message bubbles, inputs |
| Brand | `--brand` | `#6A8216` | Logo, brand elements (same as accent in light mode) |
| Brand-2 | `--brand-2` | `#A8C04A` | Lifted olive (for future dark mode) |

### Color usage rules

- **Accent (`#6A8216`) is used sparingly.** Primary buttons, active nav items, focus rings, links in markdown, streaming cursor. Never for large fills.
- **Ink (`#111110`) is the "dark" color.** Dark buttons (Add Agent, Send) use ink, not accent. This keeps the accent special.
- **Surfaces are warm, not cold.** `#F5F5F3` has a slight warmth vs pure `#F5F5F5`. This is intentional.
- **Tool blocks use `--tool-bg`** (`#F0EDE8`) — a warm beige that distinguishes them from the surface without being loud.
- **Thinking blocks use `--thinking-bg`** (`#FFFBF0`) — a warm cream with an amber left border. Visually distinct from tool blocks.

---

## Typography

| Element | Font | Usage |
|---------|------|-------|
| Headings | Inter | Page titles, section headings, agent names |
| Body | Inter | All body text, messages, labels |
| Mono | JetBrains Mono | Shell output, code blocks, tool calls, timestamps |

**Google Fonts import:**
```css
@import url("https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&family=JetBrains+Mono:wght@400;500&display=swap");
```

**Font weights:** 400 (body), 500 (labels, medium), 600 (headings, semibold). No 700+ in the UI.

**Font sizes (as used in components):**

| Size | Usage |
|------|-------|
| 12px (`text-xs`) | Timestamps, metadata, tertiary text |
| 13px | Secondary labels, sidebar items |
| 14px (`text-sm`) | Body small, input text, labels |
| 16px (`text-base`) | Body, message text |
| 18px | Section headings, sidebar title |
| 20px (`text-xl`) | Page titles |
| 24px (`text-2xl`) | Agent name in conversation header |

---

## Spacing

CaberOS uses Tailwind's spacing scale (4px base). Common values:

| Token | Value | Usage |
|-------|-------|-------|
| `gap-1` | 4px | Icon-to-text, tight gaps |
| `gap-2` | 8px | Inline spacing, message padding |
| `p-3` | 12px | Card padding |
| `p-4` | 16px | Standard padding, section padding |
| `p-6` | 24px | Large section padding, conversation padding |
| `p-8` | 32px | Page-level padding |

---

## Border radius

| Token | Value | Usage |
|-------|-------|-------|
| `--radius-sm` | 2.25px | Small elements, inline code |
| `--radius-md` | 3px | Buttons, inputs |
| `--radius-lg` | 6px | Cards, tool blocks, message bubbles |
| `rounded-full` | 9999px | Status dots, avatars, spinners |

Base radius: `--radius: 0.375rem` (6px). All other radii are calculated from this.

---

## Layout

### App shell

```
┌─────────────────────────────────────────────────────┐
│  Sidebar (collapsible)  │  Main content             │
│  --sidebar: #EFEFED     │  --surface: #F5F5F3       │
│  240px / 56px collapsed │                           │
│                         │                           │
│  • Agents               │  (page content)           │
│  • Providers            │                           │
│  • MCP                  │                           │
│  • Channels             │                           │
│  • Observability        │                           │
│  • Skills               │                           │
│  • Scheduler            │                           │
│                         │                           │
└─────────────────────────┴───────────────────────────┘
```

- **Sidebar:** Fixed left, collapsible (240px → 56px). Background `--sidebar`. Border-right `--border`.
- **Main content:** Fills remaining width. Background `--surface`. Full height, overflow hidden (scroll within content areas).
- **No top bar** — navigation is entirely in the sidebar.

### Conversation layout

```
┌──────────────────────────────────────────────────────┐
│  Sidebar       │  Chat sidebar    │  Conversation    │
│  (nav)         │  (sessions)      │  (messages)      │
│                │  240px           │                  │
│                │                  │  ┌─────────────┐ │
│                │  + New session   │  │ Messages    │ │
│                │  Session 1       │  │ (scroll)    │ │
│                │  Session 2       │  │             │ │
│                │  Session 3       │  └─────────────┘ │
│                │                  │  ┌─────────────┐ │
│                │                  │  │ Input bar   │ │
│                │                  │  └─────────────┘ │
└────────────────┴──────────────────┴──────────────────┘
```

- **Chat sidebar:** Session list, new session button. Toggleable.
- **Conversation:** Scrollable message area + fixed input bar at bottom.
- **Input bar:** Multi-line text input, attachment button, send button, model selector, thinking toggle.

---

## Components

### Message bubbles

- **User:** Right-aligned, `--white` background, `--border` border, `--radius-lg` radius.
- **Assistant:** Left-aligned, no bubble background (transparent on `--surface`). Markdown rendered.
- **Timestamps:** 12px, `--ink-3`, below the message.

### Tool call blocks

- Background: `--tool-bg` (`#F0EDE8`)
- Border: 1px `--border`
- Radius: `--radius-lg` (6px)
- Header: capability name + status badge
- Status colors: pending (`--ink-3`), running (`--warning`), approved (`--success`), denied (`--danger`), complete (`--ink-3`)
- Body: collapsible arguments + result, monospace

### Thinking blocks

- Background: `--thinking-bg` (`#FFFBF0`, warm cream)
- Left border: 3px `--thinking-border` (`#FDE68A`, amber)
- Radius: `--radius-lg`
- Content: italic, `--ink-2`
- Collapsible, with duration badge

### Approval prompts

- Inline in the conversation flow (not a modal)
- Background: `--white`, border: 1px `--border`
- Approve button: `--success` background, `--white` text
- Reject button: `--danger` background, `--white` text
- "Remember" checkbox with scope selector

### Buttons

| Type | Background | Text | Border |
|------|-----------|------|--------|
| Primary (dark) | `--ink` | `--white` | `--ink` |
| Accent | `--accent` | `--white` | none |
| Secondary | `--white` | `--ink` | `--border` |
| Ghost | transparent | `--ink-2` | none |
| Danger | `--danger` | `--white` | none |

Primary buttons use `--ink` (dark), not `--accent`. The accent is reserved for focus rings, active states, and links.

### Cards (agent list, settings)

- Background: `--white`
- Border: 1px `--border`
- Radius: `--radius-lg` (6px)
- Padding: `p-4` (16px)
- Hover: border darkens slightly

### Status dots

- Enabled/active: `--success` (green)
- Disabled/inactive: `--ink-3` (gray)
- Pending: `--warning` (amber)
- Error: `--danger` (red)
- Size: 8px circle, `rounded-full`

---

## Animations

### Pulse (thinking dots, running tools)

```css
@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.4; }
}
/* 1.5s ease-in-out infinite */
```

### Bounce dots (typing indicator)

Three dots, 6px each, `--ink-3`, staggered 0.15s delays.

### Streaming cursor

Blinking 2px-wide bar, `--accent` color, at the end of streaming text.

### Reduced motion

All animations disabled via `@media (prefers-reduced-motion: reduce)`.

---

## Scrollbars

Thin, 4px wide. Track: transparent. Thumb: `--border`, hover: `--ink-3`.

---

## Markdown rendering

Assistant messages render full Markdown (via `react-markdown` + `remark-gfm`):

- **Code (inline):** `--tool-bg` background, 3px radius, JetBrains Mono
- **Code blocks:** `--tool-bg` background, 6px radius, horizontal scroll
- **Blockquotes:** 3px left border (`--border`), `--ink-2` text
- **Links:** `--accent` color, underline
- **Tables:** `--border` borders, `--sidebar` header background
- **Lists:** Standard disc/decimal markers, 1.5em left padding

---

## shadcn/ui mapping

CaberOS uses shadcn/ui components with CSS variables mapped to the design system:

| shadcn token | CaberOS token |
|---|---|
| `--background` | `--surface` |
| `--foreground` | `--ink` |
| `--card` | `--white` |
| `--primary` | `--accent` |
| `--secondary` | `--sidebar` |
| `--muted` | `--sidebar` |
| `--muted-foreground` | `--ink-2` |
| `--destructive` | `--danger` |
| `--border` | `--border` |
| `--input` | `--border` |
| `--ring` | `--accent` |
| `--radius` | `6px` |

---

## Icons

CaberOS uses [lucide-react](https://lucide.dev/) for all icons. Icon size is typically 16px or 20px, matching the surrounding text size.

---

## What's NOT in the design system (yet)

- **Dark mode** — `--brand-2` (`#A8C04A`) is defined for future dark mode but not wired up.
- **Mobile responsive** — the app is desktop-first. Mobile layouts are not yet designed.
- **Animations beyond pulse/bounce/blink** — no page transitions, no slide-in panels, no skeleton loaders.
