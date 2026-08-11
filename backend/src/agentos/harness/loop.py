"""Harness — the agent execution loop (D2, D19 steps 7-11).

Assembles context, calls the model, iterates on tool calls (mediated by
the syscall layer), enforces turn/cost limits, and emits SSE events.
"""

import asyncio
import json
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from ..config_schema import AgentConfig
from ..syscall.protocol import SyscallHandler, SyscallResult, ToolCall
from .context import assemble_system_prompt, assemble_tool_schemas, build_message_history
from .guardrails import apply_guardrails
from .scripted_model import ScriptedModel, ScriptedResponse


@dataclass
class RunResult:
    """Result of a harness run."""

    final_answer: str = ""
    total_turns: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    total_cost: float = 0.0
    tool_calls_made: list[dict[str, Any]] = field(default_factory=list)
    status: str = "completed"  # completed, failed, limit_exceeded
    error: str | None = None
    guardrail_warnings: list[str] = field(default_factory=list)
    guardrail_redactions: list[str] = field(default_factory=list)
    # Compaction metadata (for context bar)
    context_tokens: int = 0  # tokens actually sent to the model
    max_context_tokens: int = 0  # model's context window
    compacted: bool = False  # whether compaction occurred this run
    context_breakdown: dict[str, int] = field(default_factory=dict)  # per-section token counts


# SSE event emitter type: async callable that takes (event_type: str, payload: dict)
EventEmitter = Callable[[str, dict[str, Any]], Any] | None


