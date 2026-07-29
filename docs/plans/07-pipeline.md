# 07 — Pipeline (Execution Orchestrator)

## Goal

Build the central orchestration that every inbound message follows — D19's 13-step execution pipeline. This is the heart of the system. Both channels (plan 08) and the heartbeat scheduler (plan 12) call `pipeline.handle_inbound()` to trigger a run. The pipeline is channel-agnostic — it contains no channel-specific vocabulary.

## Spec references

- **D19** — Execution pipeline (13 steps: receive, dedup, persist, resolve contact, resolve session, serialize, assemble, reason, mediate, check, iterate, deliver, record)
- **D31** — Heartbeat: triggers runs via the same pipeline with `trigger="heartbeat"`
- **D33** — The Gateway is a headless daemon; the pipeline is the core that all clients feed into

## Dependencies

- [01-database-layer.md](01-database-layer.md) — needs Run, Message, Contact, Session tables
- [03-harness.md](03-harness.md) — calls the harness for steps 7-11 (assemble, reason, mediate, check, iterate)
- [04-syscall-layer.md](04-syscall-layer.md) — the harness calls the syscall layer during step 9

## Tasks

### 1. Define the pipeline interface

`backend/src/agentos/pipeline.py`:

```python
class Pipeline:
    async def handle_inbound(
        self,
        message: InboundMessage,
        trigger: str = "user_message",  # "user_message" or "heartbeat"
        is_test: bool = False,
    ) -> Run:
        """Execute D19's 13-step pipeline for an inbound message."""
```

`InboundMessage` is defined in [08-channels.md](08-channels.md) — the channel produces it, the pipeline consumes it. For heartbeat triggers, the heartbeat scheduler (plan 12) constructs an `InboundMessage` with the heartbeat task prompt as `text` and `trigger="heartbeat"`.

### 2. Implement the 13-step pipeline

`backend/src/agentos/pipeline.py` — `handle_inbound()` executes:

1. **Receive** — the channel (or heartbeat scheduler) has already parsed the payload into `InboundMessage`. The pipeline takes it as input.
2. **Deduplicate** — check `message_id` against the Run table. If already seen → acknowledge and drop (no run created).
3. **Persist and acknowledge** — store the message in the DB, create a Run row with `status=pending`, `trigger=trigger`, `is_test=is_test`. Return the Run ID so the caller can acknowledge (HTTP 200 for channels; silent for heartbeat).
4. **Resolve Contact** — look up or create by `(channel, bot_id, external_user_id)`. For heartbeat, the contact is the operator's own contact.
5. **Resolve Session** — resume the live session or open one. Update `last_activity_at`.
6. **Serialize** — acquire the per-Contact lock (plan 04's `lock.py`). Concurrent arrivals queue.
7. **Assemble context** — delegate to the harness: load `soul`, `persona`, `task` (from `AgentConfig` — D35), MEMORY.md (from agent home dir — D34), skills, knowledge graph facts, recent turns.
8. **Reason** — delegate to the harness: call the model via Pydantic AI.
9. **Mediate** — delegate to the harness: each tool call goes through `syscall_handler.mediate()`.
10. **Check limits** — delegate to the harness: check turns, cost against `max_cost_per_run` (or `max_cost_per_heartbeat` for heartbeat runs).
11. **Iterate** — delegate to the harness: loop back to step 8 until final answer or limit hit.
12. **Deliver** — call `channel.deliver(outbound)` to send the reply. For dashboard chat, this emits SSE events. For heartbeat, this delivers to the dashboard channel (message appears in conversation, tagged as heartbeat).
13. **Record** — close the Run: set `status=completed`, record `tokens_in`, `tokens_out`, `cost`, `latency_ms`, `completed_at`. Release the per-Contact lock.

### 3. Implement deduplication

- Check `message_id` against the Run table
- If already seen → acknowledge and drop (no run created)
- Dashboard chat: message_id is a UUID generated client-side
- Heartbeat: message_id is `{agent_id}-heartbeat-{timestamp}` (deterministic, prevents duplicate heartbeat runs)

### 4. Implement session resolution

- Look up active session for `(contact_id, agent_id)`
- If exists and not idle-expired → resume
- If not → create new session
- Update `last_activity_at` on each message

### 5. Implement error handling

- **Model errors:** graceful apology to the user + visible error in Run record (story 52). For heartbeat runs: silent failure, recorded in audit log (Decision 14).
- **Capability timeouts:** error recorded, run continues with fallback.
- **Pipeline exceptions:** Run marked `failed` with error message, lock released, user notified (for user-triggered runs) or audit logged (for heartbeat runs).

### 6. Implement the smoke test script

`scripts/smoke.py` — a development tool for testing the pipeline end-to-end (not a product CLI; the `caber` CLI/TUI is v0.2, D38):
```bash
python scripts/smoke.py <agent_id> "Check my emails"
```
- Sends a message via `POST /api/chat/{agent_id}/message`
- Streams the response via SSE (`GET /api/chat/{agent_id}/stream`)
- Prints tool calls and final answer to stdout
- This is the vertical slice verification tool — no frontend needed to prove the backend works

## Files to create

- `backend/src/agentos/pipeline.py`
- `scripts/smoke.py`
- `backend/tests/test_pipeline.py`

## Verification

- `scripts/smoke.py <agent_id> "echo hello"` → message sent → agent reasons → calls `shell.run` in sandbox → prints answer to stdout
- Send the same message_id twice → second is dropped (deduplication)
- Heartbeat trigger → `handle_inbound(message, trigger="heartbeat")` → run created with `trigger=heartbeat` → reply delivered to dashboard channel
- Two concurrent messages from same contact → second queues behind first (per-Contact lock)
- Model error during user run → graceful apology returned, Run marked failed
- Model error during heartbeat run → silent failure, audit record written
- Pipeline contains no channel-specific vocabulary — only `InboundMessage` and `channel.deliver()`
- `uv run pytest tests/test_pipeline.py` passes
