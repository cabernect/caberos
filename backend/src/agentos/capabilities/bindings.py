"""Tool binding specs + the single resolution authority (W5).

A binding answers "how does this tool execute" — which engine/provider/model
and which validated options. Per-agent capability grants remain the separate
"who may execute" check (syscall mediation is unchanged).

Kinds:
- "engine": built-in execution or a keyed service (web search: DDGS/Tavily).
  DDGS needs no provider; Tavily binds a Provider ID without a model.
  Unconfigured == built-in defaults.
- "model": model-backed tool (TTS/image/…). Ready only when bound to an
  existing provider with credentials and a non-empty model name.

Readiness = spec implemented + valid configuration + available provider.
Resolution never calls providers — validation is local-only.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.provider import Provider
from ..models.tool_binding import ToolBinding
from ..providers.search_endpoints import SELF_HOSTED, validate_self_hosted
from ..providers.service_types import SEARCH_PROVIDER_TYPES, SERVICE_PROVIDER_TYPES

# Engines the bundled DDGS 9.x adapter knows how to call (valid backend
# keys for the "text" category), in default try-order.
SEARCH_ENGINES: tuple[str, ...] = (
    "duckduckgo",
    "brave",
    "startpage",
    "yahoo",
    "mojeek",
    "wikipedia",
)

# Provider types that work without a stored credential (local endpoints).
_NO_KEY_PROVIDER_TYPES: frozenset[str] = frozenset({"ollama", "lmstudio", "llama.cpp"})


@dataclass(frozen=True)
class OptionField:
    """One validated option field — enough shape for the UI to render honest
    controls and for the API to reject anything else."""

    name: str
    kind: Literal["string", "number", "boolean", "select", "engine_order"]
    label: str
    default: Any = None
    choices: tuple[str, ...] = ()  # for "select" and the universe of "engine_order"
    required: bool = False
    backends: tuple[str, ...] = ()


@dataclass(frozen=True)
class BindingSpec:
    """A bindable tool entry — static, code-owned. capabilities/builtin.py
    references specs by key; the Settings → Tools UI renders this."""

    key: str
    title: str
    description: str
    kind: Literal["engine", "model"]
    implemented: bool
    capability_names: tuple[str, ...]  # capabilities gated by this binding
    option_fields: tuple[OptionField, ...] = ()
    planned_note: str | None = None  # honest copy for not-yet-implemented entries
    # Model-kind tools: required output modality for catalog model
    # suggestions (e.g. ("image",) for image generation). Suggestions are
    # assistive — the field stays free-text per D40 override policy.
    model_modalities: tuple[str, ...] | None = None
    # Model-kind tools bound to dedicated *service* providers (speech): the
    # bound provider.type must be one of these. Empty = a chat/model provider.
    service_types: tuple[str, ...] = ()


BINDING_SPECS: tuple[BindingSpec, ...] = (
    BindingSpec(
        key="search.web",
        title="Web search",
        description=(
            "Use free DDGS engines or Tavily, Exa, Firecrawl, or Brave Search API. "
            "Search credentials are managed here, independently of the chat model."
        ),
        kind="engine",
        implemented=True,
        capability_names=("web_search",),
        option_fields=(
            OptionField(
                name="backend",
                kind="select",
                label="Search backend",
                choices=(
                    "ddgs",
                    "tavily",
                    "exa",
                    "firecrawl",
                    "firecrawl_self_hosted",
                    "brave_search",
                ),
                default="ddgs",
            ),
            OptionField(
                name="search_depth",
                kind="select",
                label="Tavily search depth",
                choices=("basic", "advanced"),
                default="basic",
                backends=("tavily",),
            ),
            OptionField(
                name="exa_search_type",
                kind="select",
                label="Exa search type",
                choices=("auto", "fast"),
                default="auto",
                backends=("exa",),
            ),
            OptionField(
                name="brave_safesearch",
                kind="select",
                label="Brave SafeSearch",
                choices=("off", "moderate", "strict"),
                default="moderate",
                backends=("brave_search",),
            ),
            OptionField(
                name="engines",
                kind="engine_order",
                label="Engines (in try order)",
                choices=SEARCH_ENGINES,
                default=list(SEARCH_ENGINES),
                backends=("ddgs",),
            ),
            OptionField(
                name="safesearch",
                kind="select",
                label="SafeSearch",
                choices=("on", "moderate", "off"),
                default="moderate",
                backends=("ddgs",),
            ),
            OptionField(
                name="region",
                kind="string",
                label="Region (e.g. us-en, wt-wt)",
                default="wt-wt",
                backends=("ddgs",),
            ),
        ),
    ),
    BindingSpec(
        key="exec.terminal",
        title="Terminal",
        description=(
            "Where agent shell commands run. Auto picks the OS-native sandbox "
            "(Seatbelt on macOS, Bubblewrap on Linux, MXC on Windows). An "
            "explicit backend must be supported and installed — a bad pick "
            "refuses honestly rather than falling back to another backend."
        ),
        kind="engine",
        implemented=True,
        capability_names=("terminal",),
        option_fields=(
            OptionField(
                name="backend",
                kind="select",
                label="Execution backend",
                choices=("auto", "seatbelt", "bwrap", "mxc"),
                default="auto",
            ),
        ),
    ),
    # Speech cards are operator actions (W10) — no capability_names, so no
    # agent tool can ever route through them. Per-operation provider support
    # is the adapter registry in speech/service.py.
    BindingSpec(
        key="speech.stt",
        title="Speech to text",
        description=(
            "Composer dictation — record, transcribe, review the text, then "
            "send. Uses a dedicated speech provider, not the chat model."
        ),
        kind="model",
        implemented=True,
        capability_names=(),
        service_types=("elevenlabs", "gemini", "openai", "groq", "openrouter"),
        option_fields=(
            OptionField(
                name="language",
                kind="string",
                label="Language (blank = auto-detect)",
                default=None,
            ),
        ),
    ),
    BindingSpec(
        key="speech.tts",
        title="Text to speech",
        description=(
            "Read aloud beneath assistant messages — explicit operator "
            "playback, never automatic. Uses a dedicated speech provider."
        ),
        kind="model",
        implemented=True,
        capability_names=(),
        service_types=("elevenlabs", "gemini", "openai", "groq", "openrouter"),
        model_modalities=("audio",),
        option_fields=(
            OptionField(
                name="voice",
                kind="string",
                label="Voice",
                default=None,
            ),
        ),
    ),
    BindingSpec(
        key="media.image",
        title="Image generation & editing",
        description="Generate images from a prompt, or edit a workspace image, "
        "saving results as artifacts.",
        kind="model",
        implemented=True,
        capability_names=("image_generate", "image_edit"),
        model_modalities=("image",),
        option_fields=(
            OptionField(
                name="size",
                kind="select",
                label="Size",
                choices=("auto", "1024x1024", "1536x1024", "1024x1536"),
                default="auto",
            ),
            OptionField(
                name="quality",
                kind="select",
                label="Quality",
                choices=("auto", "low", "medium", "high"),
                default="auto",
            ),
            OptionField(
                name="format",
                kind="select",
                label="Format",
                choices=("png", "jpeg", "webp"),
                default="png",
            ),
        ),
    ),
)

_SPECS_BY_KEY: dict[str, BindingSpec] = {s.key: s for s in BINDING_SPECS}
_CAPABILITY_TO_KEY: dict[str, str] = {
    cap: spec.key for spec in BINDING_SPECS for cap in spec.capability_names
}


def spec_for(key: str) -> BindingSpec | None:
    return _SPECS_BY_KEY.get(key)


def binding_key_for_capability(name: str) -> str | None:
    return _CAPABILITY_TO_KEY.get(name)


def validate_options(spec: BindingSpec, options: dict[str, Any]) -> dict[str, Any]:
    """Validate a raw options dict against the spec. Returns the normalized
    dict (defaults filled). Raises ValueError with a human reason on any
    violation — callers translate to 422."""
    if not isinstance(options, dict):
        raise ValueError("options must be an object")
    known = {f.name: f for f in spec.option_fields}
    unknown = set(options) - set(known)
    if unknown:
        raise ValueError(f"unknown option(s): {', '.join(sorted(unknown))}")

    normalized: dict[str, Any] = {}
    for field in spec.option_fields:
        raw = options.get(field.name, field.default)
        if raw is None:
            if field.required:
                raise ValueError(f"{field.name} is required")
            normalized[field.name] = None
            continue
        if field.kind == "boolean":
            if not isinstance(raw, bool):
                raise ValueError(f"{field.name} must be a boolean")
            normalized[field.name] = raw
        elif field.kind == "number":
            if not isinstance(raw, (int, float)) or isinstance(raw, bool):
                raise ValueError(f"{field.name} must be a number")
            normalized[field.name] = raw
        elif field.kind == "string":
            if not isinstance(raw, str):
                raise ValueError(f"{field.name} must be a non-empty string")
            raw = raw.strip()
            if not raw:
                if field.required:
                    raise ValueError(f"{field.name} must be a non-empty string")
                normalized[field.name] = None
                continue
            normalized[field.name] = raw
        elif field.kind == "select":
            if raw not in field.choices:
                raise ValueError(f"{field.name} must be one of: {', '.join(field.choices)}")
            normalized[field.name] = raw
        elif field.kind == "engine_order":
            if (
                not isinstance(raw, list)
                or not raw
                or any(e not in field.choices for e in raw)
                or len(set(raw)) != len(raw)
            ):
                raise ValueError(
                    f"{field.name} must be a non-empty ordering of: {', '.join(field.choices)}"
                )
            normalized[field.name] = list(raw)
    return normalized


def default_options(spec: BindingSpec) -> dict[str, Any]:
    return validate_options(spec, {})


@dataclass
class BindingResolution:
    """The one resolver output — catalog, UI and execution all read this."""

    spec: BindingSpec
    binding: ToolBinding | None
    provider: Provider | None
    ready: bool
    state: str  # "unconfigured" | "ready" | "invalid" | "unimplemented"
    reason: str
    options: dict[str, Any]
    identity: tuple = dataclass_field(init=False, repr=False)

    def __post_init__(self) -> None:
        # Snapshot values, not ORM identities: another query can refresh the same
        # objects while an approval is waiting.
        self.identity = (
            self.binding.revision if self.binding else None,
            self.binding.provider_id if self.binding else None,
            self.binding.model if self.binding else None,
            json.dumps(self.options, sort_keys=True),
            self.provider.type if self.provider else None,
            self.provider.encrypted_key if self.provider else None,
            self.provider.encrypted_credentials if self.provider else None,
            self.provider.base_url if self.provider else None,
            self.provider.org_id if self.provider else None,
            self.provider.extra_params if self.provider else None,
        )


async def resolve_binding(db: AsyncSession, key: str) -> BindingResolution:
    """Resolve a binding key to readiness. Local reads only — no provider
    calls, no network. Safe to call on every mediation."""
    spec = spec_for(key)
    if spec is None:
        raise KeyError(f"unknown binding key: {key}")
    if not spec.implemented:
        return BindingResolution(
            spec=spec,
            binding=None,
            provider=None,
            ready=False,
            state="unimplemented",
            reason=spec.planned_note or "Not implemented in this release.",
            options={},
        )

    binding = await db.scalar(
        select(ToolBinding).where(ToolBinding.key == key).execution_options(populate_existing=True)
    )
    try:
        stored = json.loads(binding.options) if binding else {}
        options = validate_options(spec, stored)
    except ValueError as e:
        return BindingResolution(
            spec=spec,
            binding=binding,
            provider=None,
            ready=False,
            state="invalid",
            reason=f"stored options invalid: {e}",
            options={},
        )

    service_search = spec.key == "search.web" and options.get("backend") in SEARCH_PROVIDER_TYPES
    if spec.kind == "engine" and not service_search:
        # Engine tools run self-contained — a binding only tunes them.
        return BindingResolution(
            spec=spec,
            binding=binding,
            provider=None,
            ready=not (binding and binding.provider_id),
            state="invalid"
            if binding and binding.provider_id
            else ("ready" if binding else "unconfigured"),
            reason="DDGS does not use a provider."
            if binding and binding.provider_id
            else ("" if binding else "Using built-in defaults."),
            options=options,
        )

    # model-backed: provider + credentials + model name all required
    if binding is None:
        return BindingResolution(
            spec=spec,
            binding=None,
            provider=None,
            ready=False,
            state="unconfigured",
            reason="Choose a search provider."
            if service_search
            else ("Choose a provider and model to enable this tool."),
            options=options,
        )
    if not binding.provider_id:
        return BindingResolution(
            spec=spec,
            binding=binding,
            provider=None,
            ready=False,
            state="invalid",
            reason="Binding has no provider.",
            options=options,
        )
    provider = await db.get(Provider, binding.provider_id, populate_existing=True)
    if provider is None:
        return BindingResolution(
            spec=spec,
            binding=binding,
            provider=None,
            ready=False,
            state="invalid",
            reason="Bound provider no longer exists — pick a new one.",
            options=options,
        )
    if spec.service_types:
        incompatible = provider.type not in spec.service_types
    else:
        incompatible = (service_search and provider.type != options["backend"]) or (
            not service_search and provider.type in SERVICE_PROVIDER_TYPES
        )
    if incompatible:
        return BindingResolution(
            spec,
            binding,
            provider,
            False,
            "invalid",
            "Provider type is incompatible with this tool.",
            options,
        )
    has_key = (
        bool(provider.encrypted_key)
        if service_search
        else bool(provider.encrypted_key or provider.encrypted_credentials)
    )
    if service_search and provider.type == SELF_HOSTED:
        try:
            validate_self_hosted(provider.base_url, json.loads(provider.extra_params or "{}"))
        except ValueError:
            return BindingResolution(
                spec,
                binding,
                provider,
                False,
                "invalid",
                "Check the self-hosted server URL and private-network consent.",
                options,
            )
    if not has_key and provider.type not in _NO_KEY_PROVIDER_TYPES and provider.type != SELF_HOSTED:
        return BindingResolution(
            spec=spec,
            binding=binding,
            provider=provider,
            ready=False,
            state="invalid",
            reason=f"Provider '{provider.name}' has no credentials.",
            options=options,
        )
    if not service_search and not binding.model.strip():
        return BindingResolution(
            spec=spec,
            binding=binding,
            provider=provider,
            ready=False,
            state="invalid",
            reason="Binding has no model selected.",
            options=options,
        )
    return BindingResolution(
        spec=spec,
        binding=binding,
        provider=provider,
        ready=True,
        state="ready",
        reason="",
        options=options,
    )


async def capability_ready(db: AsyncSession, capability_name: str) -> bool:
    """Catalog gate: is a binding-gated capability loadable right now?
    Capabilities without a binding spec are always ready — the ceiling
    check stays separate."""
    key = binding_key_for_capability(capability_name)
    if key is None:
        return True
    resolution = await resolve_binding(db, key)
    if resolution.spec.kind == "engine":
        return resolution.state != "invalid"  # engine defaults stay usable
    return resolution.ready
