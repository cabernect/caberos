"""Offering identity and field-authority rules, independent of persistence."""

from agentos.providers.catalog_policy import (
    catalog_identity,
    project_model,
    resolve_fields,
    validate_overrides,
)


def test_proxy_requires_an_explicit_offering_mapping():
    assert catalog_identity("openai", "model", "https://proxy.example/v1") is None
    assert catalog_identity("openai", "model") == ("openai", "model")
    assert catalog_identity("openai", "model", "https://api.openai.com.evil/v1") is None
    assert catalog_identity(
        "openai",
        "my-alias",
        "https://proxy.example/v1",
        catalog_provider_id="openrouter",
        catalog_model_id="openai/model",
    ) == ("openrouter", "openai/model")
    # Transferred from the retired helper tests — no heuristic fallback:
    # a custom provider without an explicit mapping stays unknown.
    assert catalog_identity("custom", "gpt-6", "https://proxy.local") is None
    assert catalog_identity("openai", "gpt-6", "http://proxy.local") is None
    # Only the model id without a provider id is not a mapping.
    assert catalog_identity("openai", "x", catalog_model_id="gpt-6") is None
    # Explicit mapping beats inference, exact model id preserved.
    assert catalog_identity(
        "custom",
        "my-model",
        "https://x.local",
        catalog_provider_id="openai",
        catalog_model_id="gpt-6",
    ) == ("openai", "gpt-6")


def test_total_context_is_not_a_claim_about_input_capacity():
    fields = project_model(
        {
            "limit": {"context": 100_000, "output": 8_000},
            "reasoning": True,
            "modalities": {"input": ["text", "image"], "output": ["text"]},
            "reasoning_options": [{"type": "budget_tokens", "min": 1024}],
        }
    )
    assert fields["max_context_tokens"] is None
    assert fields["context_window_tokens"] == 100_000
    assert fields["max_output_tokens"] == 8_000
    assert fields["supports_vision"] is True
    assert fields["thinking_efforts"] == []


def test_false_override_wins_and_each_authority_keeps_its_own_time():
    resolved = resolve_fields(
        {
            "reasoning": True,
            "limit": {"context": 100_000, "input": 64_000},
            "modalities": {"input": ["text", "image"]},
        },
        observed={"context_window_tokens": 80_000},
        overrides={"supports_thinking": False, "supports_vision": False},
        as_of="2026-10-09T00:00:00Z",
        observed_as_of="2026-10-09T01:00:00Z",
        override_as_of="2026-10-09T02:00:00Z",
    )
    # Both overrides win — catalog/observed values never resurrect a true.
    assert resolved["supports_thinking"] is False
    assert resolved["supports_vision"] is False
    assert resolved["provenance"]["supports_thinking"]["source"] == "user_override"
    assert resolved["provenance"]["supports_vision"]["source"] == "user_override"
    assert resolved["provenance"]["supports_thinking"]["as_of"] == "2026-10-09T02:00:00Z"
    # Fields without an override keep their own authority + time.
    assert resolved["context_window_tokens"] == 80_000
    assert resolved["provenance"]["context_window_tokens"]["source"] == "provider"
    assert resolved["provenance"]["context_window_tokens"]["as_of"] == "2026-10-09T01:00:00Z"
    # A catalog-only field (input limit → max_context_tokens) survives
    # with models_dev provenance — the "unchanged fields fall through"
    # case the retired test covered.
    assert resolved["max_context_tokens"] == 64_000
    assert resolved["provenance"]["max_context_tokens"]["source"] == "models_dev"


def test_unknown_metadata_is_not_a_200k_model():
    resolved = resolve_fields(None)
    assert resolved["max_context_tokens"] is None
    assert resolved["context_window_tokens"] is None
    assert resolved["supports_vision"] is False  # legacy bool fails closed
    assert resolved["provenance"]["max_context_tokens"]["source"] == "unknown"
    assert resolved["provenance"]["supports_vision"]["value"] is None
    assert resolved["provenance"]["supports_vision"]["source"] == "unknown"
    assert resolved["pricing"] is None


def test_invalid_override_is_rejected_not_coerced_to_a_fact():
    import pytest

    for fields in ({"max_context_tokens": True}, {"supports_vision": "yes"}, {"name": "alias"}):
        with pytest.raises(ValueError):
            validate_overrides(fields)


def test_unknown_runtime_budget_is_policy_not_a_claimed_model_limit():
    from agentos.providers.catalog_policy import resolve_input_budget

    metadata = resolve_fields(None)
    budget = resolve_input_budget(metadata)
    assert budget["tokens"] == 32768
    assert budget["source"] == "application_fallback"
    assert budget["model_limit_known"] is False
    assert metadata["max_context_tokens"] is None


def test_context_allocation_reserves_output_without_inventing_input_capacity():
    from agentos.providers.catalog_policy import resolve_input_budget

    metadata = {"context_window_tokens": 16000, "max_output_tokens": 4000}
    budget = resolve_input_budget(metadata)
    assert budget["tokens"] == 12000
    assert budget["source"] == "derived_context_budget"
    assert "max_context_tokens" not in metadata


def test_run_ceiling_caps_explicit_model_budget():
    from agentos.providers.catalog_policy import resolve_input_budget

    budget = resolve_input_budget(
        {"max_context_tokens": 12000}, model_override=20000, run_override=8000
    )
    assert budget["tokens"] == 8000
    assert budget["source"] == "user_run_budget"
