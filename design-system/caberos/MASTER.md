# CaberOS Design System — Master File

> **Source of truth:** `frontend/src/index.css` defines the actual CSS variables
> (`@theme inline` maps them to Tailwind utilities); `frontend/src/components/ui/`
> holds the shared primitives. If code and this document disagree, code wins.
>
> **Line:** v0.2 "Agent Workbench" — the W13 token set + page anatomy.

---

## Design language

**Style:** Warm, conversation-first, Claude/Linear-inspired — now in both light
and dark themes.

**Keywords:** warm, paper-like surfaces (light) / olive-dark surfaces (dark),
olive accent, minimal chrome, inspectable, functional, professional

**Philosophy:** The UI stays out of the way. The conversation and the audit
record are the product. Surfaces are warm; the olive accent is used sparingly —
primary actions, active states, focus rings. Everything else is muted.

---

## Color palette

Canonical tokens (use these — see *Legacy aliases* below). Light values are on
`:root`; dark values on `:root[data-theme="dark"]`.

| Role | Token | Light | Dark | Usage |
|------|-------|-------|------|-------|
| Ground | `--ground` | `#f7f6f2` | `#151511` | Viewport/page background |
| Surface | `--surface` | `#ffffff` | `#1e1e19` | Cards, sections, menus, inputs |
| Sunken | `--sunken` | `#f0efe9` | `#26261f` | Recessed fills: tool blocks, hovers, icon tiles |
| Track | `--track` | `#e5e4e2` | `#2d2d25` | Segmented-control track, toggle off state |
| Line | `--line` | `#e8e6de` | `#2d2d25` | Borders, dividers |
| Ink | `--ink` | `#16150f` | `#f2f0e6` | Primary text, dark buttons, titles |
| Ink muted | `--ink-muted` | `#6b6a60` | `#a5a396` | Secondary text, sub-labels |
| Ink faint | `--ink-faint` | `#6f6e64` | `#8f8d81` | Tertiary text, placeholders, scrollbar |
| Accent | `--accent` | `#5b6b1f` | `#a8bd45` | Links, active states, focus, sparkline brand |
| Accent tint | `--accent-tint` | `#ecefd9` | `#2a3b16` | Accent-tinted fills (active nav, icon tiles, user bubble in dark) |
| Warning | `--warning` | `#a4560a` | `#e8a15c` | Pending/attention states, paused |
| Warning tint | `--warning-tint` | `#f6e3c4` | `#33260f` | Warning banners, thinking blocks |
| Danger | `--danger` | `#b3261e` | `#ff8f85` | Errors, destructive actions |
| Danger tint | `--danger-tint` | `#fbede7` | `#2e1a14` | Danger banners |
| Success | `--success` | `#3e8e4f` | `#5fbf74` | Running/healthy/approved states |

In dark mode only: `--accent-foreground: var(--ground)` — text/icons placed *on*
an accent fill use the dark ground, not white.

### Legacy aliases

Old v0.1 names still resolve to canonical tokens — unswept code keeps working,
**new code must use canonical names**:

| Alias | → Canonical |
|-------|-------------|
| `--sidebar` | `--ground` |
| `--border` | `--line` |
| `--ink-2` | `--ink-muted` |
| `--ink-3` | `--ink-faint` |
| `--accent-bg` | `--accent-tint` |
| `--hover`, `--tool-bg` | `--sunken` |
| `--thinking-bg` | `--warning-tint` |
| `--thinking-border` | `warning 45% on warning-tint` |
| `--white`, `--brand` | `--surface`, `--accent` |

### Color usage rules

- **Accent is sparing.** Links, active nav (`accent-tint` bg + accent text),
  focus rings, charts, toggles-on. Never large fills.
- **Primary buttons are ink, not accent** (`--primary: var(--ink)`). Exception
  in dark mode: a primary CTA may use `dark:bg-accent` +
  `dark:text-[var(--accent-foreground)]` when an ink fill would render as a
  bright slab (e.g. New chat).
- **Status = shape + word + color — never color alone** (`StatusWord`).
- **Surfaces are warm** — `#f7f6f2`/`#151511` both lean warm, not gray.
- **Inverted fills** (`bg-ink text-surface`, e.g. filter pills, user bubble in
  light mode) always pair with a `dark:` override — ink goes near-white in dark.

### Dark mode mechanics

- `caberos-theme` localStorage: `light | dark | system`
  (`lib/themeState.ts`, `ThemeProvider` in `lib/theme.tsx`).
- Applies `data-theme` attr + `.dark` class + `style.colorScheme` on `<html>`.
- `dark:` utilities work via `@custom-variant dark (&:is(.dark *))` in index.css.
- Temporary remediation (retires with the page sweep): dark mode re-points
  `.text-white → --ground`, `.bg-white → --surface`,
  `bg-[var(--accent)]` children → `--accent-foreground`, and
  `ring-offset` to `--ground` instead of white.

---

## Typography

