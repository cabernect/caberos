"""Normalized provider adapter interface used by the agent runtime."""

from collections.abc import AsyncIterator
from typing import Any, Protocol

from ..config_schema import ModelConfig
from ..harness.scripted_model import ScriptedResponse


class ProviderAdapter(Protocol):
    """Runtime interface implemented by model provider adapters."""

    async def complete(
        self,
        agent_model: ModelConfig | None = None,
        messages: list[dict[str, Any]] | None = None,
        tools: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> ScriptedResponse: ...

    def complete_stream(
        self,
        agent_model: ModelConfig | None = None,
        messages: list[dict[str, Any]] | None = None,
        tools: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[tuple[str, Any]]: ...
