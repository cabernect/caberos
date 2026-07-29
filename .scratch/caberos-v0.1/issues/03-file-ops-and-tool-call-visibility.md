# 03 — File operations + tool call visibility

**What to build:** Ask the agent to read or write files in its workspace, and watch each tool call appear inline in the conversation as a collapsible block with its full lifecycle: pending → running → complete (or denied). The agent can also run shell commands (auto-approved in this ticket — approval flow comes in ticket 04). When the model emits reasoning tokens (e.g. Claude extended thinking), a collapsible "thinking" block streams live above the response. After each turn, a subtle badge shows tokens and cost. The user sees the agent thinking, calling tools, getting results, and producing output — like Claude Code or Cursor.

**Blocked by:** 02 — Dashboard chat with real model (needs the streaming chat UI and real model access).

**Status:** ready-for-agent

- [ ] File capabilities: `file.read(path)`, `file.write(path, content)`, `file.list(path)` — all scoped to the workspace root. Path escape (`../etc/passwd`, absolute paths) rejected by the syscall layer before the sandbox sees it.
- [ ] Shell capability: `shell.run(command)` — executes in the sandbox, auto-approved in this ticket (approval flow is ticket 04). Output captured and returned to the agent.
- [ ] Syscall layer (real implementation): subject injection (resolve contact from session), scope narrowing (workspace-bounded), authorise (check capability grant + scope), inject credentials (for connectors — stubbed here), execute (call the capability), record (write audit record). Replaces the stub from ticket 01.
- [ ] SSE events for tool calls: `tool_call` event with `{ id, capability, args, status, result }`. Status transitions: `pending` → `running` → `complete` (or `denied`). Multiple tool calls in one turn emitted in order, each with unique id.
- [ ] SSE event for thinking: `thinking` event streams reasoning tokens as they arrive (when the model emits them). Not all models emit these — when absent, no event. Reasoning tokens are ephemeral (streamed live, not stored in message history).
- [ ] SSE event for per-turn cost: `turn_complete` event with `{ turn_number, tokens_in, tokens_out, cost }`.
- [ ] Frontend — Tool call blocks: collapsible, inline in the AI message. States: pending (⏳ amber), running (⟳ spinner, "running in sandbox..." for shell.run), complete (✓ green), denied (✗ red). Auto-expand during execution, auto-collapse on completion. Expanded shows full command + output in JetBrains Mono, exit code, duration. Multiple tool calls shown in order.
- [ ] Frontend — Thinking blocks: collapsible, above the response text. Streams live (auto-expanded, secondary text color, italic, JetBrains Mono), then auto-collapses to `▸ thinking · {duration}s`. Click to re-expand. Only appears when thinking events are emitted.
- [ ] Frontend — Per-turn cost badge: inline after each turn, subtle. e.g. "1,240 tokens · $0.003". Accumulates to run total on `message_complete`.
- [ ] Result reduction: oversized tool results truncated or summarized before entering context (D18).