| Face | Font | Usage |
|------|------|-------|
| Sans | **Geist** | Everything — headings, body, labels |
| Mono | **Geist Mono** | IDs, code, model names, timestamps, section labels, badges |

```css
@import url("https://fonts.googleapis.com/css2?family=Geist:wght@400;500;600&family=Geist+Mono:wght@400;500&display=swap");
```

**Weights:** 400 body, 500 medium/labels, 600 semibold/headings. No 700+.

**Sizes (as used):**

| Size | Usage |
|------|-------|
| 11px mono | Nav section labels, badges, micro-metadata |
| 12px | Captions, sublabels, metadata, hints |
| 13px | Secondary labels, sidebar items, list-row subs |
| 14px | Body text, inputs, row titles |
| 16px | Section card titles (`SectionCard`), agent names |
| 24px (`text-2xl`) | Stat card values |
| 30px | Page titles (`PageHeader`) |

Line-heights pair as `leading-4/18px/20px/5/6/9` — 12→16, 13→18, 14→20, 16→24,
24→30, 30→36.

---

## Spacing

Tailwind 4px scale. Conventions: `px-8` page gutter, `px-4 py-3` row/section
padding, `gap-4` grids, `gap-3` rows, `gap-2` inline. Content rails center with
`mx-auto max-w-*`: `max-w-6xl` (Today), `max-w-5xl` (Scheduler, Vault detail),
`max-w-3xl` (MCP list+settings bodies), `max-w-sm` (auth cards).

---

## Border radius

Spec scale (`@theme`): **sm 6 / md 10 / lg 16** / xl 20 / 2xl 24 / 3xl 28 / 4xl 32.
`--radius` base = 10px (md).

| Token | Value | Usage |
|-------|-------|-------|
| `rounded-md` | 10px | Buttons(legacy wrappers), icon tiles, banners, dropdowns |
| `rounded-lg` | 16px | Cards, agent cards, stat cards, message bubbles |
| `rounded-xl` | 20px | `Card` primitive, modals |
| `rounded-full` | — | Pills, toggles, status dots, segmented filters |

---

## Layout

### App shell

```
┌────────────────────────────────────────────────────────┐
│ DashboardSidebar │  PageHeader (sticky)                 │
│ 240px / 48px     │  breadcrumbs → 30px title → actions  │
│                  │  trailing: command bar               │
│                  ├────────────────────────────────────── │
│                  │  PageIntro (first-run guidance)      │
│                  │  StatCard row (if any)               │
│                  │  FilterPills row (if any)            │
│                  │  content (list rows / CardGrid)      │
└──────────────────┴──────────────────────────────────────┘
```

- **Sidebar:** `DashboardSidebar` — expanded 240px (`--sidebar` → ground),
  collapsed to a 48px icon strip (persisted). Sections: *Workspace* (Today,
  Agents, Scheduler), *Capabilities* (MCPs, Skills, Channels, Knowledge Vault),
  *Observability* (Overview, Traces). Footer: "Running locally" status card,
  NotificationCenter, Settings, Sign out. Below 768px the strip is permanent
  and the expanded nav opens as a fixed overlay + scrim.
- **PageHeader:** breadcrumbs (13px muted, chevron separators) → title
  (30/36 semibold) + optional subtitle (14px muted) → right-aligned `actions`;
  `trailing` on the breadcrumb line carries the `CommandBar` (⌘K).
- **FilterPills:** `pills` = rounded chips, active = `bg-ink text-surface`;
  `segmented` = connected `--track` control, active = surface chip + shadow.
- **Content rule:** lists are **rows** (`ListRow` in `divide-y divide-line`),
  not cards. Cards are for openable entities (CardGrid) and stats.

### Page index

| Route | Page | Spec |
|-------|------|------|
| `/` | Today | `pages/today.md` |
| `/agents` | Agents | `pages/agent-list.md` |
| `/agents/:id/chat` | Conversation | `pages/conversation.md` |
| `/scheduler` | Scheduler | `pages/scheduler.md` |
| `/mcps` | MCP servers | `pages/mcps.md` |
| `/skills` | Skills | `pages/skills.md` |
| `/channels` | Channels | `pages/channels.md` |
| `/vault` | Knowledge Vault | `pages/knowledge-vault.md` |
| `/observability` | Overview | `pages/observability.md` |
| `/traces` | Traces + run detail | `pages/traces.md` |
| `/notifications` | Notifications | `pages/notifications.md` |
| `/settings` | Settings | `pages/settings.md` |
| `/login`, onboarding | Auth + first-run | `pages/login-onboarding.md` |

---

## Components (`frontend/src/components/ui/`)

