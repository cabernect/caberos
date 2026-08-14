"""Provider adapters and transport seams."""

__all__ = ["ProviderRegistry"]


def __getattr__(name: str):
    if name == "ProviderRegistry":
        from .registry import ProviderRegistry

        return ProviderRegistry
    raise AttributeError(name)
