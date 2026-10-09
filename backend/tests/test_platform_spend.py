"""Arithmetic and attribution regressions for the unified ledger."""

from datetime import UTC, datetime, timedelta

import pytest

from agentos.models.model_call import ModelCall
from agentos.models.run import Run
from agentos.services.observability_spend import platform_spend


@pytest.fixture
async def spend_ledger(db):
    now = datetime.now(UTC)
    db.add_all(
        [
            Run(id="live", session_id="s", contact_id="c", agent_id="a", is_test=False),
            Run(id="test", session_id="s", contact_id="c", agent_id="a", is_test=True),
        ]
    )
    await db.flush()
    for call_id, run, agent, provider, model, kind, cost, tin, tout, thinking, latency in (
        ("chat1", "live", "a", "p1", "m1", "chat", 1.0, 100, 30, 10, 20),
        ("chat2", "live", "a", "p2", "m2", "chat", 2.0, 200, 40, None, 30),
        ("embed", None, None, "p1", "m1", "embedding", 4.0, 400, 0, None, 40),
        ("probe", None, None, None, "m3", "probe", 8.0, 800, 1, 0, 50),
        ("testcall", "test", "a", "p1", "m1", "chat", 16.0, 1600, 60, 20, 60),
        ("old", None, None, "p1", "m1", "embedding", 32.0, 3200, 0, None, 70),
    ):
        db.add(
            ModelCall(
                id=call_id,
                run_id=run,
                agent_id=agent,
                provider_id=provider,
                model_name=model,
                kind=kind,
                purpose="embedding" if kind == "embedding" else "reasoning",
                cost=cost,
                tokens_in=tin,
                tokens_out=tout,
                thinking_tokens=thinking,
                latency_ms=latency,
                created_at=now - timedelta(days=10) if call_id == "old" else now,
            )
        )
    await db.commit()
    return db, now


async def test_platform_totals_and_all_breakdowns_reconcile(spend_ledger):
    db, now = spend_ledger
    result = await platform_spend(db, since=now - timedelta(days=1))
    assert result["total_cost"] == 15.0
    assert result["total_calls"] == 4
    assert result["total_runs"] == 1
    assert result["total_tokens_in"] == 1500
    assert result["total_tokens_out"] == 71
    assert result["thinking_tokens"] == 10  # Reported independently, not added to output.
    assert result["cached_tokens"] is None
    assert result["latency_ms"] == 140
    for key in ("by_kind", "by_provider", "by_model", "by_agent"):
        assert sum(row["total_cost"] for row in result[key]) == 15.0
        assert sum(row["call_count"] for row in result[key]) == 4
    assert {row["kind"]: row["total_cost"] for row in result["by_kind"]} == {
        "chat": 3.0,
        "embedding": 4.0,
        "probe": 8.0,
    }
    agents = {row["agent_id"]: row["total_cost"] for row in result["by_agent"]}
    assert agents == {None: 12.0, "a": 3.0}


async def test_platform_filters_select_calls_not_entire_runs(spend_ledger):
    db, now = spend_ledger
    result = await platform_spend(
        db, since=now - timedelta(days=1), agent_id="a", provider_id="p2", model="m2"
    )
    assert result["total_cost"] == 2.0
    assert result["total_calls"] == 1
    assert result["total_tokens_in"] == 200
    assert result["thinking_tokens"] is None
    result = await platform_spend(
        db, since=now - timedelta(days=1), kind="embedding", purpose="embedding"
    )
    assert result["total_cost"] == 4.0
    assert result["total_runs"] == 0
    assert result["thinking_tokens"] is None


async def test_platform_missing_usage_empty_and_exclusive_until(spend_ledger):
    db, now = spend_ledger
    result = await platform_spend(db, since=now - timedelta(days=1), kind="probe")
    assert result["thinking_tokens"] == 0
    result = await platform_spend(db, since=now - timedelta(days=1), until=now)
    assert result["total_cost"] == 0.0
    assert result["total_calls"] == 0
    assert result["by_kind"] == []
    assert result["thinking_tokens"] is None


async def test_platform_preserves_accounting_when_a_run_is_missing(db):
    now = datetime.now(UTC)
    db.add(
        ModelCall(
            id="historic",
            run_id="deleted-run",
            agent_id="former-agent",
            cost=0.5,
            tokens_in=20,
            tokens_out=5,
            created_at=now,
        )
    )
    await db.commit()
    result = await platform_spend(db, since=now - timedelta(days=1))
    assert result["total_cost"] == 0.5
    assert result["total_calls"] == 1
    assert result["by_agent"][0]["agent_id"] == "former-agent"


async def test_platform_price_and_thinking_coverage_preserve_reported_zero(db):
    now = datetime.now(UTC)
    for call_id, detail, cost, thinking, kind in (
        ("provider-zero", {"cost_source": "provider"}, 0.0, 0, "chat"),
        ("litellm-zero", {"cost_source": "litellm"}, 0.0, None, "embedding"),
        ("legacy-positive", None, 2.0, 2, "chat"),
        ("legacy-zero", None, 0.0, None, "chat"),
        ("unknown-zero", {"cost_source": "unknown"}, 0.0, None, "chat"),
        ("unclassified-zero", {"cost_source": "unrecognized"}, 0.0, None, "chat"),
    ):
        db.add(
            ModelCall(
                id=call_id,
                provider_id="p",
                model_name="m",
                kind=kind,
                cost=cost,
                detail=detail,
                thinking_tokens=thinking,
                tokens_in=10,
                tokens_out=5,
                created_at=now,
            )
        )
    await db.commit()
    result = await platform_spend(db, since=now - timedelta(days=1))
    assert result["total_calls"] == 6
    assert result["total_cost"] == 2.0
    assert result["priced_calls"] == 3
    assert result["unpriced_calls"] == 3
    assert result["thinking_tokens"] == 2
    assert result["thinking_reported_calls"] == 2
    assert result["total_tokens_out"] == 30
    for key in ("by_kind", "by_provider", "by_model", "by_agent"):
        assert sum(row["priced_calls"] for row in result[key]) == 3
        assert sum(row["unpriced_calls"] for row in result[key]) == 3
        assert sum(row["thinking_reported_calls"] for row in result[key]) == 2
    embedding = await platform_spend(db, since=now - timedelta(days=1), kind="embedding")
    assert embedding["priced_calls"] == 1
    assert embedding["unpriced_calls"] == 0
    assert embedding["thinking_tokens"] is None
    assert embedding["thinking_reported_calls"] == 0
    empty = await platform_spend(db, since=now + timedelta(seconds=1))
    assert empty["priced_calls"] == 0
    assert empty["unpriced_calls"] == 0
    assert empty["thinking_reported_calls"] == 0
