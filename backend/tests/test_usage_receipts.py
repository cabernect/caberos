"""Usage semantics at the execution/assessment seam."""

from agentos.services.usage_receipts import normalize_usage, reported_amount


def test_chat_counters_are_aggregate_not_recharged_components():
    usage = normalize_usage(
        {
            "usage": {
                "prompt_tokens": 1000,
                "completion_tokens": 500,
                "prompt_tokens_details": {"cached_tokens": 200},
                "completion_tokens_details": {"reasoning_tokens": 40},
            }
        },
        family="chat",
        provider_type="openai",
    )
    assert usage.input_tokens == 1000
    assert usage.output_tokens == 500
    assert usage.cache_read_tokens == 200
    assert usage.cache_write_tokens == 0
    assert usage.reasoning_tokens == 40


def test_missing_counters_remain_unknown_and_explicit_zero_survives():
    missing = normalize_usage({"usage": {}}, family="responses", provider_type="openai")
    assert missing.input_tokens is None and missing.output_tokens is None
    assert missing.cache_read_tokens is None
    zero = normalize_usage(
        {
            "usage": {
                "input_tokens": 0,
                "output_tokens": 0,
                "input_tokens_details": {"cached_tokens": 0},
            }
        },
        family="responses",
        provider_type="openai",
    )
    assert zero.input_tokens == zero.output_tokens == zero.cache_read_tokens == 0


def test_litellm_anthropic_prompt_already_includes_cache():
    usage = normalize_usage(
        {
            "usage": {
                "prompt_tokens": 3000,
                "completion_tokens": 400,
                "cache_creation_input_tokens": 500,
                "cache_read_input_tokens": 1000,
                "prompt_tokens_details": {
                    "cached_tokens": 1000,
                    "cache_creation_tokens": 500,
                    "cache_creation_token_details": {
                        "ephemeral_5m_input_tokens": 500,
                        "ephemeral_1h_input_tokens": 0,
                    },
                },
                "completion_tokens_details": {"reasoning_tokens": 50},
            }
        },
        family="chat",
        provider_type="anthropic",
    )
    assert usage.input_tokens == 3000
    assert usage.cache_read_tokens == 1000 and usage.cache_write_tokens == 500
    assert usage.cache_write_1h_tokens == 0
    # The SDK synthesizes this Anthropic detail; it is not a reported fact.
    assert usage.reasoning_tokens is None


def test_native_anthropic_uncached_input_is_normalized_once():
    usage = normalize_usage(
        {
            "usage": {
                "input_tokens": 1500,
                "output_tokens": 400,
                "cache_creation_input_tokens": 500,
                "cache_read_input_tokens": 1000,
            }
        },
        family="chat",
        provider_type="anthropic",
    )
    assert usage.input_tokens == 3000
    assert usage.cache_write_1h_tokens is None


def test_hidden_sdk_cost_is_not_reported_billing():
    amount, currency = reported_amount({"_hidden_params": {"response_cost": 3}})
    assert amount is None and currency == "USD"
    amount, currency = reported_amount({"cost": 0})
    assert amount == 0 and currency == "USD"


def test_openrouter_usage_cost_is_preserved_without_inventing_a_price():
    amount, currency = reported_amount({"usage": {"cost": "0.0123"}}, provider_type="openrouter")
    assert str(amount) == "0.0123" and currency == "USD"
    ignored, _ = reported_amount({"usage": {"cost": "0.0123"}}, provider_type="openai")
    assert ignored is None


def test_embedding_has_no_generated_output_dimension():
    usage = normalize_usage(
        {"usage": {"prompt_tokens": 250}}, family="embedding", provider_type="openai"
    )
    assert usage.input_tokens == 250 and usage.output_tokens == 0


def test_malformed_usage_is_not_coerced_into_a_counter():
    usage = normalize_usage(
        {"usage": {"prompt_tokens": True, "completion_tokens": "123"}},
        family="chat",
        provider_type="openai",
    )
    assert usage.input_tokens is None and usage.output_tokens is None
