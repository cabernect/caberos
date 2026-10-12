"""Reproducible monetary assessments; no SDK pricing or network dependencies."""

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from decimal import Decimal, DecimalException, InvalidOperation, localcontext
from typing import Any

CALCULATION_VERSION = "aggregate-token-rates-v2"
_MILLION = Decimal(1_000_000)
_RATE_FIELDS = {"input", "output", "cache_read", "cache_write", "reasoning"}


@dataclass(frozen=True)
class UsageReceipt:
    # Unified chat/Responses input includes cache reads and creations. Output
    # includes reasoning. Native providers must be normalized before this seam.
    input_tokens: int | None
    output_tokens: int | None
    cache_read_tokens: int | None = None
    cache_write_tokens: int | None = None
    reasoning_tokens: int | None = None
    cache_write_1h_tokens: int | None = 0
    audio_input_tokens: int | None = 0
    audio_output_tokens: int | None = 0


@dataclass(frozen=True)
class CostAssessment:
    amount: Decimal | None
    source: str
    currency: str = "USD"
    reason: str | None = None
    snapshot_revision: str | None = None
    rates: dict | None = None
    usage: UsageReceipt | None = None
    calculated_at: str | None = None
    tier: dict | None = None
    calculation_version: str = CALCULATION_VERSION

    def to_dict(self) -> dict:
        return {
            "amount": format(self.amount, "f") if self.amount is not None else None,
            "source": self.source,
            "currency": self.currency,
            "reason": self.reason,
            "snapshot_revision": self.snapshot_revision,
            "rates": self.rates,
            "usage": asdict(self.usage) if self.usage is not None else None,
            "calculated_at": self.calculated_at,
            "calculation_version": self.calculation_version,
            "tier": self.tier,
        }


def monetary_value(value: Any) -> Decimal | None:
    if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
        return None
    if len(str(value)) > 256:
        return None
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    if (
        not amount.is_finite()
        or not 0 <= amount <= Decimal("1e30")
        or amount.as_tuple().exponent < -30
        or len(amount.as_tuple().digits) > 30
    ):
        return None
    return Decimal(0) if amount == 0 else amount


