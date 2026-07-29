# Page Override: Conversation View

> **Overrides:** `design-system/caberos/MASTER.md`
> **Route:** `/agents/:id/chat`
> **Purpose:** The primary interaction surface — full-screen conversation with an agent.

---

## Layout

The conversation view is **full-screen**. Not a widget. Not embedded in a dashboard. It takes over the viewport.

```
┌──────────────────────────────────────────────────────────────┐
│  [< Back]  Agent Name                    [⚙ Settings] [☰]   │  ← top bar (minimal)
├──────────────────────────────────────────────────────────────┤
│                                                              │
│  ┌─ User message (right aligned) ────────────────────┐      │
│  │  Check my latest emails                           │      │
│  └───────────────────────────────────────────────────┘      │
│                                                              │
│  ┌─ AI message (left, ambient, no bubble) ───────────┐      │
│  │  ┌─ thinking (collapsible, secondary text) ─┐     │      │
│  │  │  ▸ thinking · 2.3s                        │     │      │
│  │  └──────────────────────────────────────────┘     │      │
│  │                                                    │      │
│  │  I'll check your inbox now.                       │      │
│  │                                                    │      │
│  │  ┌─ tool call (collapsible) ─────────────────┐   │      │
│  │  │  ▸ email.read()  ✓ allowed                 │   │      │
│  │  └────────────────────────────────────────────┘   │      │
│  │                                                    │      │
│  │  ┌─ tool call (running) ─────────────────────┐   │      │
│  │  │  ⟳ shell.run("ls -la")  running in sandbox │   │      │
│  │  └────────────────────────────────────────────┘   │      │
│  │                                                    │      │
│  │  You have 3 new emails. The most important is...  │      │
│  │  1,240 tokens · $0.003                            │      │
│  └───────────────────────────────────────────────────┘      │
│                                                              │
│  ┌─ Heartbeat message (left, purple border) ─────────┐      │
│  │  ♢ heartbeat · 09:00                              │      │
│  │  Morning check-in: no urgent emails found.        │      │
│  └───────────────────────────────────────────────────┘      │
│                                                              │
│  ● ● ●  (typing indicator)                                  │
│                                                              │
├──────────────────────────────────────────────────────────────┤
│  [ textarea: Ask your agent...                    ] [Send]  │  ← sticky input
└──────────────────────────────────────────────────────────────┘
```

### Sidebar (collapsible, off by default)

When the operator clicks the settings icon (⚙) or menu (☰), a sidebar slides in from the right:

- **Agent Settings** — soul, persona, task, model, capabilities, limits, heartbeat config
- **Workspace** — file browser for the agent's workspace
- **Version History** — config versions, diff, rollback
- **Recent Runs** — quick link to observability filtered by this agent

The sidebar is an overlay, not a layout shift. The conversation stays in place.

---

## Overrides from Master

### Theme

**Always dark mode.** The conversation view does not support light mode in v0.1. Dark background reduces eye strain during long conversations and matches the "AI-native" aesthetic.

| Role | Hex | Usage |
|------|-----|-------|
| Background | `#0A0A0A` | Full viewport background |
| Surface | `#171717` | Tool call blocks, user message bubbles |
| Surface Hover | `#262626` | Hover states on tool calls, sidebar items |
| Border | `#262626` | Subtle borders on tool calls, input |
| Text | `#F8FAFC` | All text |
| Secondary Text | `#94A3B8` | Timestamps, metadata, collapsed tool call summaries, thinking block text |
| AI Accent | `#6366F1` | Focus rings, active states, send button |
| Heartbeat | `#8B5CF6` | Heartbeat message left border, heartbeat badge |
| Success | `#10B981` | Allowed syscalls, "✓" indicator |
| Warning | `#F59E0B` | Pending approvals, "⏳" indicator |
| Danger | `#EF4444` | Denied syscalls, errors, "✗" indicator |
| Running | `#6366F1` | Spinner for running tool calls (AI Accent, animated) |

### Message Layout

- **User messages:** right-aligned, surface background bubble, max-width 80%
- **AI messages:** left-aligned, no bubble (ambient text), max-width 80%
- **Heartbeat messages:** left-aligned, purple left border (3px), no bubble, smaller text, "♢ heartbeat · timestamp" header
- **System messages:** centered, secondary text, small (e.g. "Run recovered after restart")
- **Message gap:** `--space-md` (16px) between messages
- **Conversation padding:** `--space-lg` (24px) left/right, `--space-xl` (32px) top

### Streaming Behavior

- **Typing indicator:** 3-dot pulse animation, shown within 300ms of sending a message
- **Token streaming:** model tokens appear character-by-character as they arrive via SSE
- **Streaming cursor:** a thin blinking bar at the end of streaming text (not a block cursor)
- **Tool call appearance:** when the agent calls a tool, a collapsible block appears inline immediately (before the tool result arrives). Shows "pending" state, then transitions to "running" (spinner), then "complete" (✓) or "denied" (✗).
- **Thinking blocks:** when the model emits reasoning tokens, a collapsible "thinking" block appears above the response text. Streams live (auto-expanded), then auto-collapses when reasoning completes. Models without reasoning tokens → no block.
- **Per-turn cost:** after each model turn, a subtle inline badge shows tokens and cost (e.g. "1,240 tokens · $0.003"). Accumulates to the run total.
- **Auto-scroll:** conversation auto-scrolls to bottom as new content arrives. If the user scrolls up, auto-scroll pauses and a "↓ Jump to latest" button appears.

