# 03 — Harness (Agent Loop)

## Goal

Build the agent execution loop using Pydantic AI for tool-call parsing and LiteLLM for provider access. The harness assembles context, calls the model, iterates on tool calls (mediated by the syscall layer), enforces turn/cost limits, and compacts context when it grows too large.

## Spec references

- **D1** — The OS ships the harness
- **D2** — Pydantic AI is the harness implementation
- **D6** — LiteLLM via Pydantic AI adapter
- **D17** — Session context is compacted, with warning
- **D18** — Execution limits (timeout, result reduction, declared egress)
- **D19** — Execution pipeline (steps 7-11: assemble, reason, mediate, check, iterate)
- **D31** — Heartbeat: harness processes heartbeat-triggered runs the same way as user-triggered runs
- **I8** — Agents are configuration, no user-supplied code
- **Stories 5-7** — model selection, cost cap, turn cap

## Dependencies

- [02-agent-config.md](02-agent-config.md) — needs AgentConfig to know model, soul, persona, task, limits, capabilities
- [04-syscall-layer.md](04-syscall-layer.md) — the harness calls the syscall layer to mediate each tool call

## Tasks

### 1. Create LiteLLM → Pydantic AI adapter

`backend/src/agentos/harness/litellm_adapter.py`:
- Implement a Pydantic AI `Model` that wraps LiteLLM's `completion()` call
- **Load provider config at call time (Decision 17):** given `agent_config.model.provider_id`, load the `ProviderConfig`, decrypt its API key via the secret store (Fernet, plan 10), and pass `api_key`, `base_url`, `org_id`, and `extra_params` to LiteLLM's `completion()`. The provider is resolved per call, not from env vars.
- Map LiteLLM's response format to Pydantic AI's model response interface
- Extract token usage and cost from LiteLLM's response for accounting
- Handle LiteLLM exceptions (rate limits, timeouts, provider errors) → return as model errors
- Support all providers LiteLLM supports (OpenAI, Anthropic, Gemini, Ollama, etc.). Local providers (Ollama) use `base_url` with no key.

### 2. Build the harness

`backend/src/agentos/harness/loop.py`:

```python
class Harness:
    async def run(self, agent_config, session, message, syscall_handler,
                  trigger: str = "user_message",
                  event_emitter: Callable | None = None) -> RunResult:
        # 1. Assemble context (soul, persona, task, MEMORY.md, skills, KG facts, recent turns, tool schemas)
        # 2. Call model via Pydantic AI
        #    a. If model emits reasoning tokens → emit `thinking` SSE events as they arrive
        #    b. If model emits output tokens → emit `token` SSE events as they arrive
        # 3. If model returns tool calls → for each call:
        #    a. Emit `tool_call` SSE event with status=pending
        #    b. Pass to syscall_handler.mediate(call, session, agent_config)
        #    c. Emit `tool_call` SSE event with status=running (execution started)
        #    d. If approval required and pending → emit `tool_call` with status=pending (approval)
        #    e. On result → emit `tool_call` SSE event with status=complete (or denied)
        #    f. Add result to context
        # 4. Emit `turn_complete` SSE event with { turn_number, tokens_in, tokens_out, cost }
        # 5. Check limits (turns, cost) → if exceeded, apply fallback
        #    - For heartbeat runs, check against max_cost_per_heartbeat (D31)
        # 6. If model returns final answer → return it
        # 7. Iterate (go to 2) until final answer or limit hit
        # 8. Emit `message_complete` SSE event with { run_id, total_cost, total_turns, status }
        # The trigger field is recorded on the Run but does not change the pipeline.
        # event_emitter is the channel's SSE push callback (plan 08). None in tests.
```

Note (Decision 1): The harness depends on a `SyscallHandler` *interface* (protocol/ABC), not the concrete implementation. A minimal `SyscallHandler` protocol is defined in `backend/src/agentos/syscall/protocol.py` with just the `mediate()` signature. The real implementation comes in plan 04. For testing, a stub `SyscallHandler` that auto-approves all calls is used.

