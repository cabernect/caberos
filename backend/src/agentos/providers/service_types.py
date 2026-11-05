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

# Dedicated speech providers (W10). STT/TTS support is per operation — the
# adapter registry in speech/service.py is the operation support matrix.
SPEECH_PROVIDER_LABELS = {
    "elevenlabs": "ElevenLabs",
    "deepgram": "Deepgram",
    "gradium": "Gradium",
}
SPEECH_PROVIDER_TYPES = frozenset(SPEECH_PROVIDER_LABELS)

SERVICE_PROVIDER_TYPES = SEARCH_PROVIDER_TYPES | SPEECH_PROVIDER_TYPES


def provider_scope(provider_type: str) -> Literal["model", "search", "speech"]:
    if provider_type in SEARCH_PROVIDER_TYPES:
        return "search"
    if provider_type in SPEECH_PROVIDER_TYPES:
        return "speech"
    return "model"


def require_model_provider(provider_type: str) -> None:
    if provider_type in SERVICE_PROVIDER_TYPES:
        raise ValueError("This provider supplies a tool service, not chat or model discovery.")