### Thinking Block

```
┌─────────────────────────────────────────┐
│  ▸ thinking · 2.3s                       │  ← collapsed (after streaming)
└─────────────────────────────────────────┘

┌─────────────────────────────────────────┐
│  ▾ thinking...                           │  ← expanded (during streaming)
│  The user wants to check emails.         │  ← secondary text, italic, mono
│  I should call email.read first,         │
│  then summarize the important ones...    │
└─────────────────────────────────────────┘
```

- **During streaming:** auto-expanded, reasoning tokens appear character-by-character in secondary text color (`#94A3B8`), JetBrains Mono, italic
- **After streaming:** auto-collapses to `▸ thinking · {duration}s`
- **Visually distinct from tool calls:** no surface background, just indented secondary text. Lighter weight.
- **Only appears when `thinking` SSE events are emitted.** Models without reasoning tokens → no block.
- **Click to re-expand** and read the full reasoning.

### Tool Call Block

```
┌─────────────────────────────────────────┐
│  ▸ shell.run("echo hello")  ✓ allowed   │  ← collapsed (default, complete)
└─────────────────────────────────────────┘

┌─────────────────────────────────────────┐
│  ⟳ shell.run("ls -la")  running...      │  ← running state (spinner)
└─────────────────────────────────────────┘

┌─────────────────────────────────────────┐
│  ⏳ shell.run("rm -rf /tmp/cache")       │  ← pending approval
│     waiting for approval...              │
└─────────────────────────────────────────┘

┌─────────────────────────────────────────┐
│  ▾ shell.run("echo hello")  ✓ allowed   │  ← expanded
│  ┌─────────────────────────────────┐    │
│  │  $ echo hello                   │    │  ← mono font, terminal style
│  │  hello                          │    │
│  └─────────────────────────────────┘    │
│  exit code: 0 · 120ms                   │
└─────────────────────────────────────────┘
```

- **Collapsed (default):** shows tool name + args (truncated) + status icon
- **Expanded:** shows full command, full output (scrollable if long), exit code, duration
- **States:**
  - `pending` — ⏳ (amber, Lucide Clock), "waiting for approval..." or "calling..."
  - `running` — ⟳ (spinner, Lucide Loader2 with `animate-spin`), "running in sandbox..." for shell.run, "executing..." for others. Block auto-expands during execution.
  - `complete` — ✓ (green, Lucide Check), output shown when expanded. Block auto-collapses.
  - `denied` — ✗ (red, Lucide X), "approval denied" label
- **Multiple tool calls in one turn** are shown in order, each as its own block with a unique id.
- **Icons are SVG** (Lucide), not emojis
- **Font:** JetBrains Mono for command and output
- **Max height:** expanded output is scrollable, max-height 400px

### Chat Input

- **Sticky bottom:** always visible, never scrolls out of view
- **Textarea:** auto-grows up to 200px, then scrolls internally
- **Send button:** AI accent color (#6366F1), disabled when empty or when agent is responding
- **Enter to send, Shift+Enter for newline**
- **Disabled state:** when agent is responding, input shows "Agent is working..." placeholder, send button disabled

### Top Bar (minimal)

- **Back button:** `<` icon + "Agents" text, navigates to agent list
- **Agent name:** center, `--text-lg` weight 600
- **Settings icon:** ⚙ (Lucide Settings), toggles sidebar
- **No tabs, no breadcrumbs, no nav clutter**

### Empty State

When a conversation has no messages yet:

```
┌──────────────────────────────────────────┐
│                                          │
│         [Agent avatar/icon]              │
│                                          │
│         Agent Name                       │
│         Ready when you are.              │
│                                          │
│         Try:                             │
│         "Check my emails"                │
│         "What's on my calendar today?"   │
│         "Run the deploy script"          │
│                                          │
└──────────────────────────────────────────┘
```

- Centered, `--text-2xl` for agent name
- Suggested prompts are clickable (fill the input, don't send)
- No heavy illustration — just the agent icon (Lucide) and text

---

## Accessibility

- **Keyboard navigation:** Tab to move between input, send button, settings, back. Enter to send. Escape to close sidebar.
- **Screen reader:** each message is an `article` with `role` and `aria-label` (e.g. "User message", "Agent message", "Heartbeat message at 09:00")
- **Tool call blocks:** `aria-expanded` on the toggle, `aria-live="polite"` on the result so screen readers announce tool results
- **Streaming text:** `aria-live="polite"` on the AI message container so streaming tokens are announced
- **Typing indicator:** `aria-label="Agent is typing"`, hidden from screen reader when not visible
- **Reduced motion:** typing indicator becomes static dots, streaming text appears instantly (no character-by-character), all transitions disabled
