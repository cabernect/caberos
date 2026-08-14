"""LiteLLM transport used by provider adapters."""

from typing import Any

import litellm


class LiteLLMTransport:
    """Small injectable seam around LiteLLM's async entry points."""

    async def completion(self, **kwargs: Any) -> Any:
        """Call LiteLLM's Chat Completions-compatible entry point."""
        return await litellm.acompletion(**kwargs)

    async def responses(self, **kwargs: Any) -> Any:
        """Call LiteLLM's OpenAI Responses entry point."""
        return await litellm.aresponses(**kwargs)