| Primitive | Purpose / anatomy |
|-----------|-------------------|
| `Button` | base-ui + cva. Variants: `default` (primary/ink), `outline`, `secondary`, `ghost`, `destructive`, `link`. Sizes: `xs` `sm` `default`(h-8) `lg` + `icon` `icon-xs` `icon-sm` `icon-lg`. Focus-visible ring `--ring`, press `translate-y-px`. |
| `ListRow` | `[leading] title / sub [trailing]`. Title 14px medium ink, sub 13px muted, `px-4 py-3 gap-3`. Clickable rows hover `bg-sunken`. Dividers via parent `divide-y divide-line`. |
| `IconTile` | Rounded-square icon holder. Sizes `sm` 28 / `md` 36 / `lg` 44 px. Tones: `sunken` `accent` `warning` `danger` `surface` (tint bg + tone fg). |
| `EmptyState` | Dashed-border box: tile icon + 14px semibold title + 13px muted guidance + optional action. **Rule: explain what to do next.** |
| `WarningBanner` | Inline banner, tones `warning`/`danger`/`info` (tint bg + tone icon/text). |
| `StatusWord` | Dot + word + tone: running(success, pulsing), idle(ink-faint), paused/needs_setup(warning), failed(danger), success. Never color alone. |
| `SectionCard` | `rounded-md border-line bg-surface`; header = 16px semibold + optional action over `border-b`; body holds ListRows. |
| `CardGrid` | `repeat(auto-fill, minmax(Npx,1fr))` grid for openable entity cards. |
| `StatCard` | 12px muted caption → 24/30 semibold value → 12px faint sublabel. |
| `KeyValueRow` | Label (13 muted, left) / value (14 ink, right, `mono` → Geist Mono). |
| `FilterPills` | See above; optional count in `ink-faint`. |
| `CommandBar` | Fake search field — opens CommandPalette (⌘K/Ctrl+K). |
| `Toggle` | Track `--track` off / `bg-accent` on, white thumb; `sm`/`md`. |
| `Select` | Styled dropdown (portal, edge-flip) — replaces native `<select>` for Chrome/WKWebView parity. |
| `Input` / `Textarea` | `border-input`, transparent bg, `focus-visible` ring `--ring`. |
| `ApprovalCard` | Warning/danger header + mono detail + Approve/Deny + footer slot. |
| `Card` | shadcn-style (`rounded-xl`, `ring-1 ring-foreground/10`) — CardHeader/Title/Description/Action/Content/Footer. |

Also: `PageHeader`, `Breadcrumb`s; `guidance/` primitives — `PageIntro`
(first-run explainer), `TourSpotlight`, `GuidanceHost`.

---

## Conversation stream anatomy

- **User bubble:** right-aligned, `bg-ink text-surface` (light) →
  `dark:bg-[var(--accent-tint)] dark:text-ink` (dark) — olive wash, not a
  white slab.
- **Assistant text:** left-aligned, transparent on ground, full markdown.
- **Thinking block:** `--thinking-bg` (warning-tint) + amber-ish left border,
  italic muted text, collapsible + duration badge.
- **Tool call block:** `--tool-bg` (sunken), capability name + status badge,
  collapsible mono args/result.
- **Approval prompt:** `ApprovalCard`, inline in the flow — never a modal.
- **Elicitation card:** question + input/options, inline.
- **Streaming cursor:** 2px `--accent` bar, blink.
- **Timestamps:** 10–12px `ink-faint`, mono.

---

## Animations

| Keyframe | Use |
|----------|-----|
| `pulse` (1.5s) | thinking dots, running status |
| `bounce` (1s, 3 staggered dots) | typing indicator |
| `blink` (1s) | streaming cursor |
| `screen-in` | boot → login → app fades |
| `logo-land` + `rise-in` | boot handoff / login card |
| `stage-fade`, `ob-step-in/out-fwd/back` | onboarding stepper, direction-aware |

All disabled under `prefers-reduced-motion`.

---

## Scrollbars

4px thin. Transparent track, `--border` thumb, `--ink-3` hover.

---

## Markdown rendering

`react-markdown` + `remark-gfm`, `.markdown-body` styles in index.css:
inline code `--tool-bg` + 3px radius Geist Mono; code blocks `--tool-bg` +
6px; blockquote 3px `--border` left + `ink-2`; links `--accent` underlined;
tables `--border` cells, `--sidebar` header; strong = 600.

---

## shadcn/ui mapping

| shadcn | CaberOS |
|--------|---------|
| `--background` | `--ground` |
| `--foreground` | `--ink` |
| `--card` | `--surface` |
| `--primary` | `--ink` (!) |
| `--secondary` | `--surface` |
| `--muted` | `--sunken` |
| `--muted-foreground` | `--ink-muted` |
| `--destructive` | `--danger` |
| `--border`, `--input` | `--line` |
| `--ring` | `--accent` |
| `--radius` | `10px` |
| `--chart-1..5` | accent, warning, success, danger, ink-faint |

---

## Icons

[lucide-react](https://lucide.dev/) — 14–20px typical, matching text size.
Mono font accompanies icon badges/labels.

---

## What's NOT in the design system (yet)

- **Mobile layouts** — desktop-first; <768px gets the icon-strip sidebar but
  page bodies aren't mobile-designed.
- **Density/compact mode**, **high-contrast theme** — not designed.
- **Legacy alias retirement** — the sweep is incomplete; unswept surfaces still
  reference `--ink-2`, `--tool-bg`, etc.