Key behaviors:
- **Turn counting:** each model call = 1 turn. Checked against `max_turns_per_run`.
- **Cost accumulation:** sum of all token costs across turns. Checked against `max_cost_per_run` (or `max_cost_per_heartbeat` for heartbeat-triggered runs, D31).
- **Sub-agent turns roll up:** when a sub-agent runs, its turns and cost count against the parent Run's limits (D12 rule 5).
- **Fallback on limit exceeded:** configured per-agent (`tell_user_and_stop` or `handoff_to_human`).
- **Error handling:** model errors produce a graceful apology to the user + visible error in dashboard (story 52).
- **Heartbeat runs (D31):** same pipeline, different trigger. The `trigger` field is recorded on the Run for audit/filtering. The harness does not branch on trigger — it just records it.
- **Reasoning tokens (thinking):** when the model emits reasoning tokens (e.g. Claude extended thinking, Gemini thought), the harness streams them via `thinking` SSE events as they arrive. Not all models emit these — when absent, no event is emitted and the UI shows no thinking block. Reasoning tokens are not stored in the message history (they're ephemeral, shown live, then discarded).
- **Per-turn cost emission:** after each model turn, the harness emits a `turn_complete` event with token counts and cost for that turn. This lets the UI show per-turn cost inline, not just the aggregate on the Run record after completion.
- **Tool call lifecycle:** each tool call emits a `tool_call` event with a progression of `status`: `pending` → `running` → `complete` (or `denied` if approval is rejected). Multiple tool calls in one turn are emitted in order, each with a unique `id`. The UI shows each as a collapsible block with its current state.

### 3. Implement context assembly

`backend/src/agentos/harness/context.py`:

Context assembly order (Decision 35):
1. **`soul`** — agent identity, from `AgentConfig.soul` (versioned config field), always loaded first
2. **`persona`** — agent personality/style, from `AgentConfig.persona` (versioned config field), always loaded second
3. **`task`** — task instructions, from `AgentConfig.task` (versioned config field), loaded third
4. **MEMORY.md** — agent's curated knowledge about the user, read from `~/agentos/agents/{agent_id}/MEMORY.md` (agent home dir, D34), always loaded
5. **Relevant skills** — trigger-loaded from `workspace/skills/*/SKILL.md`
6. **Knowledge graph facts** — queried via `memory.query_facts`
7. **Recent turns** — session working memory (last N messages, verbatim)
8. **Semantic recall** — fallback, only if needed (FTS5 or embeddings depending on config)

- Load rolling summary (if session has been compacted)
- Build tool schemas from the agent's granted capabilities (from the capability registry)
- Return as a Pydantic AI message history

### 4. Implement compaction

`backend/src/agentos/harness/compaction.py`:
- Check if assembled context exceeds `max_context_tokens`
- If yes: keep last N turns verbatim, summarize older turns into a rolling summary
- Use a cheap model call for summarization (or the same model)
- Record compaction event on the Run (timestamp, tokens before/after)
- **Warning before ceiling:** if context is at 80% of `max_context_tokens`, flag a warning on the Run
- Use Pydantic AI's compaction primitives where available (D2), configured via the OS

### 5. Implement result reduction

`backend/src/agentos/harness/result_reduction.py`:
- After each tool call returns, check if the result exceeds a token threshold
- If yes: truncate or summarize the result before it enters context
- This happens at production time (when the result is returned), not at storage time (D18)
- Use Pydantic AI's tool-output reduction where available

### 6. Wire into the execution pipeline

The harness is called at step 8-11 of D19's pipeline:
- Step 8: `harness.run()` is called with the agent config, session, and message
- Step 9: inside the loop, each tool call goes through `syscall_handler.mediate()`
- Step 10: limits checked after each turn
- Step 11: iterate until final answer

## Files to create

- `backend/src/agentos/harness/__init__.py`
- `backend/src/agentos/harness/litellm_adapter.py`
- `backend/src/agentos/harness/loop.py`
- `backend/src/agentos/harness/context.py`
- `backend/src/agentos/harness/compaction.py`
- `backend/src/agentos/harness/result_reduction.py`
- `backend/src/agentos/syscall/protocol.py`  # stubbed SyscallHandler interface (Decision 1)
- `backend/tests/test_harness.py`

## Verification

- Scripted model client returns a tool call → harness passes it to syscall handler → gets result → iterates → returns final answer
- Turn limit hit (max_turns=2, model keeps calling tools) → fallback applied, run stops
- Cost limit hit → fallback applied, run stops
- Context exceeds 80% of max → warning recorded on Run
- Context exceeds 100% → compaction fires, summary created, context shrinks
- Oversized tool result → truncated before entering context
- Model error → graceful apology returned, error visible in Run record
- Sub-agent call → sub-agent's turns and cost roll up to parent Run
- `uv run pytest tests/test_harness.py` passes (using scripted model double)

## Cross-references

- Plan 04 — Syscall layer (still plan 04)
- Plan 07 — Pipeline (new)
- Plan 11 — Memory (was plan 08)
