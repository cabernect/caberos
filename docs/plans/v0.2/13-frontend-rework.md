# Frontend Rework (W13)

**Status: In progress — branch `feat/v0.2.0-frontend` off `feat/v0.2.0`.**
Design source: `docs/plans/v0.2/fe_example/` — 28 annotated mockups (design
system sheet + per-page redesigns + dark mode + startup states + landing).
The mockups are the visual source of truth; this doc is the build spec.

## Outcome

One consistent frontend: every page shares the same anatomy, primitives, and
tokens; dark mode is a designed state; page components are small enough to
navigate; and the app gains a "Today" operator home as its landing page.

## Design tokens (from `Design system@1x.png`)

Light · dark pairs, applied via CSS custom properties in `index.css`:

| Token | Light | Dark | Role |
|---|---|---|---|
| `ground` | `#F7F6F2` | `#151511` | page background |
| `surface` | `#FFFFFF` | `#1E1E19` | cards, inputs, rows |
| `sunken` | `#F0EFE9` | `#26261F` | tags, inset blocks |
| `track` | `#E5E4E2` | `#2D2D25` | toggle off, bar tracks |
| `line` | `#E8E6DE` | `#2D2D25` | borders, dividers |
| `ink` | `#16150F` | `#F2F0E6` | text, primary button |
| `ink-muted` | `#6B6A60` | `#A5A396` | secondary text |
| `ink-faint` | `#6F6E64` | `#8F8D81` | timestamps, hints |
| `accent` | `#5B6B1F` | `#A8BD45` | links, active, focus, success bars |
| `accent-tint` | `#ECEFD9` | `#2A3B16` | selected, icon tiles |
| `warning` | `#A4560A` | `#E8A15C` | needs attention |
| `warning-tint` | `#F6E3C4` | `#33260F` | warning surfaces |
| `danger` | `#B3261E` | `#FF8F85` | failed, destructive |
| `danger-tint` | `#FBEDE7` | `#2E1A14` | error banners |
| `success` | `#3E8E4F` | `#5FBF74` | live dot only |

**Type:** Geist; Geist Mono for IDs/model names. Scale: `page` 30/36 600 ·
`section` 18/26 600 · `stat` 24/30 600 · `title` 16/24 600 · `body` 14/20 400 ·
`small` 13/18 400 · `caption` 12/16 400.
**Spacing:** space-1…8 = 4/8/12/16/20/24/28/40. **Radius:** sm 6, md 10,
lg 16, pill full. **Control height:** sm 34, md 40, lg 44.

## Rules (hard)

1. One primary button per view.
2. Status is a shape + a word + a colour — never colour alone
   (Running ● / Idle ◐ / Paused ○ / Needs setup ⚠ / Failed ⚠).
3. Cards are for things you open or edit. Lists use rows. No card inside a card.
4. Every page = header, then filter row, then content.
5. Destructive actions sit apart from edit actions and ask for confirmation.
6. An empty state says what to do next.
7. Sentence case. Sidebar group labels are the only all-caps text.

## Page anatomy

```
breadcrumb (section / page)          [⌘K command bar — global header]
Page title (30/36) + subtitle (body, ink-muted)
[actions — secondary + ONE primary]      [stat cards row, if the page has them]
filter pills + sort                          (container-responsive auto-fill grid)
content — cards / rows / detail drawers
```

## Shared primitives (new — `src/components/ui/`)

Built once, consumed by every page. Derived directly from the mockups:

| Primitive | From mockups |
|---|---|
| `StatCard` | label + stat + hint (Agents/Overview rows) |
| `FilterPills` | All 7 / Active 5 / Needs setup 1 / Disabled 1; Today/7d/30d; Settings tabs |
| `IconTile` | letter/glyph in accent-tint tile (avatars, warning, shield, success) |
| `StatusWord` | shape + word + color per status vocabulary |
| `CardGrid` | `repeat(auto-fill, minmax(N,1fr))` container-responsive |
| `WarningBanner` | danger-tint strip + icon + copy + action link |
| `EmptyState` | centered icon + text + "what to do next" action |
| `SectionCard` | bordered surface + optional action column (Settings sections) |
| `KeyValueRow` | label left · value right (egress card, health bar) |
| `ApprovalCard` | warning-tint card: icon tile + request + evidence + allow-once/always/deny |
| `Drawer` | right-side detail/preview panel w/ resize (exists: `useResizableWidth`) |
| `Modal` | centered dialog (schedule editor pattern) |
| `OnThisPage` | right-side scroll-spy nav for long settings pages |
| `CommandBar` | ⌘K palette — jump to page/agent/action (minimal v1) |
| `AskAgentBar` | input + agent picker chip + send → new session (Today + chat new) |

## Sidebar (redesigned — `DashboardSidebar.tsx`)

- Adds **Today** item at top of Workspace (home icon) → route `/`.
- Badge counts per item: `Agents a/b` (active/total), `MCPs c/b` (connected/total),
  `Skills n` (published), `Channels a/b` (active/total), `Knowledge Vault n` (docs).
- Footer card: `● Running locally — N MCP servers live · data stays on this machine`.
- Bottom row: Settings + notification bell. Collapse behavior preserved.
- Counts come from the `/api/home` aggregate payload (single fetch — no waterfalls).

## New surfaces

### Today (home) — `Redesign · Today (home)@1x.png`

Route `/` (replaces redirect to `/agents`; `/agents` stays).
- Header: `Workspace / Today` breadcrumb; title + "What your agents did, and what
  they're waiting on."; ⌘K bar in global header.
- `AskAgentBar`: input + agent chip dropdown + Send → create session + message →
  navigate to conversation.
- **Needs you** card — rows from unread notifications seeded, **live-verified at
  read** (approval still pending, agent still model-less, failed-run group still
  unresolved). Actions deep-link (`action_path`); Dismiss = `markRead`.
  Kinds: approval/browser-takeover, needs-model, failed-run groups, MCP/OAuth.
- **What happened** card — audit-derived rollups grouped by agent × day ×
  outcome ("Caber finished 3 runs — Oct 6 9:19–9:40 AM"), `Open Traces` link,
  footer line "Nothing is running right now." when idle.
- **What can leave this machine** — egress surface: providers connected, MCP
  servers, channel state; footer "Stays here: config, memory, credentials,
  workspace files, run history." Display-only, from `/api/home`.
- **Your agents** — rows with `StatusWord` + last-run; "See all N agents" → `/agents`.

**Backend: `GET /api/home`** — one aggregate payload:
```json
{ "counts": {"agents_running":0,"agents_total":7,"mcps_connected":2,"mcps_total":7,
             "skills_published":6,"channels_active":0,"channels_total":2,"vault_documents":8},
  "agents": [{"id":"caber","name":"Caber","initial":"C","status":"idle","last_run_at":"…"}],
  "needs_you": [{"kind":"approval","agent_id":"…","title":"…","detail":"…",
                 "action_path":"…","notification_id":123}],
  "happened": [{"agent_id":"caber","agent_name":"Caber","outcome":"completed",
                "count":3,"window_start":"…","window_end":"…"}],
  "egress": {"providers":["OpenAI","Google Gemini","OpenRouter"],
             "mcps":["Notion"],"channels":[{"name":"Telegram","state":"paused"}]}
}
```
Sidebar reads the same payload for badges. New file `api/home.py` + tests.

### ⌘K command palette

Minimal v1: ⌘K / click bar opens modal — fuzzy match over nav destinations
(Today, Agents, Scheduler, …), agents (→ open chat), and a few actions
(New agent, New chat, Open Traces). Decorative bar is always visible in header.

### Settings shell — `Redesign · Settings *`

Settings becomes a **page** (not just overlay): tab pills
(General/Providers/Models/Browser/Migration/About) + `OnThisPage` scroll-spy nav.
General: Operator card, **Appearance** (Light/Dark/System theme pickers),
Notifications (enable, quiet hours, per-event overrides), Search (engine select).
Existing overlay content migrates into the page; overlay may remain for
contextual edit flows — decide during implementation.

