# 13 — Frontend

## Goal

Build the React frontend — conversation-first, not a management console with a chat widget. Two-level navigation: agent list (landing) → click an agent → full-screen conversation view. Management features (settings, MCP servers, observability, approvals, spend) are accessible from the conversation view, not the main screen.

The frontend is **one client of the API** (D33), not a special one. It has no privileged access, no back-channel, no direct database reads. Everything it does goes through the same HTTP + SSE API that a future CLI, TUI, or native app would use. The frontend is a reference client.

Built with React 19, Vite, shadcn/ui, Tailwind, TanStack Query + SSE. Design system: [`design-system/caberos/`](../../design-system/caberos/) — AI-Native UI style, dark-first, Inter + JetBrains Mono, minimal chrome.

## Spec references

- **D27** — Build order: vertical slice first, then the dashboard
- **D31** — Heartbeat: agents act autonomously; heartbeat messages appear in conversation
- **D32** — Conversation-first frontend
- **D33** — The Gateway is a headless daemon; the frontend is one client of many
- **Decision 8** — v0.1 is dark-only; light mode is a future consideration
- **Decision 9** — Per-conversation SSE: one long-lived connection per agent
- **Decision 35** — `soul`, `persona`, `task` are versioned config fields on `AgentConfig` (not workspace files); MEMORY.md is an agent-owned file in the agent home dir (D34)
- **Stories 1-70** — all operator-facing stories

## Design system

Before implementing any UI, read:
- [`design-system/caberos/MASTER.md`](../../design-system/caberos/MASTER.md) — global rules: colors, typography, spacing, components, anti-patterns
- [`design-system/caberos/pages/agent-list.md`](../../design-system/caberos/pages/agent-list.md) — landing page layout and overrides
- [`design-system/caberos/pages/conversation.md`](../../design-system/caberos/pages/conversation.md) — conversation view layout, streaming behavior, tool call blocks, accessibility

Key design decisions:
- **Dark-first.** The conversation view is always dark mode. Background `#0A0A0A`, surface `#171717`, text `#F8FAFC`.
- **v0.1 is dark-only.** Light mode is a future consideration. (Decision 8)
- **AI-Native UI style.** Minimal chrome, ambient AI messages (no bubble), typing indicators, streaming text, context cards for tool calls.
- **Inter for UI text, JetBrains Mono for shell output and tool calls.**
- **AI accent: `#6366F1`** (indigo). Heartbeat accent: `#8B5CF6` (purple). Success: `#10B981`. Danger: `#EF4444`.
- **Lucide icons** (matches shadcn/ui). No emojis as icons.
- **shadcn/ui components** with CSS variables for theming (per shadcn best practices).

## Dependencies

- [12-control-plane.md](12-control-plane.md) — needs the admin API to exist
- [07-pipeline.md](07-pipeline.md) — run execution pipeline (SSE events originate here)
- All backend plans — the frontend reads from every part of the system via the API

## Tasks

### 1. Set up the app shell with two-level navigation

`frontend/src/`:
- `App.tsx` — router with two levels:
  - Level 1: `/` — agent list (landing page, per `design-system/caberos/pages/agent-list.md`)
  - Level 2: `/agents/:id/chat` — full-screen conversation view (per `design-system/caberos/pages/conversation.md`)
  - Secondary routes: `/agents/:id/settings`, `/mcp-servers`, `/observability`, `/approvals`, `/spend`
- `lib/api.ts` — TanStack Query client, fetch wrapper with auth cookie. This is the **only** way the frontend talks to the backend (D33).
- `lib/sse.ts` — SSE client for streaming agent responses
- `lib/types.ts` — TypeScript types matching backend Pydantic models
- `index.css` — Tailwind + shadcn/ui theme variables from `design-system/caberos/MASTER.md`

### 2. Build the Agent List page (landing) (stories 1-11, 28-33)

`pages/AgentList.tsx` — per `design-system/caberos/pages/agent-list.md`:
- Full-screen dark background
- "CaberOS" wordmark top-left, Add Agent button, Settings icon top-right
- "Your Agents" heading
- Responsive card grid (1/2/3/4 columns at 375/768/1024/1440px)
- Each card: agent icon (Lucide), name, model + today's spend, heartbeat badge if enabled
- Click card → navigate to `/agents/:id/chat`
- "New Agent" card with dashed border
- Empty state: centered Bot icon + "No agents yet" + Create button

