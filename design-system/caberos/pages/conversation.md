# Page: Conversation

> **Route:** `/agents/:id/chat`
> **Overrides:** `design-system/caberos/MASTER.md`

## Layout

```
┌──────────────────────────────────────────────────────────────┐
│  Sidebar  │  Chat Sidebar  │  Conversation                   │
│  (nav)    │  (sessions)    │                                 │
│           │                │  ┌────────────────────────────┐ │
│  Agents   │  + New session │  │  Agent name  [model] [⚙]  │ │
│  Providers│  ───────────── │  ├────────────────────────────┤ │
│  MCP      │  Session 1  ←  │  │                            │ │
│  Channels │  Session 2     │  │  Messages (scrollable)     │ │
│  Observ…  │  Session 3     │  │                            │ │
│  Skills   │  Session 4     │  │  • User message            │ │
│  Scheduler│                │  │  • Assistant message       │ │
│           │                │  │    (markdown)              │ │
│           │                │  │  • Tool call block         │ │
│           │                │  │  • Thinking block          │ │
│           │                │  │  • Approval prompt         │ │
│           │                │  │                            │ │
│           │                │  ├────────────────────────────┤ │
│           │                │  │  Input bar                 │ │
│           │                │  │  [📎] [text...] [model][→]│ │
│           │                │  └────────────────────────────┘ │
└───────────┴────────────────┴──────────────────────────────────┘
```

### Three-panel layout

1. **Nav sidebar** (left, 240px / 56px collapsed) — same as all pages
2. **Chat sidebar** (240px) — session list for this agent, toggleable via panel button
3. **Conversation** (fills remaining) — header + messages + input

### Header

- Agent name (18px, font-semibold, `--ink`)
- Model selector (dropdown, shows current model)
- Thinking toggle (brain icon, effort slider)
- Settings gear → opens `SettingsOverlay`

### Message area

- Scrollable, auto-scrolls to bottom on new messages
- "Scroll to bottom" button appears when scrolled up
- Messages render based on role (see MASTER.md → Message bubbles)

### Stream items (during a run)

During an active run, the following stream items appear inline in the message area:

1. **Thinking block** — warm cream background, amber left border, italic text, collapsible with duration badge
2. **Tool call block** — warm beige background, capability name + status, collapsible args/result
3. **Text** — streaming text with blinking cursor (`--accent`, 2px bar)
4. **Approval prompt** — inline card with approve/reject buttons + remember checkbox
5. **Elicitation prompt** — inline card with question + text input or option buttons
6. **Sub-agent stream** — nested thinking + tools + text, visually indented

### Input bar

- Multi-line text input (auto-growing)
- Attachment button (paperclip icon) — supports images, files, URLs
- Model selector (compact dropdown)
- Thinking toggle (brain icon)
- Send button (arrow icon, `--ink` background)
- Disabled while a run is active; replaced by "Stop" button
- Context items (attachments) show as chips above the input

### Chat sidebar (sessions)

- "New session" button at top
- Session list: title, last activity timestamp, message count
- Active session highlighted with `--accent-bg` background
- Click → switches session
- Session menu → rename, delete, compact