### Startup states — `Startup · {Starting,Taking longer,Couldn't start}`

Minimal full-page states for the desktop shell's gateway boot: spinner/brand,
"Taking longer…" escalation, failure + retry + logs path. (Tauri-side concern —
`frontend` splash before gateway ready.)

### Dark mode — designed

Token pairs are specified (table above). `theme.tsx` gains
light/dark/system with the Settings → Appearance picker; `index.css` remediation
rules are replaced by first-class token pairs. Playwright audit both themes.

## Page-by-page work

| Page | Mockup | Key changes |
|---|---|---|
| Today (new) | `Today (home)` | New route + `/api/home` + cards above |
| Agents | `Agents` | Stat cards, filter pills+sort, card anatomy (icon tile, model mono, StatusWord, session sparkbar, Open chat/Choose model/Enable) |
| Conversation | `Chat (new)`, `Chat flow 1–3` | Chat sidebar (New chat, search ⌘/, TODAY/7DAYS/OLDER groups), agent header strip (status · skills · MCPs · vault), model chip + panel toggle, empty state w/ suggested actions, composer toolbar (attach, Web, Think, effort low/med/high, ↵ send), approval card, process-step timeline |
| Overview | `Overview` | Period pills, system-health bar, warning banner, stat cards, runs-per-day bars, top-agents stacked bar, recent runs |
| Traces | `Traces (runs)`, `Trace detail` | List anatomy + detail inspector per mockups |
| Knowledge Vault | `Knowledge Vault` | Anatomy + cards per mockup |
| Skills | `Skills`, `Skill preview`, `Skill instructions` | Scope pills, cards, preview drawer, full-page instructions |
| Scheduler | `Scheduler` | Anatomy per mockup |
| MCPs | `MCP servers` | Rows/cards per mockup |
| Channels | `Channels` | Longest-divergent page — full pass |
| Settings | `Settings · General/Providers/Models/Browser/Migration/About` | Page shell + tabs + OnThisPage |
| Startup | `Startup · ×3` | Boot states (desktop) |
| Landing | `Landing page · animated` | Desktop/marketing landing — scope TBD |

Each page: apply tokens + primitives + anatomy, then page-specific mockup
details. Conversation also gets its long-overdue decomposition (data fetch,
SSE, composer, preview dock, timeline → separate modules).

## Implementation order

1. **Tokens + theme plumbing** — light/dark pairs in `index.css`,
   `theme.tsx` light/dark/system, prune `--white` drift.
2. **Primitives** — `components/ui/` set above (each with a test/story usage).
3. **Sidebar + Today + `/api/home`** — the visible center of the rework;
   primitives get real consumers immediately.
4. **Page sweep in mockup order** — Agents → Conversation (decompose) →
   Overview → Traces → Knowledge Vault → Skills → Scheduler → MCPs → Channels.
5. **Settings shell** — tabs + OnThisPage + Appearance picker.
6. **⌘K palette** — minimal v1.
7. **Startup states** + landing decision.
8. **Dark audit** — Playwright pass over every page in both themes.

Each step is its own commit/PR-sized slice; gates per slice: `npm run lint &&
npm run build`, vitest touched files, Playwright verify light (and dark once
tokens land).

## Verification

- Playwright screenshot pass over every page, light **and** dark, as the
  refactor gate (visual-regression snapshots optional).
- Honest empty/loading/error states everywhere — mockup states all exist in
  `fe_example` (e.g. "Nothing is running right now", "No billable usage",
  "no model set").
- No per-page copies of pills/search/drawer/grid remain; no stray `--white`;
  no page component over the agreed size budget (~500 lines target for the
  largest page after Conversation decomposition).

## Deferred from brainstorm (unchanged)

- Component-library adoption (shadcn/Radix) — decide deliberately, not by drift.
- Full design-language change — this is consolidation + the mockup language,
  not a rebrand beyond what `fe_example` specifies.