### 3. Build the Conversation View (primary interaction) (stories 12-14, 64-70)

`pages/Conversation.tsx` — per `design-system/caberos/pages/conversation.md`:

**Layout:**
- Full-screen dark conversation. Not a widget.
- Minimal top bar: Back button, agent name (center), Settings icon
- Main area: message list (scrollable)
- Sticky bottom: chat input
- Collapsible sidebar (right slide-in overlay): agent settings, workspace, version history, recent runs

**Message list:**
- User messages: right-aligned, surface background bubble, max-width 80%
- AI messages: left-aligned, ambient (no bubble), max-width 80%
- Heartbeat messages: left-aligned, purple left border (3px), "♢ heartbeat · timestamp" header, smaller text
- System messages: centered, secondary text, small
- Message gap: 16px. Conversation padding: 24px sides, 32px top.
- Auto-scroll to bottom. "↓ Jump to latest" button when scrolled up.

**Real-time streaming (SSE) — per-conversation (Decision 9):**
- One long-lived SSE connection per agent. The frontend opens the SSE connection on entering the conversation view and closes it on leaving.
- Events: `typing`, `thinking`, `token`, `tool_call`, `turn_complete`, `message_complete`, `heartbeat`
- Typing indicator (3-dot pulse) within 300ms of sending (on `typing` event)
- **Thinking blocks (on `thinking` events):** when the model emits reasoning tokens, they stream into a collapsible "thinking" block above the response. Collapsed by default after streaming completes; expanded during streaming so the user can watch the agent reason. Shown in secondary text color, JetBrains Mono. Not all models emit reasoning tokens — when absent, no thinking block appears.
- Model tokens stream character-by-character via `token` events
- Streaming cursor: thin blinking bar at end of streaming text
- **Tool calls appear inline immediately** as collapsible blocks (on `tool_call` events). Multiple tool calls in one turn are shown in order, each as its own block with a unique id. Each block transitions through states as events arrive:
  - `pending` — block appears with ⏳ icon and "waiting for approval..." if approval is required, or "calling..." if not
  - `running` — spinner icon, "running in sandbox..." for shell.run, or "executing..." for other tools
  - `complete` — ✓ icon (green), output shown when expanded
  - `denied` — ✗ icon (red), "approval denied" label
- **Per-turn cost (on `turn_complete` events):** after each model turn, show a subtle inline badge with tokens and cost for that turn (e.g. "1,240 tokens · $0.003"). Accumulates to the run total shown on `message_complete`.
- `message_complete` event finalizes the message with total cost and turns
- `heartbeat` event delivers heartbeat-tagged messages in real time

**Tool call block (collapsible):**
- Collapsed (default): `▸ shell.run("echo hello") ✓ allowed` — tool name + truncated args + status icon
- Expanded: full command, full output (scrollable, max 400px), exit code, duration
- Status icons: ✓ (green, complete), ✗ (red, denied/failed), ⏳ (amber, pending/running) — Lucide SVG icons, not emojis
- **Running state:** while a tool is executing, the block shows a spinner (Lucide `Loader2` with `animate-spin`) and a label ("running in sandbox..." for shell.run, "executing..." for others). The block auto-expands during execution, then auto-collapses on completion (user can re-expand).
- Font: JetBrains Mono for command and output

**Thinking block (collapsible):**
- Shown above the model's response text, inside the AI message
- During streaming: auto-expanded, reasoning tokens appear character-by-character in secondary text color (`#94A3B8`), JetBrains Mono, italic
- After streaming completes: auto-collapses to `▸ thinking · 2.3s` (duration shown)
- User can click to re-expand and read the full reasoning
- Visually distinct from tool calls: no surface background, just indented secondary text. Lighter weight.
- Only appears when `thinking` events are emitted. Models without reasoning tokens → no block.