def _count(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and 0 <= value < 2**63


def assess_usage(
    usage: UsageReceipt,
    pricing: dict | None,
    *,
    reported_cost: Any = None,
    reported_currency: str = "USD",
    rate_source: str = "models_dev",
    snapshot_revision: str | None = None,
    calculated_at: str | None = None,
    context_tier_basis: str | None = None,
) -> CostAssessment:
    """Assess a supported rate schedule, or explain why the amount is unknown.

    Unsupported tier bases, audio billing, and nonstandard cache lifetimes
    deliberately stay unresolved until their billing semantics are supported.
    A reported amount is independent of whether usage or rates are available.
    """
    timestamp = calculated_at or datetime.now(UTC).isoformat()
    common = {
        "snapshot_revision": snapshot_revision,
        "usage": usage,
        "calculated_at": timestamp,
    }

    def unknown(reason: str) -> CostAssessment:
        return CostAssessment(None, "unknown", reason=reason, **common)

    reported = monetary_value(reported_cost)
    if reported is not None:
        if reported_currency != "USD":
            return unknown("unsupported_reported_currency")
        return CostAssessment(reported, "provider", **common)
    if pricing is None:
        return unknown("missing_pricing")
    if not isinstance(pricing, dict) or rate_source not in (
        "models_dev",
        "user_rate",
        "provider_rate",
    ):
        return unknown("invalid_pricing")
    if pricing.get("currency", "USD") != "USD":
        return unknown("unsupported_pricing_currency")
    if pricing.get("unit", "per_million_tokens") != "per_million_tokens":
        return unknown("unsupported_pricing_unit")
    selected_tier = None
    tiers = pricing.get("tiers")
    if tiers is None and "context_over_200k" in pricing:
        legacy = pricing["context_over_200k"]
        if not isinstance(legacy, dict):
            return unknown("invalid_pricing_tier")
        tiers = [{"tier": {"type": "context", "size": 200000}, **legacy}]
    if tiers:
        if context_tier_basis != "aggregate_input":
            return unknown("unsupported_context_tier_basis")
        if not _count(usage.input_tokens) or not isinstance(tiers, list):
            return unknown("missing_or_invalid_context_usage")
        threshold_prices = {}
        for entry in tiers:
            if not isinstance(entry, dict) or not isinstance(entry.get("tier"), dict):
                return unknown("invalid_pricing_tier")
            descriptor = entry["tier"]
            size = descriptor.get("size")
            if descriptor.get("type") != "context" or not _count(size) or size in threshold_prices:
                return unknown("unsupported_pricing_tier")
            threshold_prices[size] = entry
        if usage.input_tokens > 0 and usage.input_tokens in threshold_prices:
            return unknown("ambiguous_tier_boundary")
        applicable = [size for size in threshold_prices if size < usage.input_tokens or size == 0]
        if applicable:
            size = max(applicable)
            chosen = threshold_prices[size]
            quantities = {
                "cache_read": usage.cache_read_tokens,
                "cache_write": usage.cache_write_tokens,
                "reasoning": usage.reasoning_tokens,
            }
            for dimension, quantity in quantities.items():
                if dimension in pricing and dimension not in chosen and quantity != 0:
                    return unknown(f"missing_tier_{dimension}_rate")
            pricing = {key: value for key, value in chosen.items() if key != "tier"}
            selected_tier = {"type": "context", "size": size}
        else:
            pricing = {
                key: value
                for key, value in pricing.items()
                if key not in ("tiers", "context_over_200k")
            }
    elif "tiers" in pricing:
        if not isinstance(tiers, list):
            return unknown("invalid_pricing_tiers")
        pricing = {
            key: value
            for key, value in pricing.items()
            if key not in ("tiers", "context_over_200k")
        }
    if set(pricing) - _RATE_FIELDS - {"currency", "unit"}:
        return unknown("unsupported_pricing_dimension")

    rates = {key: monetary_value(pricing[key]) for key in _RATE_FIELDS if key in pricing}
    if (
        "input" not in rates
        or "output" not in rates
        or any(value is None for value in rates.values())
    ):
        return unknown("invalid_pricing")
    if not _count(usage.input_tokens) or not _count(usage.output_tokens):
        return unknown("missing_or_invalid_usage")
    for value in (
        usage.cache_read_tokens,
        usage.cache_write_tokens,
        usage.reasoning_tokens,
        usage.cache_write_1h_tokens,
        usage.audio_input_tokens,
        usage.audio_output_tokens,
    ):
        if value is not None and not _count(value):
            return unknown("invalid_usage_dimension")
    if (
        (usage.cache_write_1h_tokens is None and (usage.cache_write_tokens or 0) > 0)
        or (usage.cache_write_1h_tokens or 0) > 0
        or usage.audio_input_tokens is None
        or usage.audio_input_tokens > 0
        or usage.audio_output_tokens is None
        or usage.audio_output_tokens > 0
    ):
        return unknown("unsupported_usage_dimension")

    # When a schedule is uniform over aggregate input, a missing cache breakdown
    # cannot change the amount. Do not turn that into a reported zero counter.
    reads = usage.cache_read_tokens
    writes = usage.cache_write_tokens
    if reads is None:
        if "cache_read" in rates and rates["cache_read"] != rates["input"]:
            return unknown("missing_cache_read_usage")
        reads = 0
    if writes is None:
        if "cache_write" in rates and rates["cache_write"] != rates["input"]:
            return unknown("missing_cache_write_usage")
        writes = 0
    if reads and "cache_read" not in rates:
        return unknown("missing_cache_read_rate")
    if writes and "cache_write" not in rates:
        return unknown("missing_cache_write_rate")
    if reads + writes > usage.input_tokens:
        return unknown("cache_usage_exceeds_input")
    thinking = usage.reasoning_tokens
    if thinking is not None and thinking > usage.output_tokens:
        return unknown("reasoning_usage_exceeds_output")
    reasoning_rate = rates.get("reasoning", rates["output"])
    if reasoning_rate != rates["output"] and thinking is None:
        return unknown("missing_reasoning_usage")
    thinking = thinking or 0
    try:
        with localcontext() as context:
            context.prec = 90
            amount = (
                Decimal(usage.input_tokens - reads - writes) * rates["input"]
                + Decimal(reads) * rates.get("cache_read", rates["input"])
                + Decimal(writes) * rates.get("cache_write", rates["input"])
                + Decimal(usage.output_tokens - thinking) * rates["output"]
                + Decimal(thinking) * reasoning_rate
            ) / _MILLION
    except DecimalException:
        return unknown("unrepresentable_amount")
    if not amount.is_finite():
        return unknown("unrepresentable_amount")
    return CostAssessment(
        amount,
        rate_source,
        rates={key: str(value) for key, value in rates.items()},
        tier=selected_tier,
        **common,
    )
