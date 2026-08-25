from agentos.providers.model_catalog import _context_window


def test_context_window_is_separate_from_input_and_output_limits():
    info = {"max_input_tokens": 922_000, "max_output_tokens": 128_000}

    assert _context_window(info) == 1_050_000
