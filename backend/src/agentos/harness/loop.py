"""Harness — the agent execution loop (D2, D19 steps 7-11).

Assembles context, calls the model, iterates on tool calls (mediated by
the syscall layer), enforces turn/cost limits, and emits SSE events.
"""

import json
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from ..config_schema import AgentConfig
from ..syscall.protocol import SyscallHandler, SyscallResult, ToolCall
from .context import assemble_system_prompt, assemble_tool_schemas, build_message_history
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
    ) -> RunResult:
        """Execute the agent loop (D19 steps 7-11).

        7. Assemble context
        8. Reason (call model)
        9. Mediate (tool calls through syscall layer)
        10. Check limits
        11. Iterate until final answer or limit hit
        """
        # Step 7: Assemble context
        system_prompt = assemble_system_prompt(agent_config)
        tool_schemas = assemble_tool_schemas(agent_config)
        history = build_message_history(system_prompt, recent_messages or [], message)

        # Emit typing event
        if event_emitter:
            await self._emit(event_emitter, "typing", {})

        result = RunResult()
        max_turns = agent_config.limits.max_turns_per_run
        max_cost = (
            agent_config.limits.max_cost_per_run
            if trigger == "user_message"
            else agent_config.heartbeat.max_cost_per_heartbeat
        )

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
                        await self._emit(
                            event_emitter, "thinking", {"content": response.thinking}
                        )
            except Exception as e:
                result.status = "failed"
                result.error = str(e)
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
                for tc in response.tool_calls:
                    call = ToolCall(
                        id=tc.get("id", str(uuid.uuid4())),
                        name=tc["name"],
                        args=tc.get("args", {}),
                    )

                    # Emit tool_call pending
                    if event_emitter:
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

                    # Emit tool_call running (before execution)
                    if event_emitter:
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

                    # Mediate
                    syscall_result: SyscallResult = await syscall_handler.mediate(
                        call=call,
                        session=session,
                        agent_config=agent_config,
                        run_id=run_id,
                        event_emitter=event_emitter,
                    )

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
                        history.append(
                            {
                                "role": "tool",
                                "content": json.dumps(syscall_result.output)
                                if syscall_result.output
                                else "",
                                "tool_call_id": call.id,
                                "name": call.name,
                            }
                        )
                    else:
                        history.append(
                            {
                                "role": "tool",
                                "content": f"Denied: {syscall_result.denied_reason}",
                                "tool_call_id": call.id,
                                "name": call.name,
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
            result.final_answer = response.content

            # Emit turn_complete for the final turn
            # (tokens were already streamed via _call_streaming if streaming)
            if event_emitter:
                if not hasattr(self.model, "complete_stream"):
                    # Non-streaming path: emit the full content as one token event
                    await self._emit(event_emitter, "token", {"content": response.content})
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
