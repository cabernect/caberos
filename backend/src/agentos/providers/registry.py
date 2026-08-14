"""Provider adapter registry."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..harness.litellm_adapter import LiteLLMAdapter
from ..models.provider import Provider
from .interface import ProviderAdapter
from .litellm_transport import LiteLLMTransport
from .opencode_zen_adapter import OpenCodeZenMixin


class LiteLLMProviderAdapter(LiteLLMAdapter):
    """Generic provider adapter backed by the shared LiteLLM transport."""


class OpenCodeZenProviderAdapter(OpenCodeZenMixin, LiteLLMAdapter):
    """OpenCode Zen adapter backed by the shared LiteLLM transport."""


class ProviderRegistry:
    """Resolve configured providers to runtime adapters."""

    def __init__(self, db: AsyncSession, transport: LiteLLMTransport | None = None):
        self.db = db
        self.transport = transport or LiteLLMTransport()

    async def for_provider(self, provider_id: str) -> ProviderAdapter:
        """Return the adapter selected for a configured provider."""
        result = await self.db.execute(select(Provider).where(Provider.id == provider_id))
        provider = result.scalar_one_or_none()
        if provider is None:
            raise ValueError(f"Provider {provider_id} not found")

        if (
            provider.type == "openai"
            and provider.base_url
            and "opencode.ai/zen" in provider.base_url.lower()
        ):
            return OpenCodeZenProviderAdapter(self.db, transport=self.transport)
        return LiteLLMProviderAdapter(self.db, transport=self.transport)

    async def for_model(self, provider_id: str) -> ProviderAdapter:
        """Alias emphasizing that the adapter is selected by model provider."""
        return await self.for_provider(provider_id)


__all__ = [
    "LiteLLMProviderAdapter",
    "OpenCodeZenProviderAdapter",
    "ProviderRegistry",
]
