"""Normalize execution receipts without SDK-generated pricing or guessed usage."""

from typing import Any

from .cost_assessment import UsageReceipt, monetary_value


def _get(value: Any, key: str, default: Any = None) -> Any:
    if isinstance(value, dict):
        return value.get(key, default)
    return getattr(value, key, default) if value is not None else default


def _counter(value: Any) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool) and 0 <= value < 2**63:
        return value
    return None


def normalize_usage(
    raw: Any,
    *,
    family: str,
    provider_type: str = "",
    audio_input_used: bool = False,
) -> UsageReceipt:
    """Preserve absent counters; normalize native Anthropic input only once.

    The current execution paths send text/image inputs, not audio. An audio
    caller must explicitly attest that input dimension until it is supported.
    """
    if family not in ("chat", "responses", "embedding"):
        raise ValueError("unsupported usage receipt family")
    usage = _get(raw, "usage")
    is_responses = family == "responses"
    input_key = "input_tokens" if is_responses else "prompt_tokens"
    output_key = "output_tokens" if is_responses else "completion_tokens"
    inputs = _counter(_get(usage, input_key))
    outputs = _counter(_get(usage, output_key))
    details = _get(usage, "input_tokens_details" if is_responses else "prompt_tokens_details")
    output_details = _get(
        usage, "output_tokens_details" if is_responses else "completion_tokens_details"
    )
    reads = _counter(_get(details, "cached_tokens"))
    if reads is None:
        reads = _counter(_get(usage, "cached_tokens"))
    if reads is None:
        reads = _counter(_get(usage, "cache_read_input_tokens"))
    writes = _counter(_get(details, "cache_creation_tokens"))
    if writes is None:
        writes = _counter(_get(usage, "cache_creation_input_tokens"))
    if writes is None and provider_type in ("openai", "google", "gemini", "openrouter"):
        writes = 0

    # The SDK's Anthropic prompt_tokens already includes both cache components.
    # Native Anthropic input_tokens excludes them; absent native cache fields
    # denote no cache use, unlike an absent aggregate usage receipt.
    if provider_type == "anthropic" and inputs is None:
        native = _counter(_get(usage, "input_tokens"))
        if native is not None:
            if _get(usage, "cache_read_input_tokens") is None:
                reads = 0
            if _get(usage, "cache_creation_input_tokens") is None:
                writes = 0
            if reads is not None and writes is not None:
                inputs = native + reads + writes
            outputs = _counter(_get(usage, "output_tokens"))

    if family == "embedding":
        if inputs is None:
            inputs = _counter(_get(usage, "total_tokens"))
        outputs = 0  # Embedding vectors are not generated text-token output.
    reasoning = _counter(_get(output_details, "reasoning_tokens"))
    if reasoning is None:
        reasoning = _counter(_get(usage, "reasoning_tokens"))
    if provider_type == "anthropic":
        # The installed SDK estimates this detail from reasoning text; do not
        # turn that tokenizer estimate into provider-reported usage.
        reasoning = None

    creation = _get(details, "cache_creation_token_details")
    if creation is None:
        creation = _get(usage, "cache_creation")
    hour_writes = _counter(_get(creation, "ephemeral_1h_input_tokens"))
    if writes == 0:
        hour_writes = 0
    elif hour_writes is None:
        five_minute_writes = _counter(_get(creation, "ephemeral_5m_input_tokens"))
        if writes is not None and five_minute_writes == writes:
            hour_writes = 0
    audio_input = _counter(_get(details, "audio_tokens"))
    audio_output = _counter(_get(output_details, "audio_tokens"))
    if audio_input is None and not audio_input_used:
        audio_input = 0
    if audio_output is None:
        choices = _get(raw, "choices", []) or []
        audio_present = _get(_get(raw, "message"), "audio") is not None or any(
            _get(_get(choice, "message"), "audio") is not None for choice in choices
        )
        if not audio_present:
            audio_output = 0
    return UsageReceipt(
        input_tokens=inputs,
        output_tokens=outputs,
        cache_read_tokens=reads,
        cache_write_tokens=writes,
        reasoning_tokens=reasoning,
        cache_write_1h_tokens=hour_writes,
        audio_input_tokens=audio_input,
        audio_output_tokens=audio_output,
    )


def reported_amount(raw: Any, *, provider_type: str = "") -> tuple[Any, str]:
    """Native monetary fields only; _hidden_params.response_cost is not billing."""
    value = _get(raw, "cost")
    currency = _get(raw, "cost_currency") or _get(raw, "currency") or "USD"
    if isinstance(value, dict):
        currency = value.get("currency") or currency
        value = value.get("amount")
    amount = monetary_value(value)
    if amount is None and provider_type == "openrouter":
        amount = monetary_value(_get(_get(raw, "usage"), "cost"))
    return amount, currency.upper() if isinstance(currency, str) else "unknown"
