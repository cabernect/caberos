"""Exact offering identity and field-level authority for catalog consumers."""

import json
from copy import deepcopy
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import urlparse

# An OpenAI-compatible transport is not evidence of OpenAI offering prices.
_OFFICIAL_PROVIDERS = {
    "openai": ("openai", {"api.openai.com"}),
    "anthropic": ("anthropic", {"api.anthropic.com"}),
    "google": ("google", {"generativelanguage.googleapis.com"}),
    "gemini": ("google", {"generativelanguage.googleapis.com"}),
    "openrouter": ("openrouter", {"openrouter.ai"}),
    "deepseek": ("deepseek", {"api.deepseek.com"}),
    "xai": ("xai", {"api.x.ai"}),
    "mistral": ("mistral", {"api.mistral.ai"}),
    "groq": ("groq", {"api.groq.com"}),
    "together_ai": ("togetherai", {"api.together.xyz", "api.together.ai"}),
    "fireworks_ai": ("fireworks-ai", {"api.fireworks.ai"}),
    "perplexity": ("perplexity", {"api.perplexity.ai"}),
    "cohere": ("cohere", {"api.cohere.com"}),
    "ai21": ("ai21", {"api.ai21.com"}),
    "nvidia_nim": ("nvidia", {"integrate.api.nvidia.com"}),
    "zhipu": ("zhipuai", {"open.bigmodel.cn"}),
}
_LIMIT_FIELDS = {
    "max_context_tokens": "input",
    "context_window_tokens": "context",
    "max_output_tokens": "output",
}
_BOOL_FIELDS = {"supports_vision", "supports_thinking", "tool_call", "structured_output"}
_MODEL_FIELDS = (
    "display_name",
    *_LIMIT_FIELDS,
    "supports_vision",
    "supports_thinking",
    "thinking_efforts",
    "reasoning_options",
    "modalities",
    "tool_call",
    "structured_output",
    "temperature",
    "lifecycle",
    "pricing",
)


def resolve_input_budget(
    metadata: dict | None,
    *,
    model_override: int | None = None,
    run_override: int | None = None,
    output_tokens: int | None = None,
) -> dict:
    """Choose an input allocation without inventing a model capacity."""
    fields = metadata or {}

    def positive(value: Any) -> int | None:
        return (
            value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else None
        )

    for value in (model_override, run_override, output_tokens):
        if value is not None and positive(value) is None:
            raise ValueError("Configured token budgets must be positive integers")
    inputs = positive(fields.get("max_context_tokens"))
    context = positive(fields.get("context_window_tokens"))
    reserve = output_tokens or positive(fields.get("max_output_tokens")) or 4096
    if model_override is not None:
        tokens, source = model_override, "user_model_budget"
    elif context is not None:
        remaining = context - reserve
        if remaining <= 0:
            raise ValueError("Output reserve leaves no input capacity in the documented context")
        tokens = min(inputs, remaining) if inputs is not None else remaining
        source = (
            "resolved_input_limit"
            if inputs is not None and tokens == inputs
            else "derived_context_budget"
        )
    elif inputs is not None:
        tokens, source = inputs, "resolved_input_limit"
    else:
        tokens, source = 32768, "application_fallback"
    if run_override is not None and run_override < tokens:
        tokens, source = run_override, "user_run_budget"
    return {
        "tokens": tokens,
        "source": source,
        "model_limit_known": inputs is not None or context is not None,
        "output_reserve": reserve if context is not None and model_override is None else None,
    }


def catalog_identity(
    provider_type: str,
    model_id: str,
    base_url: str | None = None,
    *,
    catalog_provider_id: str | None = None,
    catalog_model_id: str | None = None,
) -> tuple[str, str] | None:
    """Map only a declared offering or a known official endpoint, never a nickname."""
    if catalog_provider_id:
        return catalog_provider_id, catalog_model_id or model_id
    if catalog_model_id:
        return None
    mapping = _OFFICIAL_PROVIDERS.get(provider_type)
    if mapping is None:
        return None
    key, hosts = mapping
    if base_url:
        parsed = urlparse(base_url)
        if (
            parsed.scheme != "https"
            or parsed.hostname not in hosts
            or parsed.username
            or parsed.password
        ):
            return None
    return key, model_id


