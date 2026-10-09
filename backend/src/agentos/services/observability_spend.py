"""Platform spend reads the call ledger, never estimates from run totals."""

from datetime import datetime

from sqlalchemy import case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.model_call import ModelCall
from ..models.run import Run


async def platform_spend(
    db: AsyncSession,
    *,
    since: datetime,
    until: datetime | None = None,
    agent_id: str | None = None,
    provider_id: str | None = None,
    model: str | None = None,
    purpose: str | None = None,
    kind: str | None = None,
) -> dict:
    """Aggregate ledger values without estimating missing prices or token usage."""
    filters = [
        ModelCall.created_at >= since,
        or_(Run.id.is_(None), Run.is_test.is_(False)),
    ]
    if until is not None:
        filters.append(ModelCall.created_at < until)
    for column, value in (
        (ModelCall.agent_id, agent_id),
        (ModelCall.provider_id, provider_id),
        (ModelCall.model_name, model),
        (ModelCall.purpose, purpose),
        (ModelCall.kind, kind),
    ):
        if value is not None:
            filters.append(column == value)
    cost_source = ModelCall.detail["cost_source"].as_string()
    # Legacy zeroes have no pricing provenance. Positive legacy costs retain
    # their recorded value; an explicitly unknown source remains unpriced.
    priced = case(
        (cost_source == "unknown", 0),
        (cost_source.in_(("provider", "litellm")), 1),
        (ModelCall.cost > 0, 1),
        else_=0,
    )
    calls = (
        select(
            ModelCall.id,
            ModelCall.run_id,
            ModelCall.agent_id,
            ModelCall.provider_id,
            ModelCall.model_name,
            ModelCall.kind,
            ModelCall.tokens_in,
            ModelCall.tokens_out,
            ModelCall.thinking_tokens,
            ModelCall.cached_tokens,
            ModelCall.cost,
            ModelCall.latency_ms,
            priced.label("priced"),
        )
        .outerjoin(Run, ModelCall.run_id == Run.id)
        .where(*filters)
        .subquery()
    )
    aggregates = (
        func.coalesce(func.sum(calls.c.cost), 0.0).label("total_cost"),
        func.count(calls.c.id).label("call_count"),
        func.count(func.distinct(calls.c.run_id)).label("run_count"),
        func.coalesce(func.sum(calls.c.tokens_in), 0).label("tokens_in"),
        func.coalesce(func.sum(calls.c.tokens_out), 0).label("tokens_out"),
        func.sum(calls.c.thinking_tokens).label("thinking_tokens"),
        func.sum(calls.c.cached_tokens).label("cached_tokens"),
        func.coalesce(func.sum(calls.c.latency_ms), 0).label("latency_ms"),
        func.coalesce(func.sum(calls.c.priced), 0).label("priced_calls"),
        func.count(calls.c.thinking_tokens).label("thinking_reported_calls"),
    )
    total = dict((await db.execute(select(*aggregates))).mappings().one())

    async def breakdown(*columns) -> list[dict]:
        rows = await db.execute(select(*columns, *aggregates).group_by(*columns).order_by(*columns))
        result = []
        for row in rows.mappings():
            item = dict(row)
            item["unpriced_calls"] = item["call_count"] - item["priced_calls"]
            result.append(item)
        return result

    return {
        "scope": "platform",
        "since": since.isoformat(),
        "until": until.isoformat() if until is not None else None,
        "total_cost": total["total_cost"],
        "total_calls": total["call_count"],
        "total_runs": total["run_count"],
        "total_tokens_in": total["tokens_in"],
        "total_tokens_out": total["tokens_out"],
        "thinking_tokens": total["thinking_tokens"],
        "cached_tokens": total["cached_tokens"],
        "latency_ms": total["latency_ms"],
        "priced_calls": total["priced_calls"],
        "unpriced_calls": total["call_count"] - total["priced_calls"],
        "thinking_reported_calls": total["thinking_reported_calls"],
        "by_kind": await breakdown(calls.c.kind),
        "by_provider": await breakdown(calls.c.provider_id),
        "by_model": await breakdown(calls.c.provider_id, calls.c.model_name),
        # A null agent bucket is explicit: unattributed work is not hidden.
        "by_agent": await breakdown(calls.c.agent_id),
    }
