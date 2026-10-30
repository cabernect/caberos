import json

import pytest

from agentos.redaction import bound_payload, project_args, project_result

CANARY = "sk-ant-api03-abcdefghijklmnopqrstuvwxyz0123456789ABCDEFGHIJ"


@pytest.mark.parametrize("results", [42, True, "wrong shape", {"text": "private"}])
def test_malformed_search_results_are_not_exposed(results):
    projected, _, _ = project_result("doc_search", {"results": results})
    assert projected["results"] == []
    assert projected["count"] == 0


@pytest.mark.parametrize("args", [f"cookies={CANARY}", [CANARY], 42])
def test_malformed_browser_args_fail_closed(args):
    projected, redacted, _ = project_args("browser_act", args)
    assert projected is None
    assert redacted


def test_secret_in_trace_label_is_redacted_before_truncation():
    secret = "sk-proj-" + "a" * 150
    projected, _, _ = project_result("doc_search", {"trace": {"fusion": secret}, "results": []})
    assert projected["trace"]["fusion"] == "[REDACTED]"


def test_nested_secret_flags_and_nullable_token_counts():
    projected, redacted, truncated = bound_payload(
        {
            "nested": [{"password": 123456, "value": CANARY}],
            "thinking_tokens": None,
            "cached_tokens": 0,
        }
    )
    assert redacted
    assert not truncated
    assert projected["thinking_tokens"] is None
    assert projected["cached_tokens"] == 0
    assert "password" not in json.dumps(projected)
    assert CANARY not in json.dumps(projected)


@pytest.mark.parametrize("capability", ["read_terminal", "close_terminal"])
def test_malformed_terminal_result_is_not_raw_output(capability):
    projected, redacted, _ = project_result(capability, "private console contents")
    assert projected is None
    assert redacted
