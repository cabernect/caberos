"""Service providers share credential storage, not model discovery/dispatch."""

from typing import Literal

SEARCH_PROVIDER_LABELS = {
    "tavily": "Tavily",
    "exa": "Exa",
    "firecrawl": "Firecrawl Cloud",
    "firecrawl_self_hosted": "Firecrawl self-hosted",
    "brave_search": "Brave Search API",
}
SEARCH_PROVIDER_TYPES = frozenset(SEARCH_PROVIDER_LABELS)
SERVICE_PROVIDER_TYPES = SEARCH_PROVIDER_TYPES


def provider_scope(provider_type: str) -> Literal["model", "search"]:
    return "search" if provider_type in SEARCH_PROVIDER_TYPES else "model"


def require_model_provider(provider_type: str) -> None:
    if provider_type in SERVICE_PROVIDER_TYPES:
        raise ValueError("This provider supplies a tool service, not chat or model discovery.")
