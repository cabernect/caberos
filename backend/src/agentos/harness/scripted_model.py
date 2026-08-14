"""Scripted model double — returns predetermined responses for testing.

This is NOT a real model. It returns a scripted sequence of tool calls
and final answers, so the tracer bullet (ticket 01) can test the full
pipeline without an API key or a real LLM.
"""

import asyncio
from collections.abc import AsyncIterator
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
    cached_tokens: int | None = None
    cost: float = 0.0


@dataclass
class ScriptedModel:
    """A fake model that returns scripted responses in sequence.

    Usage:
        model = ScriptedModel([
            ScriptedResponse(
                tool_calls=[{
                    "id": "call_1",
                    "name": "terminal",
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

    async def complete_stream(
        self,
        agent_model: Any = None,
        messages: list[dict[str, str]] | None = None,
        tools: list[dict[str, Any]] | None = None,
        **_kwargs: Any,
    ) -> AsyncIterator[tuple[str, Any]]:
        """Streaming variant — emits thinking chunks, then token chunks, then done.

        Yields tuples of (delta_type, content):
          - ("thinking", str) — thinking text chunk
          - ("token", str) — output token chunk
          - ("done", ScriptedResponse) — final response object
        """
        if self._index >= len(self.responses):
            resp = ScriptedResponse(content="Done.", tokens_in=10, tokens_out=1, cost=0.0)
            yield "done", resp
            return

        resp = self.responses[self._index]
        self._index += 1
        # Fill in fake token counts
        if resp.tokens_in == 0:
            resp.tokens_in = sum(len(m.get("content", "")) for m in (messages or [])) // 4
        if resp.tokens_out == 0:
            resp.tokens_out = (len(resp.content) + sum(len(str(tc)) for tc in resp.tool_calls)) // 4
        if resp.cost == 0.0:
            resp.cost = (resp.tokens_in + resp.tokens_out) * 0.00001

        # Stream thinking word-by-word
        if resp.thinking:
            words = resp.thinking.split(" ")
            for i, w in enumerate(words):
                chunk = w + (" " if i < len(words) - 1 else "")
                yield "thinking", chunk
                await asyncio.sleep(0.04)

        # Stream content word-by-word (only if no tool calls — tool calls are handled separately)
        if resp.content and not resp.tool_calls:
            words = resp.content.split(" ")
            for i, w in enumerate(words):
                chunk = w + (" " if i < len(words) - 1 else "")
                yield "token", chunk
                await asyncio.sleep(0.06)

        yield "done", resp
