# 08 — Channels

## Goal

Build the channel abstraction and the one v0.1 channel: dashboard chat. The channel port is proven by having a clean abstraction — adding a second channel (Zalo, in the appendix) is a configuration change, not an architectural one. The pipeline orchestration (D19's 13-step execution pipeline) has been extracted to [plan 07](07-pipeline.md); this plan covers only the channel abstraction and the dashboard chat adapter.

## Spec references

- **D20** — The Channel port, proven by two implementations
- **D19** — Execution pipeline (steps 1-3 receive, step 12 deliver)
- **Stories 12-14** — chat in dashboard, see syscalls inline, test sessions separate

## Dependencies

- [03-harness.md](03-harness.md) — the channel triggers a run via the harness
- [04-syscall-layer.md](04-syscall-layer.md) — the pipeline goes through the syscall layer
- [07-pipeline.md](07-pipeline.md) — the channel calls `pipeline.handle_inbound()` to trigger a run
- [12-control-plane.md](12-control-plane.md) — the control plane hosts the chat API routes

## Tasks

### 1. Define the channel interface

`backend/src/agentos/channels/base.py`:

```python
class Channel(ABC):
    type: str  # "dashboard_chat", "zalo_bot", ...

    async def receive(self, raw_payload: dict) -> InboundMessage:
        """Parse a raw platform payload into a normalized inbound message."""

    async def deliver(self, outbound: OutboundMessage) -> None:
        """Send a reply under this channel's output constraints."""

    @property
    def output_constraints(self) -> OutputConstraints:
        """Max length, supported formatting, typing indicator support."""

class InboundMessage(BaseModel):
    channel: str
    bot_id: str
    external_user_id: str
    external_user_name: str
    message_id: str
    text: str
    timestamp: datetime

class OutboundMessage(BaseModel):
    session_id: str
    text: str

class OutputConstraints(BaseModel):
    max_length: int | None
    supported_formatting: list[str]  # ["markdown", "plain"]
    supports_typing_indicator: bool
```

### 2. Implement dashboard chat channel

`backend/src/agentos/channels/dashboard.py`:

- **Receive:** messages come from the control plane API (WebSocket or SSE)
  - `POST /api/chat/{agent_id}/message` — operator sends a message
  - The message is normalized into `InboundMessage` with `channel="dashboard_chat"`
  - `bot_id` = agent_id, `external_user_id` = operator's contact id
  - `is_test` flag — test sessions are flagged and excluded from spend reports (story 14)
  - The channel calls `pipeline.handle_inbound(message)` — the pipeline (plan 07) handles the full 13-step execution

- **Deliver:** replies sent back via a per-conversation SSE stream (Decision 9)
  - `GET /api/chat/{agent_id}/stream` — one long-lived SSE connection per agent
  - The frontend opens the stream on entering the conversation view and closes it on leaving
  - Output constraints: no length limit, markdown supported, typing indicator via SSE events
  - SSE event types:
    - `typing` — the harness is running (show typing indicator)
    - `thinking` — reasoning tokens from the model (when the model emits them, e.g. Claude extended thinking). Streamed as they arrive. Collapsible "thinking" block in the UI. Not all models emit these — when absent, no event.
    - `token` — model output tokens, streamed character-by-character
    - `tool_call` — a tool call is starting. Payload: `{ id, capability, args, status: "pending" | "running" | "complete" | "denied", result }`. Emitted when the call starts (`pending`), when execution begins (`running`), and when the result returns (`complete`) or approval is denied (`denied`). Multiple tool calls in one turn are emitted in order, each with its own `id`.
    - `turn_complete` — one model turn finished. Payload: `{ turn_number, tokens_in, tokens_out, cost }`. Lets the UI show per-turn cost inline.
    - `message_complete` — the full run is done, final answer delivered. Payload: `{ run_id, total_cost, total_turns, status }`.
    - `heartbeat` — a heartbeat-triggered run is starting (message tagged as heartbeat in the UI)

- **Typing indicator:** sent as a `typing` SSE event while the harness is running

### 3. Create chat API routes

`backend/src/agentos/api/chat.py`:
- `POST /api/chat/{agent_id}/message` — send a message (body: `{ text, is_test }`)
- `GET /api/chat/{agent_id}/stream` — per-conversation SSE stream (stays open). Event types: `typing`, `thinking`, `token`, `tool_call`, `turn_complete`, `message_complete`, `heartbeat`
- `GET /api/chat/{agent_id}/history` — conversation history
- `GET /api/chat/{agent_id}/runs/{run_id}` — run detail with syscalls inline (story 13)

## Files to create

- `backend/src/agentos/channels/__init__.py`
- `backend/src/agentos/channels/base.py`
- `backend/src/agentos/channels/dashboard.py`
- `backend/src/agentos/api/chat.py`
- `backend/tests/test_channels.py`

## Verification

- Send a message via `POST /api/chat/{agent_id}/message` → Run created, reply received via SSE
- Typing indicator appears via SSE (`typing` event) while the agent is reasoning
- `token` events stream as the model generates output
- `tool_call` events appear when the agent invokes capabilities
- `message_complete` event fires when the run finishes
- `heartbeat` events keep the SSE connection alive
- SSE stream stays open per-conversation; frontend opens on entering conversation view, closes on leaving
- Test session (`is_test=true`) → flagged, excluded from spend reports
- Conversation history shows messages with timestamps
- Run detail shows syscalls inline (story 13)
- `uv run pytest tests/test_channels.py` passes
