# Page: Conversation

> **Route:** `/agents/:id/chat`
> **Overrides:** `design-system/caberos/MASTER.md`

## Layout

```
┌──────────────────────────────────────────────────────────┐
│ Sidebar  │  ChatSidebar   │  Conversation                 │
│ 240/48px │  ~240px        │                               │
│          │  [+ New chat]  │  ┌──────────────────────────┐ │
│          │  ────────────  │  │ header: agent / model    │ │
│          │  Today         │  ├──────────────────────────┤ │
│          │   session …    │  │                          │ │
│          │  Yesterday     │  │  messages (scroll)       │ │
│          │   session …    │  │   user bubble (right)    │ │
│          │  Previous 7d   │  │   assistant markdown     │ │
│          │  Older         │  │   tool / thinking /      │ │
│          │                │  │   approval / elicit /    │ │
│          │                │  │   sub-agent blocks       │ │
│          │                │  ├──────────────────────────┤ │
│          │                │  │ ChatInputBar             │ │
│          │                │  └──────────────────────────┘ │
└──────────┴────────────────┴───────────────────────────────┘
```

Three panels: nav sidebar → `ChatSidebar` (session list for this agent,
collapsible) → conversation column.

## ChatSidebar

- **New chat** button at top — `bg-ink text-surface` light /
  `dark:bg-accent dark:text-[var(--accent-foreground)]` dark (olive CTA).
- Sessions grouped by **local** day buckets: Today / Yesterday /
  Previous 7 days / Older (`groupSessionsByDate`).
- Row: title + relative last-activity + message count; active session gets
  `accent-tint`. Per-session menu → rename / delete / compact.
- `learning` flag on a session → "internal work" indicator while a
  close/learning pass runs.

## Conversation column

- **Header:** agent name + `ModelPicker` + thinking toggle + settings gear
  (`SettingsOverlay`).
- **Messages:** see MASTER → *Conversation stream anatomy*. User bubble is
  `bg-ink text-surface` / `dark:bg-[var(--accent-tint)] dark:text-ink`.
- **Stream items during a run:** thinking block, tool call block, streaming
  text + cursor, `ApprovalCard`, elicitation card, nested sub-agent stream —
  all inline, no modals.
- **Auto-scroll** to bottom; "scroll to bottom" pill when scrolled up.

## ChatInputBar

Auto-growing textarea + attachments (paperclip; images/files/URLs),
`ModelPicker`, thinking toggle, send/stop, context-token meter
(context / cached / max). Attachment chips sit above the input.

## Notes

- Messages poll + SSE during runs; the run-inspector opens `TraceInspector`.
- Day-bucket boundaries and timestamps render in operator-local time.