class Harness:
    """The agent execution loop."""

    def __init__(self, model: ScriptedModel | Any) -> None:
        """Initialize with a model (ScriptedModel for tests, or a real adapter later)."""
        self.model = model

    async def run(
        self,
        agent_config: AgentConfig,
        session: Any,
        message: str,
        syscall_handler: SyscallHandler,
        run_id: str,
        recent_messages: list[Any] | None = None,
        trigger: str = "user_message",
        event_emitter: EventEmitter = None,
        attachments: list[Any] | None = None,
        skill: str | None = None,
    ) -> RunResult:
        """Execute the agent loop (D19 steps 7-11).

        7. Assemble context
        8. Reason (call model)
        9. Mediate (tool calls through syscall layer)
        10. Check limits
        11. Iterate until final answer or limit hit
        """
        # Step 7: Assemble context
        # Load KG facts for this contact (D34 — subject-scoped, D10)
        kg_facts: list[dict] = []
        recall_snippets: list[dict] = []
        past_sessions: list[dict] = []
        if hasattr(syscall_handler, "db") and hasattr(session, "contact_id"):
            from ..memory.triples import query_facts

            try:
                kg_facts = await query_facts(
                    syscall_handler.db,
                    contact_id=session.contact_id,
                    agent_id=agent_config.id,
                )
            except Exception:
                pass  # No facts yet, or contact not resolved — continue without

            # Semantic recall fallback (D34) — fetch relevant snippets from past
            # conversations. Bounded: top 3 results, only if there's a real query.
            if message and len(message.strip()) > 3:
                from ..memory.recall import recall_snippets as _recall

                try:
                    recall_snippets = await _recall(
                        syscall_handler.db,
                        contact_id=session.contact_id,
                        agent_id=agent_config.id,
                        query=message,
                        limit=3,
                    )
                except Exception:
                    pass  # No snippets yet, or FTS not ready — continue without

                # Episodic recall (D34) — search past session summaries for
                # topical context. Auto-injected into the system prompt so
                # the agent knows "what we did before" without searching.
                from ..memory.episodic import search_session_summaries

                try:
                    past_sessions = await search_session_summaries(
                        syscall_handler.db,
                        agent_id=agent_config.id,
                        contact_id=session.contact_id,
                        query=message,
                        limit=3,
                    )
                except Exception:
                    past_sessions = []

        # Check if the model supports vision (for system prompt awareness)
        supports_vision = None
        if agent_config.model and agent_config.model.name:
            from .litellm_adapter import _check_vision
            supports_vision = _check_vision(agent_config.model.name)

        system_prompt = assemble_system_prompt(
            agent_config, message, kg_facts=kg_facts, recall_snippets=recall_snippets,
            forced_skill=skill, past_sessions=past_sessions, supports_vision=supports_vision,
        )
        tool_schemas = assemble_tool_schemas(agent_config)
        history = build_message_history(system_prompt, recent_messages or [], message, attachments)

        result = RunResult()

        # --- Context compaction (head/middle/tail) ---
        # Runs before the first LLM call. If auto-compaction is on and the
        # context exceeds the threshold, older messages are summarized.
        # The system prompt (history[0]) is always protected.
        from .compaction import compact_context, count_tokens, count_text_tokens, count_tool_tokens, get_model_max_tokens

        compaction_summary = getattr(session, "conversation_summary", None)

        # Get model info for token counting + summary LLM call
        model_str = "gpt-4o"  # fallback
        api_key = None
        base_url = None
        if hasattr(self.model, "get_model_info"):
            try:
                info = await self.model.get_model_info(agent_config.model)
                model_str = info["model_str"]
                api_key = info["api_key"]
                base_url = info["base_url"]
            except Exception:
                pass

        if agent_config.compaction.auto_compaction and len(history) > 1:
            # Compact the message portion (exclude system prompt — always kept)
            system_msgs = [history[0]] if history and history[0].get("role") == "system" else []
            conversation_msgs = history[len(system_msgs):]

            compaction_result = await compact_context(
                messages=conversation_msgs,
                agent_config=agent_config,
                model_str=model_str,
                previous_summary=compaction_summary,
                api_key=api_key,
                base_url=base_url,
            )

            history = system_msgs + compaction_result.messages
            result.max_context_tokens = get_model_max_tokens(
                model_str, agent_config.limits.max_context_tokens,
            )
            result.compacted = compaction_result.compacted

            # Per-section breakdown for the context tooltip
            result.context_breakdown = {
                "system_prompt": count_text_tokens(system_prompt, model_str),
                "conversation": count_tokens(compaction_result.messages, model_str),
                "tools": count_tool_tokens(tool_schemas, model_str),
            }
            result.context_tokens = sum(result.context_breakdown.values())

            # Persist the updated summary to the session
            if compaction_result.compacted and compaction_result.summary != compaction_summary:
                if hasattr(syscall_handler, "db") and hasattr(session, "id"):
                    from sqlalchemy import update as sa_update
                    from ..models.session import Session as SessionModel

                    await syscall_handler.db.execute(
                        sa_update(SessionModel)
                        .where(SessionModel.id == session.id)
                        .values(conversation_summary=compaction_result.summary)
                    )
                    await syscall_handler.db.flush()
                    session.conversation_summary = compaction_result.summary
        else:
            # No compaction — still report token count for the context bar
            result.max_context_tokens = get_model_max_tokens(
                model_str, agent_config.limits.max_context_tokens,
            )

            # Per-section breakdown for the context tooltip
            system_msgs = [history[0]] if history and history[0].get("role") == "system" else []
            conversation_msgs = history[len(system_msgs):]
            result.context_breakdown = {
                "system_prompt": count_tokens(system_msgs, model_str),
                "conversation": count_tokens(conversation_msgs, model_str),
                "tools": count_tool_tokens(tool_schemas, model_str),
            }
            # Total = sum of all sections (litellm's token_counter on full history
            # can be inconsistent, so we sum the breakdown for accuracy)
            result.context_tokens = sum(result.context_breakdown.values())

        # Inject spawn context into the syscall handler so run_subagent
        # can access the harness, session, run_id, and event_emitter.
        if hasattr(syscall_handler, "_spawn_context"):
            syscall_handler._spawn_context = {
                "harness": self,
                "session": session,
                "run_id": run_id,
                "event_emitter": event_emitter,
                "syscall_handler": syscall_handler,
            }

        # Emit typing event
        if event_emitter:
            await self._emit(event_emitter, "typing", {})

        max_turns = agent_config.limits.max_turns_per_run
        max_cost = (
            agent_config.limits.max_cost_per_run
            if trigger == "user_message"
            else agent_config.heartbeat.max_cost_per_heartbeat
        )
        consecutive_tool_failures = 0
        max_consecutive_failures = 5

        # Steps 8-11: the loop
        while result.total_turns < max_turns:
            result.total_turns += 1

            # Step 8: Call model
            # Use streaming if the adapter supports it (LiteLLMAdapter);
            # fall back to non-streaming for ScriptedModel
            try:
                if hasattr(self.model, "complete_stream"):
                    response = await self._call_streaming(
                        agent_config, history, tool_schemas, event_emitter
                    )
                else:
                    response: ScriptedResponse = await self.model.complete(
                        agent_model=agent_config.model,
                        messages=history,
                        tools=tool_schemas,
                    )
                    # Emit thinking if present (non-streaming path)
                    if response.thinking and event_emitter:
                        await self._emit(event_emitter, "thinking", {"content": response.thinking})
            except Exception as e:
                import logging as _log
                _log.getLogger("agentos.harness.loop").exception(
                    "Model call failed: model=%s provider=%s",
                    agent_config.model.name if agent_config.model else "?",
                    agent_config.model.provider_id if agent_config.model else "?",
                )
                result.status = "failed"
                result.error = str(e)
                # Show the actual error to the user instead of a generic message
                error_msg = str(e)
                if "429" in error_msg or "RateLimit" in error_msg or "rate" in error_msg.lower():
                    result.final_answer = (
                        "The model is rate-limited right now. Please try again in a moment, "
                        "or select a different model."
                    )
                elif isinstance(e, TimeoutError):
                    result.final_answer = (
                        "I couldn't complete that request because the model connection "
                        "timed out. Please try again."
                    )
                elif "401" in error_msg or "Authentication" in error_msg or "auth" in error_msg.lower():
                    result.final_answer = (
                        "Authentication failed — check that the provider API key is valid."
                    )
                elif "tool use" in error_msg.lower() or "tool_use" in error_msg.lower() or "function" in error_msg.lower() and "not" in error_msg.lower():
                    result.final_answer = (
                        "This model doesn't support tool use (function calling). "
                        "Please select a model that supports tools, or use a different provider."
                    )
                else:
                    # Include the actual error so the user can diagnose the issue
                    short_err = error_msg[:200] if len(error_msg) > 200 else error_msg
                    result.final_answer = (
                        f"I couldn't complete that request. Error: {short_err}"
                    )
                if event_emitter:
                    await self._emit(
                        event_emitter,
                        "message_complete",
                        {
                            "run_id": run_id,
                            "total_cost": result.total_cost,
                            "total_turns": result.total_turns,
                            "status": "failed",
                        },
                    )
                return result

            # Accumulate tokens/cost
            result.tokens_in += response.tokens_in
            result.tokens_out += response.tokens_out
            result.total_cost += response.cost

            # Step 9: Process tool calls
            if response.tool_calls:
                # Add the assistant message with tool_calls to history FIRST
                # (must precede the tool result messages for OpenAI API compliance)
                history.append(
                    {
                        "role": "assistant",
                        "content": response.content or "",
                        "tool_calls": [
                            {
                                "id": tc.get("id", str(uuid.uuid4())),
                                "type": "function",
                                "function": {
                                    "name": tc["name"],
                                    "arguments": json.dumps(tc.get("args", {})),
                                },
                            }
                            for tc in response.tool_calls
                        ],
                    }
                )

                # Build ToolCall objects
                calls = [
                    ToolCall(
                        id=tc.get("id", str(uuid.uuid4())),
                        name=tc["name"],
                        args=tc.get("args", {}),
                    )
                    for tc in response.tool_calls
                ]

                # Emit pending + running events for all calls (in order, before any execution)
                if event_emitter:
                    for call in calls:
                        await self._emit(
                            event_emitter,
                            "tool_call",
                            {
                                "id": call.id,
                                "capability": call.name,
                                "args": call.args,
                                "status": "pending",
                            },
                        )
                    for call in calls:
                        await self._emit(
                            event_emitter,
                            "tool_call",
                            {
                                "id": call.id,
                                "capability": call.name,
                                "args": call.args,
                                "status": "running",
                            },
                        )

                # Dispatch all tool calls concurrently.
                # Independent tools (read_file, web_search, run_subagent, etc.)
                # run in parallel via asyncio.gather.
                async def _mediate_one(call: ToolCall) -> SyscallResult:
                    return await syscall_handler.mediate(
                        call=call,
                        session=session,
                        agent_config=agent_config,
                        run_id=run_id,
                        event_emitter=event_emitter,
                    )

                syscall_results = await asyncio.gather(*[_mediate_one(c) for c in calls])

                # Process results in order (to maintain history ordering)
                for call, syscall_result in zip(calls, syscall_results, strict=True):
                    # Emit tool_call complete/denied
                    if event_emitter:
                        status = "complete" if syscall_result.allowed else "denied"
                        await self._emit(
                            event_emitter,
                            "tool_call",
                            {
                                "id": call.id,
                                "capability": call.name,
                                "args": call.args,
                                "status": status,
                                "result": syscall_result.output,
                            },
                        )

                    result.tool_calls_made.append(
                        {
                            "id": call.id,
                            "name": call.name,
                            "args": call.args,
                            "allowed": syscall_result.allowed,
                            "result": syscall_result.output,
                        }
                    )

                    # Add tool result to history
                    if syscall_result.allowed:
                        output = syscall_result.output
                        # Track consecutive failures (empty/error results)
                        is_empty = (
                            output is None
                            or output == ""
                            or (isinstance(output, dict) and output.get("results") == [])
                        )
                        if is_empty:
                            consecutive_tool_failures += 1
                        else:
                            consecutive_tool_failures = 0
                        history.append(
                            {
                                "role": "tool",
                                "content": json.dumps(output) if output else "",
                                "tool_call_id": call.id,
                                "name": call.name,
                            }
                        )
                    else:
                        consecutive_tool_failures += 1
                        history.append(
                            {
                                "role": "tool",
                                "content": f"Denied: {syscall_result.denied_reason}",
                                "tool_call_id": call.id,
                                "name": call.name,
                            }
                        )

                # Stop if too many consecutive tool failures
                if consecutive_tool_failures >= max_consecutive_failures:
                    history.append(
                        {
                            "role": "user",
                            "content": f"Note: {consecutive_tool_failures} consecutive tool calls returned empty or failed results. Stop calling tools and respond with what you know.",
                        }
                    )

                # Emit turn_complete
                if event_emitter:
                    await self._emit(
                        event_emitter,
                        "turn_complete",
                        {
                            "turn_number": result.total_turns,
                            "tokens_in": response.tokens_in,
                            "tokens_out": response.tokens_out,
                            "cost": response.cost,
                        },
                    )

                # Continue the loop (model will be called again)
                continue

            # No tool calls → this is the final answer
            # Add the assistant message to history
            history.append({"role": "assistant", "content": response.content or ""})
            # Apply guardrails before emitting to the user (D2)
            guardrail_result = apply_guardrails(response.content)
            result.final_answer = guardrail_result.content
            result.guardrail_warnings = guardrail_result.warnings
            result.guardrail_redactions = guardrail_result.redactions

            # Emit turn_complete for the final turn
            # (tokens were already streamed via _call_streaming if streaming)
            if event_emitter:
                if not hasattr(self.model, "complete_stream"):
                    # Non-streaming path: emit the guardrailed content as one token event
                    await self._emit(event_emitter, "token", {"content": guardrail_result.content})
                else:
                    # Streaming path: tokens were already emitted raw during streaming.
                    # If guardrails modified the content, emit a correction event so
                    # the frontend can replace the streamed output with the clean version.
                    if guardrail_result.content != response.content:
                        await self._emit(
                            event_emitter,
                            "guardrail_correction",
                            {"content": guardrail_result.content},
                        )
                # Emit guardrail warnings (if any) so the UI can show a notice
                if guardrail_result.warnings:
                    await self._emit(
                        event_emitter,
                        "guardrail_warning",
                        {"warnings": guardrail_result.warnings},
                    )
                await self._emit(
                    event_emitter,
                    "turn_complete",
                    {
                        "turn_number": result.total_turns,
                        "tokens_in": response.tokens_in,
                        "tokens_out": response.tokens_out,
                        "cost": response.cost,
                    },
                )

            # Step 10: Check limits
            if result.total_cost > max_cost:
                result.status = "limit_exceeded"
                result.final_answer = agent_config.fallback.on_limit_exceeded
                break

            break

        # Step 11: Check if we hit the turn limit
        if result.total_turns >= max_turns and not result.final_answer:
            result.status = "limit_exceeded"
            result.final_answer = "I've reached my turn limit for this run."

        # Emit message_complete
        if event_emitter:
            await self._emit(
                event_emitter,
                "message_complete",
                {
                    "run_id": run_id,
                    "total_cost": result.total_cost,
                    "total_turns": result.total_turns,
                    "status": result.status,
                },
            )

        return result

    async def _emit(self, emitter: EventEmitter, event_type: str, payload: dict[str, Any]) -> None:
        """Safely emit an SSE event."""
        if emitter is None:
            return
        result = emitter(event_type, payload)
        if hasattr(result, "__await__"):
            await result

    async def _call_streaming(
        self,
        agent_config: AgentConfig,
        history: list[dict[str, str]],
        tool_schemas: list[dict[str, Any]],
        event_emitter: EventEmitter,
    ) -> ScriptedResponse:
        """Call the model with streaming, emitting token/thinking events as they arrive."""
        response: ScriptedResponse | None = None
        async for delta_type, content in self.model.complete_stream(
            agent_model=agent_config.model,
            messages=history,
            tools=tool_schemas,
        ):
            if delta_type == "token" and event_emitter:
                await self._emit(event_emitter, "token", {"content": content})
            elif delta_type == "thinking" and event_emitter:
                await self._emit(event_emitter, "thinking", {"content": content})
            elif delta_type == "done":
                response = content

        if response is None:
            raise RuntimeError("Streaming ended without a 'done' event")
        return response
