"""Independent arithmetic examples for versioned call-cost assessments."""

from decimal import Decimal

from agentos.services.cost_assessment import UsageReceipt, assess_usage


def test_cache_reads_replace_full_input_charges():
    assessment = assess_usage(
        UsageReceipt(1000, 500, cache_read_tokens=200, cache_write_tokens=0),
        {"input": "2", "output": "10", "cache_read": "0.5"},
        snapshot_revision="fixture-v1",
    )
    assert assessment.amount == Decimal("0.0067")
    assert assessment.source == "models_dev"
    assert assessment.snapshot_revision == "fixture-v1"


def test_cache_creation_is_not_charged_as_ordinary_input_too():
    assessment = assess_usage(
        UsageReceipt(3000, 400, cache_read_tokens=1000, cache_write_tokens=500),
        {"input": "3", "output": "15", "cache_read": "0.3", "cache_write": "3.75"},
    )
    assert assessment.amount == Decimal("0.012675")


def test_reasoning_is_already_inside_output_total():
    usage = UsageReceipt(1000, 500, reasoning_tokens=200)
    assessment = assess_usage(usage, {"input": "2", "output": "10", "reasoning": "12"})
    assert assessment.amount == Decimal("0.0074")
    same_rate = assess_usage(usage, {"input": "2", "output": "10", "reasoning": "10"})
    assert same_rate.amount == Decimal("0.007")


def test_reported_zero_does_not_need_usage_or_a_price():
    assessment = assess_usage(UsageReceipt(None, None), None, reported_cost="0")
    assert assessment.amount == Decimal("0")
    assert assessment.source == "provider"


def test_unknown_or_invalid_usage_does_not_become_free():
    for usage in (
        UsageReceipt(None, 2),
        UsageReceipt(10, None),
        UsageReceipt(True, 2),
        UsageReceipt(10, 2, cache_read_tokens=11),
        UsageReceipt(10, 2, reasoning_tokens=3),
    ):
        assessment = assess_usage(usage, {"input": "2", "output": "10"})
        assert assessment.amount is None
        assert assessment.source == "unknown"


def test_unknown_discounted_cache_usage_is_unresolved():
    assessment = assess_usage(
        UsageReceipt(1000, 500),
        {"input": "2", "output": "10", "cache_read": "0.5"},
    )
    assert assessment.amount is None
    assert assessment.reason == "missing_cache_read_usage"


def test_unknown_pricing_dimensions_are_not_silently_ignored():
    for extra in (
        {"per_request": "0.5"},
        {"input_audio": "2"},
        {"tiers": [{"tier": {"size": 200000}}]},
    ):
        assessment = assess_usage(UsageReceipt(10, 2), {"input": "2", "output": "10", **extra})
        assert assessment.amount is None
        assert assessment.source == "unknown"


def test_decimal_rates_and_user_rate_source_are_preserved():
    assessment = assess_usage(
        UsageReceipt(1, 1),
        {"input": "0.1", "output": "0.2"},
        rate_source="user_rate",
    )
    assert assessment.amount == Decimal("0.0000003")
    assert assessment.source == "user_rate"
    assert assessment.to_dict()["amount"] == "0.0000003"


def test_nonfinite_or_negative_rates_and_reported_costs_are_not_money():
    for rate in ("NaN", "Infinity", "-1", True):
        assessment = assess_usage(UsageReceipt(1, 1), {"input": rate, "output": "0"})
        assert assessment.amount is None
    for cost in ("NaN", "Infinity", "-1", True):
        assessment = assess_usage(UsageReceipt(None, None), None, reported_cost=cost)
        assert assessment.amount is None


def test_declared_context_tiers_use_total_input_without_double_counting():
    pricing = {
        "input": "2.5",
        "output": "15",
        "tiers": [
            {"tier": {"type": "context", "size": 200000}, "input": "5", "output": "22.5"},
            {"tier": {"type": "context", "size": 500000}, "input": "7", "output": "30"},
        ],
    }
    kwargs = {"context_tier_basis": "aggregate_input"}
    below = assess_usage(UsageReceipt(199999, 1000), pricing, **kwargs)
    above = assess_usage(UsageReceipt(200001, 1000), pricing, **kwargs)
    highest = assess_usage(UsageReceipt(500001, 1000), pricing, **kwargs)
    assert below.amount == Decimal("0.5149975")
    assert above.amount == Decimal("1.022505")
    assert highest.amount == Decimal("3.530007")
    assert above.to_dict()["tier"] == {"type": "context", "size": 200000}
    # The upstream threshold does not specify equality semantics. Do not
    # invent a provider charge at that boundary.
    boundary = assess_usage(UsageReceipt(200000, 1000), pricing, **kwargs)
    assert boundary.amount is None and boundary.reason == "ambiguous_tier_boundary"
    unspecified_basis = assess_usage(UsageReceipt(200001, 1000), pricing)
    assert unspecified_basis.amount is None
