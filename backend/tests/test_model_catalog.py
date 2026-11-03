"""Discovery/capability projection — observed catalog fields only."""

from agentos.providers.catalog_policy import project_model
from agentos.providers.model_catalog import model_kind


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


def test_model_kind_media_by_reported_modality():
    # Endpoint says it outputs image — media regardless of the id shape.
    assert model_kind("openai/gpt-image-2", ["image"]) == "media"
    assert model_kind("openai/gpt-4o", ["text"]) == "chat"
    # Mixed output (e.g. image + text) still counts as media for pickers.
    assert model_kind("google/gemini-2.5-flash-image", ["text", "image"]) == "media"


def test_model_kind_falls_back_to_id_pattern_when_unreported():
    assert model_kind("gpt-image-1", None) == "media"
    assert model_kind("dall-e-3", None) == "media"
    assert model_kind("text-embedding-3-large", None) == "media"
    assert model_kind("tts-1", None) == "media"
    assert model_kind("gpt-4o", None) == "chat"
    assert model_kind("claude-sonnet-4-5", []) == "chat"