def _positive_integer(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        return None
    try:
        number = Decimal(str(value))
        if number.is_finite() and number > 0 and number == number.to_integral_value():
            return int(number)
    except (InvalidOperation, ValueError, OverflowError):
        pass
    return None


def _string_list(value: Any) -> list[str] | None:
    if isinstance(value, list) and all(isinstance(item, str) and item for item in value):
        return list(dict.fromkeys(value))
    return None


def _field_value(field: str, value: Any) -> Any:
    if value is None:
        return None
    if field in _LIMIT_FIELDS:
        return _positive_integer(value)
    if field in _BOOL_FIELDS or field == "temperature":
        return value if isinstance(value, bool) else None
    if field in ("thinking_efforts",):
        return _string_list(value)
    if field == "display_name":
        return value if isinstance(value, str) and value.strip() else None
    if field == "lifecycle":
        return value if value in ("alpha", "beta", "deprecated", "active") else None
    if field == "modalities":
        if not isinstance(value, dict):
            return None
        result = {
            direction: items
            for direction in ("input", "output")
            if (items := _string_list(value.get(direction))) is not None
        }
        return result or None
    if field == "reasoning_options":
        if isinstance(value, list) and all(isinstance(item, dict) for item in value):
            return deepcopy(value)
        return None
    if field == "pricing":
        if isinstance(value, dict) and value:
            return json.loads(json.dumps(value, default=lambda number: str(number)))
        return None
    return None


def project_model(raw: dict) -> dict:
    """Project known catalog fields without inventing missing limits or controls."""
    limit = raw.get("limit") if isinstance(raw.get("limit"), dict) else {}
    result = {field: _positive_integer(limit.get(key)) for field, key in _LIMIT_FIELDS.items()}
    for field, key in (
        ("display_name", "name"),
        ("supports_thinking", "reasoning"),
        ("modalities", "modalities"),
        ("reasoning_options", "reasoning_options"),
        ("tool_call", "tool_call"),
        ("structured_output", "structured_output"),
        ("temperature", "temperature"),
        ("lifecycle", "status"),
        ("pricing", "cost"),
    ):
        result[field] = _field_value(field, raw.get(key))
    modalities = result["modalities"]
    result["supports_vision"] = (
        "image" in modalities["input"] if modalities and "input" in modalities else None
    )
    options = result["reasoning_options"]
    result["thinking_efforts"] = (
        list(
            dict.fromkeys(
                value
                for option in options
                if option.get("type") == "effort"
                for value in (_string_list(option.get("values")) or [])
            )
        )
        if options is not None
        else None
    )
    return result


def validate_overrides(fields: dict) -> dict:
    """Reject malformed declarations rather than coercing them into model facts."""
    if not isinstance(fields, dict):
        raise ValueError("model overrides must be an object")
    result = {}
    for field, value in fields.items():
        if field not in _MODEL_FIELDS:
            raise ValueError(f"unsupported model field: {field}")
        normalized = _field_value(field, value)
        if value is not None and normalized is None:
            raise ValueError(f"invalid model field: {field}")
        result[field] = normalized
    return result


def resolve_fields(
    catalog_model: dict | None,
    *,
    observed: dict | None = None,
    overrides: dict | None = None,
    as_of: str | None = None,
    observed_as_of: str | None = None,
    override_as_of: str | None = None,
) -> dict:
    """Return legacy display fields plus the actual value/source of every field."""
    catalog = project_model(catalog_model or {})
    observed = observed or {}
    overrides = validate_overrides(overrides or {})
    resolved: dict[str, Any] = {}
    provenance = {}
    for field in _MODEL_FIELDS:
        value = catalog.get(field)
        source = "models_dev" if value is not None else "unknown"
        confirmed_at = as_of if value is not None else None
        reported = _field_value(field, observed.get(field))
        if reported is not None:
            value, source, confirmed_at = reported, "provider", observed_as_of
        if overrides.get(field) is not None:
            value, source, confirmed_at = overrides[field], "user_override", override_as_of
        confidence = {
            "models_dev": "catalog_documented",
            "provider": "provider_reported",
            "user_override": "user_declared",
            "unknown": "unknown",
        }[source]
        provenance[field] = {
            "value": deepcopy(value),
            "source": source,
            "as_of": confirmed_at,
            "confidence": confidence,
        }
        resolved[field] = deepcopy(value)
    # Legacy booleans fail closed, while provenance distinguishes unknown from false.
    for field in _BOOL_FIELDS:
        if resolved[field] is None:
            resolved[field] = False
    if resolved["thinking_efforts"] is None:
        resolved["thinking_efforts"] = []
    resolved["provenance"] = provenance
    return resolved


def decode_catalog(payload: bytes) -> dict:
    """Validate the consumed projection and retain exact decimal rate literals."""
    if not isinstance(payload, bytes) or len(payload) > 16 * 1024 * 1024:
        raise ValueError("catalog exceeds the payload bound")

    def invalid_constant(value: str) -> None:
        raise ValueError(f"nonfinite catalog number: {value}")

    try:
        data = json.loads(payload, parse_float=Decimal, parse_constant=invalid_constant)
    except (UnicodeError, RecursionError, InvalidOperation) as error:
        raise ValueError("invalid catalog encoding") from error
    if not isinstance(data, dict) or not data:
        raise ValueError("catalog must contain provider records")
    has_models = False
    for provider_id, provider in data.items():
        if not provider_id or not isinstance(provider, dict):
            raise ValueError("invalid catalog provider")
        models = provider.get("models")
        if not isinstance(models, dict):
            raise ValueError("invalid catalog model collection")
        for model_id, model in models.items():
            has_models = True
            if not model_id or not isinstance(model, dict):
                raise ValueError("invalid catalog model")
            if not isinstance(model.get("name"), str) or not model["name"].strip():
                raise ValueError("catalog model is missing its name")
            if "id" in model and model["id"] != model_id:
                raise ValueError("catalog request model identity mismatch")
            for key in ("reasoning", "attachment", "tool_call", "temperature", "structured_output"):
                if key in model and not isinstance(model[key], bool):
                    raise ValueError("invalid catalog capability")
            limits = model.get("limit", {})
            if not isinstance(limits, dict):
                raise ValueError("invalid catalog limits")
            for key in ("input", "output", "context"):
                if key in limits and limits[key] != 0 and _positive_integer(limits[key]) is None:
                    raise ValueError("invalid catalog capacity")
                if isinstance(limits.get(key), bool):
                    raise ValueError("invalid catalog capacity")
            modalities = model.get("modalities", {})
            if not isinstance(modalities, dict):
                raise ValueError("invalid catalog modalities")
            for key in ("input", "output"):
                if key in modalities and _string_list(modalities[key]) is None:
                    raise ValueError("invalid catalog modality list")
            cost = model.get("cost")
            if cost is not None:
                if not isinstance(cost, dict):
                    raise ValueError("invalid catalog pricing")
                price_sets = [cost]
                tiers = cost.get("tiers", [])
                if not isinstance(tiers, list):
                    raise ValueError("invalid catalog price tiers")
                seen_thresholds = set()
                for tier in tiers:
                    if not isinstance(tier, dict) or not isinstance(tier.get("tier"), dict):
                        raise ValueError("invalid catalog price tier")
                    threshold = tier["tier"].get("size")
                    if isinstance(threshold, bool) or (
                        threshold != 0 and _positive_integer(threshold) is None
                    ):
                        raise ValueError("invalid catalog tier threshold")
                    if threshold in seen_thresholds:
                        raise ValueError("duplicate catalog tier threshold")
                    seen_thresholds.add(threshold)
                    price_sets.append(tier)
                if "context_over_200k" in cost:
                    if not isinstance(cost["context_over_200k"], dict):
                        raise ValueError("invalid legacy catalog price tier")
                    price_sets.append(cost["context_over_200k"])
                for prices in price_sets:
                    if "input" not in prices or "output" not in prices:
                        raise ValueError("catalog prices require input and output rates")
                    for key in (
                        "input",
                        "output",
                        "cache_read",
                        "cache_write",
                        "reasoning",
                        "input_audio",
                        "output_audio",
                    ):
                        if key not in prices:
                            continue
                        value = prices[key]
                        if (
                            isinstance(value, bool)
                            or not isinstance(value, (int, Decimal))
                            or not Decimal(value).is_finite()
                            or value < 0
                        ):
                            raise ValueError("invalid catalog rate")
    if not has_models:
        raise ValueError("catalog contains no model records")
    return data
