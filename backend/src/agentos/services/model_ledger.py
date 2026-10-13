"""System-level model-call ledger writes — W10 accounting for provider
calls that don't belong to a run: validation probes, memory extraction,
session-title generation.

Single small async writer. Never raises into the caller's flow — a
bookkeeping failure is logged, not propagated (a probe must not fail
because its receipt couldn't be filed).
"""

import logging
from typing import Any

from .call_accounting import CallRateSnapshot
from .cost_assessment import assess_usage
from .usage_receipts import normalize_usage, reported_amount

log = logging.getLogger(__name__)


def _get(obj: Any, key: str) -> Any:
    if isinstance(obj, dict):
        return obj.get(key)
    return getattr(obj, key, None)


def _valid_cost(value: Any) -> float | None:
    """Finite, non-negative floats only — NaN/inf/negative are treated
    as absent and fall through to the next source."""
    import math

    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) and f >= 0 else None


def response_cost(
    raw_response: Any,
    model_str: str | None,
    *,
    accounting: CallRateSnapshot | None = None,
    family: str = "chat",
    provider_type: str = "",
) -> tuple[float, str]:
    """Compatibility amount; the full assessment retains exact decimals.

    A routed model string is not a provider offering. Without a captured local
    rate authority only a genuine reported monetary amount can resolve cost.
    SDK-generated hidden costs are deliberately ignored.
    """
    if accounting is not None:
        assessment = accounting.assess(raw_response, family=family)
    else:
        amount, currency = reported_amount(raw_response, provider_type=provider_type)
        assessment = assess_usage(
            normalize_usage(raw_response, family=family, provider_type=provider_type),
            None,
            reported_cost=amount,
            reported_currency=currency,
        )
    return (
        float(assessment.amount) if assessment.amount is not None else 0.0,
        assessment.source,
    )


async def record_system_call(
    *,
    kind: str,
    purpose: str = "reasoning",
    provider_id: str | None = None,
    model_name: str | None = None,
    model_str: str | None = None,
    run_id: str | None = None,
    agent_id: str | None = None,
    sub_agent_id: str | None = None,
    response: Any = None,
    error: BaseException | None = None,
    latency_ms: int = 0,
    detail: dict | None = None,
) -> None:
    """Append a non-run ModelCall row. Failures are swallowed + logged.

    Token/cost fields come ONLY from the response object's attributes —
    never inferred. Error rows carry zero/None for unknowns and
    status='timeout' for TimeoutError else 'error'.
    """
    try:
        import asyncio

        from ..db import async_session_factory, retry_locked_transaction
        from ..models.model_call import ModelCall

        tokens_in = tokens_out = 0
        cached = thinking = None
        cost = 0.0
        status = "ok"
        error_text = None
        if error is not None:
            status = (
                "timeout" if isinstance(error, (TimeoutError, asyncio.TimeoutError)) else "error"
            )
            error_text = f"{type(error).__name__}: {error}"[:2000]
        if response is not None:
            tokens_in = response.tokens_in or 0
            tokens_out = response.tokens_out or 0
            cached = response.cached_tokens
            thinking = response.thinking_tokens
            cost = response.cost or 0.0
            if getattr(response, "cost_source", None) is not None:
                detail = {**(detail or {}), "cost_source": response.cost_source}
            receipt = getattr(response, "cost_receipt", None)
            if receipt:
                detail = {**(detail or {}), **receipt}

        row = ModelCall(
            run_id=run_id,
            agent_id=agent_id,
            sub_agent_id=sub_agent_id,
            kind=kind,
            purpose=purpose,
            provider_id=provider_id,
            model_name=model_name,
            model_str=model_str,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cached_tokens=cached,
            thinking_tokens=thinking,
            cost=cost,
            latency_ms=latency_ms,
            status=status,
            error=error_text,
            detail=detail,
        )
        async with async_session_factory() as session:

            async def _write():
                session.add(row)
                await session.commit()

            await retry_locked_transaction(
                _write,
                session,
                "record system model call",
            )
    except Exception:  # noqa: BLE001 — bookkeeping must not poison the flow
        log.debug("system model-call ledger write failed", exc_info=True)
