"""Read projection for model-call accounting receipts.

`detail.cost_assessment` / `detail.rate_authority` are stored receipts —
never re-derived on read. This module exposes a strict whitelist so the
run-detail and timeline APIs surface the amount, rate version and
classification an operator needs without leaking raw payloads, URLs, or
secrets. Anything not listed here stays in the store, not the API.
"""

from __future__ import annotations

import json
from typing import Any

from ..redaction import redact_text
from .cost_assessment import monetary_value

# Legacy scalar fields the existing APIs already exposed — preserved so
# the receipt fields are additive, not a shape change.
_LEGACY_KEYS = (
    "resource_id",
    "generation_id",
    "operation",
    "chunk_count",
    "cost_source",
)

_ASSESSMENT_SCALARS = (
    "amount",
    "source",
    "currency",
    "snapshot_revision",
    "calculated_at",
    "calculation_version",
)
_RATE_KEYS = ("input", "output", "cache_read", "cache_write", "reasoning")
_USAGE_KEYS = (
    "input_tokens",
    "output_tokens",
    "cache_read_tokens",
    "cache_write_tokens",
    "reasoning_tokens",
    "cache_write_1h_tokens",
    "audio_input_tokens",
    "audio_output_tokens",
)
_AUTHORITY_SCALARS = (
    "provider_id",
    "request_model_id",
    "config_fingerprint",
    "offering_revision",
    "snapshot_revision",
    "routing_override_unresolved",
)
_PRICING_AUTHORITY_KEYS = ("source", "confidence", "as_of")

_MAX_STR = 255
_MAX_REASON = 512
_MAX_PAYLOAD = 8000


def _clean_str(value: Any, limit: int = _MAX_STR) -> str | None:
    """Bounded redacted scalar — secrets are scrubbed before truncation
    so a limit cut can never expose a credential prefix."""
    if value is None or isinstance(value, (dict, list)):
        return None
    text, _, _ = redact_text(str(value), limit)
    return text


def _clean_counter(value: Any) -> int | None:
    """Nullable token counter — strict non-bool int, [0, 2**63)."""
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value if 0 <= value < 2**63 else None


def _project_assessment(raw: Any) -> dict | None:
    if not isinstance(raw, dict):
        return None
    out: dict[str, Any] = {k: _clean_str(raw.get(k)) for k in _ASSESSMENT_SCALARS}
    reason = raw.get("reason")
    out["reason"] = _clean_str(reason, _MAX_REASON) if reason is not None else None

    rates = raw.get("rates")
    if isinstance(rates, dict):
        out["rates"] = {
            k: (format(v, "f") if (v := monetary_value(rates[k])) is not None else None)
            for k in _RATE_KEYS
            if k in rates
        }
    else:
        out["rates"] = None

    usage = raw.get("usage")
    if isinstance(usage, dict):
        out["usage"] = {k: _clean_counter(usage.get(k)) for k in _USAGE_KEYS}
    else:
        out["usage"] = None

    tier = raw.get("tier")
    if isinstance(tier, dict):
        # Fixed shape — {"type": "context", "size": int} only.
        out["tier"] = {
            "type": _clean_str(tier.get("type")),
            "size": _clean_counter(tier.get("size")),
        }
    else:
        out["tier"] = None
    return out


def _project_authority(raw: Any) -> dict | None:
    if not isinstance(raw, dict):
        return None
    out: dict[str, Any] = {}
    for key in _AUTHORITY_SCALARS:
        value = raw.get(key)
        if key == "routing_override_unresolved":
            out[key] = value if isinstance(value, bool) else None
        elif key == "offering_revision":
            out[key] = _clean_counter(value)
        else:
            out[key] = _clean_str(value)
    pricing = raw.get("pricing_authority")
    if isinstance(pricing, dict):
        out["pricing_authority"] = {k: _clean_str(pricing.get(k)) for k in _PRICING_AUTHORITY_KEYS}
    else:
        out["pricing_authority"] = None
    return out


def project_call_detail(detail: Any) -> dict | None:
    """Whitelist a stored call detail for read APIs.

    Legacy keys pass through typed+redacted; the receipt fields land as
    fixed-shape structures. Total projected payload bounded at 8000
    characters of JSON — no arbitrary dict content escapes the store.
    """
    if not isinstance(detail, dict):
        return None
    out: dict[str, Any] = {
        k: _clean_str(detail[k]) if not isinstance(detail[k], (int, bool)) else detail[k]
        for k in _LEGACY_KEYS
        if k in detail
    }
    assessment = _project_assessment(detail.get("cost_assessment"))
    if assessment is not None:
        out["cost_assessment"] = assessment
    authority = _project_authority(detail.get("rate_authority"))
    if authority is not None:
        out["rate_authority"] = authority
    if len(json.dumps(out, default=str)) > _MAX_PAYLOAD:
        # Drop the optional bulky field first, then bail to legacy-only.
        out.pop("rate_authority", None)
        if len(json.dumps(out, default=str)) > _MAX_PAYLOAD:
            out.pop("cost_assessment", None)
    return out or None
