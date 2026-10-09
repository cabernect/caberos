"""System-level model-call ledger writes — W10 accounting for provider
calls that don't belong to a run: validation probes, memory extraction,
session-title generation.

Single small async writer. Never raises into the caller's flow — a
bookkeeping failure is logged, not propagated (a probe must not fail
because its receipt couldn't be filed).
"""

import logging
from typing import Any

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


def response_cost(raw_response: Any, model_str: str | None) -> tuple[float, str]:
    """Exact cost recipe — returns (cost, source).

    1. Provider-reported ``cost`` (explicit 0 counts).
    2. LiteLLM ``_hidden_params.response_cost``.
    3. ``litellm.completion_cost`` — unknown pricing raises or returns
       None → (0.0, "unknown"). No pricing is ever invented.
    """
    value = _valid_cost(_get(raw_response, "cost"))
    if value is not None:
        return value, "provider"
    hidden = _get(raw_response, "_hidden_params") or {}
    value = _valid_cost(_get(hidden, "response_cost"))
    if value is not None:
        return value, "provider"
    try:
        import litellm

        cost = litellm.completion_cost(completion_response=raw_response, model=model_str)
        value = _valid_cost(cost)
        if value is None:
            return 0.0, "unknown"
        return value, "litellm"
    except Exception:
        return 0.0, "unknown"


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