**Chat input (sticky bottom):**
- Auto-growing textarea (up to 200px)
- Send button (AI accent #6366F1), disabled when empty or agent responding
- Enter to send, Shift+Enter for newline
- Disabled state: "Agent is working..." placeholder

**Empty state:**
- Centered agent icon, agent name, "Ready when you are."
- Suggested prompts (clickable, fill input but don't send)

**Heartbeat messages (D31):**
- Purple left border, "♢ heartbeat · timestamp" header
- Lucide Activity icon (not emoji)
- Visually distinct from user and AI messages

### 4. Build the Agent Settings sidebar (accessible from conversation) (stories 1-11, 28-33)

`components/agent/AgentSettings.tsx` — right slide-in overlay from conversation view:
- Form: name, soul (markdown editor), persona (markdown editor), task (markdown editor), model config, capabilities (checkbox list), limits, fallback
- **Identity fields (Decision 35):** `soul`, `persona`, and `task` are config fields on `AgentConfig`, edited as markdown text areas in the settings sidebar. Saving any of them creates a new `AgentVersion` (diff and rollback apply to identity changes, not just task changes). They are NOT workspace files.
- **MEMORY.md editing (Decision 34):** a separate markdown editor for MEMORY.md, read/written via `GET/PUT /api/agents/{id}/memory`. This is NOT a config field — editing it does not create a new version. It's the agent's living notebook (a file in the agent home dir, not the workspace, not the DB); the user can edit it directly, and the agent updates it via the `memory.update` syscall during runs.
- **Model config (Decision 17, 18):** a provider dropdown (populated from configured providers) + a model selector. When a provider is selected, call `GET /api/providers/{id}/models`. If `discovery == "dynamic"` → show a dropdown of discovered models (Ollama shows locally pulled models; OpenAI/Google show live lists) with a "type your own" override. If `discovery == "unavailable"` (e.g. Anthropic) → show a free-text input. Save validates the model with a 1-token completion.
- Capabilities list: grouped by kind (tools, sub-agents, memory, MCP tools), with scope and approval toggles per grant
- Heartbeat config: enable/disable, interval, task prompt, cost budget (D31)
- **Skills management:** list skills, create/upload a skill, delete a skill. Skills are workspace files (`workspace/skills/{agent_id}/`) shown in a list with create/upload and delete actions.
- Version history: list of versions, diff view between two versions, rollback button
- Workspace tab: file browser for the agent's workspace
- YAML export/import buttons
- Uses shadcn/ui Form + React Hook Form (per shadcn best practices)

### 5. Build the MCP Servers page (stories 15-18, plan 10)

`pages/McpServers.tsx` (was `Connectors.tsx`):
- List configured MCP servers: name, transport (stdio/http), tools discovered, connected status
- Add server button → form: name, transport, command/args (stdio) or URL/headers (http), env template, tool filter
- Connect button → starts OAuth flow (loopback redirect, for servers that need it) or test connection (for API-key servers)
- Server detail: list of discovered tools (name, description, egress, require_approval, subject_scoped), tool filter toggle
- Revoke button → confirms, revokes (deletes credentials, unregisters tools, disconnects)
- Per-server: list of agents using it (blast radius, story 17)
- Subject bindings: bind a Contact to an MCP server instance (whose mailbox/calendar)

### 6. Build the Observability page (stories 38-44)

`pages/Observability.tsx`:
- **Runs list:** recent runs, filterable by agent, contact, outcome, **trigger** (user_message/heartbeat)
- **Run detail:** messages with timestamps, syscalls with results, model calls, errors — all linked by run_id
- **Syscall log:** one table across all agents, filterable by agent, capability, contact, outcome
- **Denied syscalls:** highlighted with reason
- **Latency:** time-to-first-reply per run

### 7. Build the Approvals page (stories 45-46)

`pages/Approvals.tsx`:
- Queue of pending approvals: capability name, agent, context (the conversation that triggered it)
- Approve / Reject buttons
- After action: approval removed from queue, run resumes or continues with denial

### 8. Build the Spend page (story 33)

`pages/Spend.tsx`:
- Total spend: today, this week, this month
- Per-agent breakdown: bar chart or table
- Spend by capability: which capabilities cost the most
- Spend by trigger: user_message vs heartbeat
- Trend over time (simple line chart)

### 9. Build the Settings page

`pages/Settings.tsx`:
- System health: DB, sandbox, model status
- Operator settings: change password
- Memory browser: per-agent, per-contact memory entries, with clear button (stories 26-27)
- **Provider management (Decision 17):** list configured providers (name, type, base_url — never the key). Add provider (name, type, API key, base_url for local). Rotate key. Delete (blocked if an agent references it). Test connection (1-token completion). Embedding provider config for memory (D34) lives here too.

## Files to create

```
frontend/src/
├── App.tsx
├── index.css                          # Tailwind + shadcn theme vars from design-system
├── lib/
│   ├── api.ts                         # The ONLY way frontend talks to backend (D33)
│   ├── sse.ts                         # SSE client for streaming
│   └── types.ts
├── components/
│   ├── layout/
│   │   └── TopBar.tsx
│   ├── agents/
│   │   ├── AgentCard.tsx
│   │   ├── AgentForm.tsx
│   │   ├── AgentSettings.tsx          # Sidebar overlay
│   │   ├── CapabilityPicker.tsx
│   │   ├── HeartbeatConfig.tsx
│   │   ├── ModelSelector.tsx          # Provider dropdown + model discovery/free-text (Decision 17, 18)
│   │   ├── IdentityFields.tsx         # soul + persona + task editors (config fields, Decision 35)
│   │   ├── MemoryEditor.tsx           # MEMORY.md editor (agent home dir file, not versioned, Decision 34)
│   │   ├── SkillsManager.tsx          # Skills list/create/delete
│   │   ├── VersionHistory.tsx
│   │   └── VersionDiff.tsx
│   ├── providers/
│   │   └── ProviderManager.tsx        # Provider CRUD, key rotation, test (Decision 17)
│   ├── conversation/
│   │   ├── ConversationView.tsx       # Full-screen conversation
│   │   ├── MessageList.tsx
│   │   ├── MessageItem.tsx
│   │   ├── HeartbeatMessage.tsx
│   │   ├── ToolCallBlock.tsx          # Collapsible tool call (pending/running/complete/denied states)
│   │   ├── ThinkingBlock.tsx          # Collapsible reasoning tokens (streaming, then collapsed)
│   │   ├── TurnCostBadge.tsx          # Per-turn tokens + cost inline badge
│   │   ├── StreamingText.tsx          # Character-by-character streaming
│   │   ├── TypingIndicator.tsx        # 3-dot pulse
│   │   ├── ChatInput.tsx              # Sticky bottom input
│   │   └── EmptyState.tsx
│   └── ui/                            # shadcn/ui components
├── pages/
│   ├── AgentList.tsx                  # Landing page
│   ├── Conversation.tsx               # Full-screen conversation
│   ├── McpServers.tsx
│   ├── Observability.tsx
│   ├── RunDetail.tsx
│   ├── SyscallLog.tsx
│   ├── Approvals.tsx
│   ├── Spend.tsx
│   └── Settings.tsx
```

## Verification

- Login → redirected to Agent List (landing page, dark mode)
- Agent list shows seeded agent in a card grid, with heartbeat status badge
- Click agent card → full-screen conversation view (not a widget)
- Empty state shows agent icon + suggested prompts
- Send message → typing indicator (3-dot pulse) within 300ms → reply streams character-by-character
- SSE connection opens on entering conversation view, closes on leaving (one per agent)
- **Thinking block:** if the model emits reasoning tokens, a collapsible "thinking" block appears above the response, streams live, then auto-collapses. Models without reasoning tokens → no block.
- Tool calls appear inline as collapsible blocks with status icons (✓/✗/⏳)
- **Tool call lifecycle:** pending (⏳ waiting for approval or calling) → running (spinner, "running in sandbox...") → complete (✓) or denied (✗). Multiple tool calls in one turn shown in order.
- Expand tool call → see full command + output in JetBrains Mono
- **Per-turn cost badge:** after each turn, inline badge shows tokens + cost (e.g. "1,240 tokens · $0.003"). Run total shown on message completion.
- Heartbeat message appears in conversation with purple left border + "♢ heartbeat" header
- Back button → returns to agent list
- Settings icon → right sidebar slides in with agent settings, heartbeat config
- Edit soul/persona/task from settings sidebar → save → new AgentVersion created, diff visible (identity changes are versioned — Decision 35)
- Edit MEMORY.md from settings sidebar → save → file updated in agent home dir (no new version — it's a living document, Decision 34)
- Skills management: list skills, create/upload a skill, delete a skill
- Edit task → save → new version created, diff visible
- Enable heartbeat → set interval + task prompt → save → next heartbeat run appears in conversation
- MCP Servers page → add Outlook MCP server → OAuth redirect → returns connected, tools discovered
- Observability → run list → filter by trigger (user/heartbeat) → open run → see messages, syscalls, costs
- Approvals → pending approval → approve → run resumes
- Spend → today's total matches sum of runs, breakdown by trigger
- All API calls go through `lib/api.ts` — no direct fetch, no back-channel (D33)
- `prefers-reduced-motion` → typing indicator static, streaming instant
- Responsive at 375px, 768px, 1024px, 1440px
- `npm run build` succeeds with no TypeScript errors
