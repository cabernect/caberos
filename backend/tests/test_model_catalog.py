"""Discovery/capability projection — observed catalog fields only."""

from agentos.providers.catalog_policy import project_model


def test_project_model_keeps_input_and_output_limits_separate():
    raw = {
        "limit": {"input": 922_000, "output": 128_000, "context": 1_050_000},
        "modalities": {"input": ["text", "image"], "output": ["text"]},
    }
    projected = project_model(raw)
    assert projected["max_context_tokens"] == 922_000
    assert projected["context_window_tokens"] == 1_050_000
    assert projected["max_output_tokens"] == 128_000
    assert projected["supports_vision"] is True


def test_project_model_never_invents_limits():
    projected = project_model({})
    assert projected["max_context_tokens"] is None
    assert projected["context_window_tokens"] is None
    assert projected["supports_vision"] is None
