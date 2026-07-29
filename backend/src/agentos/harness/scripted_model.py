"""Scripted model double — returns predetermined responses for testing.

This is NOT a real model. It returns a scripted sequence of tool calls
and final answers, so the tracer bullet (ticket 01) can test the full
pipeline without an API key or a real LLM.
"""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ScriptedResponse:
    """One response from the scripted model."""

    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    content: str = ""
    thinking: str = ""
    tokens_in: int = 0
    tokens_out: int = 0
    cost: float = 0.0


@dataclass
class ScriptedModel:
    """A fake model that returns scripted responses in sequence.

    Usage:
        model = ScriptedModel([
            ScriptedResponse(
                tool_calls=[{
                    "id": "call_1",
                    "name": "shell.run",
                    "args": {"command": "echo hello"},
                }]
            ),
            ScriptedResponse(content="The command output: hello"),
        ])
        # The harness calls model.complete() twice:
        #   1st call → returns the tool call
        #   2nd call → returns the final answer
    """

    responses: list[ScriptedResponse]
    _index: int = field(default=0, init=False, repr=False)

    async def complete(
        self,
        agent_model: Any = None,
        messages: list[dict[str, str]] | None = None,
        tools: list[dict[str, Any]] | None = None,
        **_kwargs: Any,
    ) -> ScriptedResponse:
        """Return the next scripted response."""
        if messages is None:
            messages = []
        if self._index >= len(self.responses):
            # Default: return a simple final answer
            return ScriptedResponse(content="Done.", tokens_in=10, tokens_out=1, cost=0.0)
        resp = self.responses[self._index]
        self._index += 1
        # Fill in fake token counts if not set
        if resp.tokens_in == 0:
            resp.tokens_in = sum(len(m.get("content", "")) for m in messages) // 4  # rough estimate
        if resp.tokens_out == 0:
            resp.tokens_out = (len(resp.content) + sum(len(str(tc)) for tc in resp.tool_calls)) // 4
        if resp.cost == 0.0:
            resp.cost = (resp.tokens_in + resp.tokens_out) * 0.00001  # fake cost
        return resp
