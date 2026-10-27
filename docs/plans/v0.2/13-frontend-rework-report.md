# W13 Frontend Rework — Progress Report

Session sweep against `docs/plans/v0.2/fe_example/` mockups. Each page was
visually compared to its mockup in a live browser (light + dark where noted),
not just reskinned from memory.

## Global fix — the "so white" bug

Every page's root wrapper used `var(--surface)` (pure white `#FFFFFF`) instead
of `var(--ground)` (warm cream `#F7F6F2`). This also explains the earlier
composer mystery: the chat page rendered white while the composer band was
`--ground`, so the band read as a faint warm wrap around the card.

- Roots → `--ground`: `Conversation.tsx`, `Skills.tsx`, `Scheduler.tsx`,
  `Mcps.tsx`, `Channels.tsx`, `Notifications.tsx`, `ProvidersSettings.tsx`
- Inner `var(--sidebar)` fills → `var(--surface)` across the same files
  (`--sidebar` aliases `--ground`, so cards were rendering flat cream-on-cream)
- Verified live: composer band is now invisible against the chat surface

## Pages completed to mockup anatomy

| Page | Mockup | What landed |
|---|---|---|
| Agents | `Redesign · Agents` | Already matched (stat cards, counted pills, card grid, StatusWord) — verified |
| Traces list + detail | `Redesign · Traces (runs)` + `Trace detail` | Flat all-agents run table, 4 stat cards, agent share bar, cluster banner ("4 heartbeat runs failed on Oct 5"), segmented Timeline/Messages/Syscalls tabs, `?status=` deep-linking from Overview's "Review failed runs" |
| Knowledge Vault | `Redesign · Knowledge Vault` | All/Shared/Agents pills w/ counts, vault search, Shared-knowledge card (dropzone + doc rows w/ `● Indexed`), Agent scopes card (`Empty`+`Add` / `n docs`+`Open`), detail view on tokens |
| Skills | `Redesign · Skills` + `Skill preview` | `Capabilities / Skills` header, From URL / Import .zip / Create skill actions, counted segmented pills (per-view `count` fetch), search, cards: IconTile + mono name + enable/disable toggle (`setSkillStatus`), scope chips, `rev n`, resources, Used-by (last-used in tooltip), "Draft with an agent" banner → existing CreateDialog |
| Scheduler | `Redesign · Scheduler` | `Workspace / Scheduler` header, Schedules/Heartbeat segmented pills w/ counts, alerts + run errors → `WarningBanner`, `EmptyState`s |
| MCPs | `Redesign · MCP servers` | `Capabilities / MCPs`, My servers/Browse catalog segmented pills, client-side search, `Connected · n` / `Not connected · n` grouping, cards on surface tokens |
| Channels | `Redesign · Channels` | `Capabilities / Channels`, All/Connected/Paused pills w/ counts, search, `StatusWord` ("Live · polling · replies with X" / "Paused · … messages are not being read"), "Available to connect" rail (unconnected platforms, Connect preselects add form) |
| Notifications | `Redesign · Notifications` | `Observability / Notifications`, All/Needs action/Unread pills, Needs-your-action card (warning-tinted rows) + Earlier card, "Alerts right now" rail wired to real `getNotificationPrefs` (toasts/browser on-off, quiet-hours times, "Change in Settings"), Notification settings link |
| Settings | `Redesign · Settings (General)` | `Settings / {tab}` breadcrumb + segmented tab pills. Tab interiors unchanged |
| Conversation | `Chat (new)` + flow mockups | Floating translucent composer (`bg-surface/85` + blur), continuous gradient fade band, model picker bottom-right in toolbar, effort → compact dropdown, sidebar collapse moved into sidebar top-right, rail expand button, citation rows restyled (numbered tile + truncated URL + capped excerpt) |
| Overview | `Redesign · Overview` | Health strip, failed-runs banner → deep link, 5 stat cards, runs/cost-per-day bars, top-agents stacked bar, recent runs, Spend section kept |
| Today | `Redesign · Today (home)` | Done in earlier session (quick-prompt, Needs you, What happened, egress + agents rail) |

## Deliberately not implemented (no backend exists — faking would be dishonest)

- Knowledge Vault: `+ New scope` button; URL-paste ingest in dropzone
- MCPs: per-tool `Allow/Ask/Block` matrix (only binary `tool_filter` exists);
  right-rail selected-server inspector
- Channels: editable `Replies with` select (`updateChannel` has no `agent_id`),
  `Who can message it` allowlist (no field on `ChannelInfo`)
- Scheduler: week-grid calendar, schedule templates, "describe when" NL→cron
  parsing
- Settings: per-section interior anatomy, theme tile-picker (current select
  works), "On this page" anchor rail

## Deferred / next

- Skill drawer interior restyle (structure already matches the preview mockup)
- Command palette polish, startup states (`Startup · *` mockups unread),
  landing page decision
- Full dark-mode audit (pages spot-checked; token-level sweep not done)
- `Observability.tsx`/`Conversation.tsx`/`ProvidersSettings.tsx` still over the
  ~500-line decomposition target

## Gates

- `tsc --noEmit`: clean
- `npm run lint`: 0 errors (pre-existing warnings only)
- `npx vitest run`: 195/195 — two regressions found + fixed
  (`NotificationPrefs.defaults` guard; `Skills.test` updated: last-used moved
  to tooltip)
- `npm run build`: green (chunk-size warning only)
- Live verification: Playwright screenshots on Skills, Scheduler (both tabs),
  MCPs, Channels, Notifications, Settings, Chat — light + dark
