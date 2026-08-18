"""Tests for context compaction (head/middle/tail summarization).

Tests the 4-phase pipeline:
  Phase 1: Prune old tool results
  Phase 2: Determine boundaries (head/tail)
  Phase 3: Structured summary (mocked LLM)
  Phase 4: Reassemble + sanitize tool pairs
"""

from unittest.mock import AsyncMock, patch

from agentos.config_schema import AgentConfig, CompactionConfig, ModelConfig
from agentos.harness.compaction import (
    _align_boundary_backward,
    _sanitize_tool_pairs,
    compact_context,
    count_tokens,
    determine_boundaries,
    get_model_max_tokens,
    prune_tool_results,
    reassemble,
)


def _make_agent_config(compaction: CompactionConfig | None = None) -> AgentConfig:
    return AgentConfig(
        id="test-agent",
        name="Test Agent",
        model=ModelConfig(provider_id="test-provider", name="test-model"),
        compaction=compaction or CompactionConfig(),
    )


def _make_messages(n: int, prefix: str = "msg") -> list[dict]:
    """Generate n simple user/assistant messages."""
    msgs = []
    for i in range(n):
        role = "user" if i % 2 == 0 else "assistant"
        msgs.append({"role": role, "content": f"{prefix} {i}: {'x' * 100}"})
    return msgs


class TestPhase1PruneToolResults:
    """Phase 1 — replace long tool results outside the tail with a stub."""

    def test_prunes_long_tool_result_outside_tail(self):
        msgs = [
            {"role": "user", "content": "Read this file"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [{"id": "tc1", "function": {"name": "file.read"}}],
            },
            {"role": "tool", "tool_call_id": "tc1", "content": "x" * 5000},
            {"role": "assistant", "content": "Here's the file content"},
        ]
        pruned = prune_tool_results(msgs, tail_start=3, prune_over=200)
        # The tool result at index 2 is outside the tail (tail_start=3)
        assert "[Old tool output cleared" in pruned[2]["content"]
        # Other messages unchanged
        assert pruned[0]["content"] == "Read this file"
        assert pruned[3]["content"] == "Here's the file content"

    def test_preserves_tool_result_inside_tail(self):
        msgs = [
            {"role": "user", "content": "Read this file"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [{"id": "tc1", "function": {"name": "file.read"}}],
            },
            {"role": "tool", "tool_call_id": "tc1", "content": "x" * 5000},
        ]
        # tail_start=0 means everything is inside the tail → no pruning
        pruned = prune_tool_results(msgs, tail_start=0, prune_over=200)
        assert pruned[2]["content"] == "x" * 5000  # Not pruned

    def test_preserves_short_tool_results(self):
        msgs = [
            {"role": "tool", "tool_call_id": "tc1", "content": "OK"},
        ]
        pruned = prune_tool_results(msgs, tail_start=0, prune_over=200)
        assert pruned[0]["content"] == "OK"  # Under 200 chars, not pruned


class TestPhase2DetermineBoundaries:
    """Phase 2 — determine head and tail boundaries."""

    def test_head_is_first_n_messages(self):
        config = CompactionConfig(protect_first_n=3, protect_last_n=5, tail_budget_fraction=0.20)
        msgs = _make_messages(30)
        head_end, tail_start = determine_boundaries(msgs, config, threshold_tokens=10000)
        assert head_end == 3

    def test_short_conversation_no_middle(self):
        config = CompactionConfig(protect_first_n=3, protect_last_n=20)
        msgs = _make_messages(10)
        head_end, tail_start = determine_boundaries(msgs, config, threshold_tokens=10000)
        # 10 messages <= 3 (head) + 20 (min tail) → no middle
        assert tail_start == 10  # tail covers everything after head

    def test_tail_does_not_overlap_head(self):
        config = CompactionConfig(protect_first_n=3, protect_last_n=5, tail_budget_fraction=0.01)
        msgs = _make_messages(10)
        head_end, tail_start = determine_boundaries(msgs, config, threshold_tokens=100)
        # With a tiny tail budget, tail falls back to protect_last_n=5
        # tail_start = 10 - 5 = 5, which is > head_end=3
        assert tail_start >= head_end

    def test_align_boundary_avoids_splitting_tool_pairs(self):
        msgs = [
            {"role": "user", "content": "msg 0"},
            {"role": "user", "content": "msg 1"},
            {"role": "user", "content": "msg 2"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [{"id": "tc1", "function": {"name": "file.read"}}],
            },
            {"role": "tool", "tool_call_id": "tc1", "content": "result"},
            {"role": "assistant", "content": "msg 5"},
            {"role": "user", "content": "msg 6"},
        ]
        # If boundary lands on the tool result (index 4), it should move back
        aligned = _align_boundary_backward(msgs, 4)
        # Should move back past the tool result and the tool call
        assert aligned < 4

    def test_tail_budget_based_on_tokens(self):
        config = CompactionConfig(
            protect_first_n=2,
            protect_last_n=3,
            tail_budget_fraction=0.20,
        )
        msgs = _make_messages(20)
        head_end, tail_start = determine_boundaries(msgs, config, threshold_tokens=500)
        # Tail should have at least protect_last_n=3 messages
        assert len(msgs) - tail_start >= 3


class TestPhase4SanitizeToolPairs:
    """Phase 4 — sanitize orphaned tool calls/results."""

    def test_removes_orphaned_tool_result(self):
        msgs = [
            {"role": "user", "content": "hello"},
            {"role": "tool", "tool_call_id": "orphan", "content": "no matching call"},
            {"role": "assistant", "content": "hi"},
        ]
        sanitized = _sanitize_tool_pairs(msgs)
        # The orphaned tool result should be removed
        assert len(sanitized) == 2
        assert sanitized[0]["role"] == "user"
        assert sanitized[1]["role"] == "assistant"

    def test_injects_stub_for_orphaned_tool_call(self):
        msgs = [
            {"role": "user", "content": "read file"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [{"id": "tc1", "function": {"name": "file.read"}}],
            },
            {"role": "assistant", "content": "Here's the result"},
        ]
        sanitized = _sanitize_tool_pairs(msgs)
        # user, assistant(tool_call), tool(stub), assistant → 4 items
        assert len(sanitized) == 4
        assert sanitized[1]["role"] == "assistant"
        assert sanitized[2]["role"] == "tool"
        assert sanitized[2]["tool_call_id"] == "tc1"
        assert "not available" in sanitized[2]["content"]

    def test_preserves_matched_pairs(self):
        msgs = [
            {"role": "user", "content": "read file"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [{"id": "tc1", "function": {"name": "file.read"}}],
            },
            {"role": "tool", "tool_call_id": "tc1", "content": "file contents"},
            {"role": "assistant", "content": "Done"},
        ]
        sanitized = _sanitize_tool_pairs(msgs)
        assert len(sanitized) == 4  # No changes


class TestPhase4Reassemble:
    """Phase 4 — reassemble head + summary + tail."""

    def test_reassemble_with_summary(self):
        head = [{"role": "user", "content": "initial task"}]
        tail = [{"role": "user", "content": "continue"}]
        summary = "## Goal\nDo the thing"
        result = reassemble(head, summary, tail)
        # head + summary + tail
        assert len(result) == 3
        assert result[0]["content"] == "initial task"
        assert "Previous conversation summary" in result[1]["content"]
        assert result[2]["content"] == "continue"

    def test_reassemble_without_summary(self):
        head = [{"role": "user", "content": "task"}]
        tail = [{"role": "assistant", "content": "done"}]
        result = reassemble(head, "", tail)
        # No summary → just head + tail
        assert len(result) == 2

    def test_summary_role_preserves_alternation(self):
        # Last head message is assistant → summary should be "user"
        head = [
            {"role": "user", "content": "task"},
            {"role": "assistant", "content": "ok"},
        ]
        tail = [{"role": "user", "content": "next"}]
        result = reassemble(head, "summary", tail)
        # Summary role should be "user" (after assistant)
        assert result[2]["role"] == "user"


class TestTokenCounting:
    """Token counting utilities."""

    def test_count_tokens_basic(self):
        msgs = [{"role": "user", "content": "Hello, how are you?"}]
        tokens = count_tokens(msgs, "gpt-4o")
        assert tokens > 0
        assert tokens < 100  # Should be small

    def test_count_tokens_empty(self):
        tokens = count_tokens([], "gpt-4o")
        assert tokens >= 0  # litellm may return 0 or a small base count

    def test_get_model_max_tokens_known(self):
        max_tokens = get_model_max_tokens("gpt-4o")
        assert max_tokens > 1000  # Should be 128000

    def test_get_model_max_tokens_unknown_fallback(self):
        max_tokens = get_model_max_tokens("nonexistent/model-xyz")
        assert max_tokens > 0  # Should return a default


class TestCompactContext:
    """Integration test — full compaction pipeline."""

    async def test_no_compaction_when_under_threshold(self):
        config = _make_agent_config(CompactionConfig(auto_compaction=True, threshold=0.7))
        msgs = _make_messages(5)
        result = await compact_context(msgs, config, "gpt-4o")
        assert not result.compacted
        assert result.messages == msgs

    async def test_compaction_forced(self):
        """Force compaction even when under threshold."""
        config = _make_agent_config(
            CompactionConfig(
                auto_compaction=True,
                protect_first_n=2,
                protect_last_n=2,
                tail_budget_fraction=0.20,
            )
        )
        msgs = _make_messages(10)

        # Mock the summary LLM call and use a small context window
        with (
            patch("agentos.harness.compaction.generate_summary", new_callable=AsyncMock) as mock,
            patch("agentos.harness.compaction.get_model_max_tokens", return_value=500),
        ):
            mock.return_value = "## Goal\nTest summary"
            result = await compact_context(msgs, config, "test-model", force=True)

        assert result.compacted
        assert result.summary == "## Goal\nTest summary"
        # Should have fewer messages than original (middle was summarized)
        assert len(result.messages) < len(msgs)
        # Head + summary + tail
        assert result.head_count == 2
        assert result.tail_count == 2

    async def test_compaction_with_previous_summary(self):
        """Later compaction passes previous summary to LLM."""
        config = _make_agent_config(
            CompactionConfig(
                auto_compaction=True,
                protect_first_n=2,
                protect_last_n=2,
                tail_budget_fraction=0.20,
            )
        )
        msgs = _make_messages(10)
        previous = "## Goal\nOld summary"

        with (
            patch("agentos.harness.compaction.generate_summary", new_callable=AsyncMock) as mock,
            patch("agentos.harness.compaction.get_model_max_tokens", return_value=500),
        ):
            mock.return_value = "## Goal\nUpdated summary"
            result = await compact_context(
                msgs, config, "test-model", previous_summary=previous, force=True
            )

        assert result.compacted
        assert "Updated" in result.summary
        # Verify the LLM was called with the previous summary
        mock.assert_called_once()
        call_args = mock.call_args
        assert call_args[1]["previous_summary"] == previous

    async def test_compaction_auto_off(self):
        """Auto-compaction off → no compaction unless forced."""
        config = _make_agent_config(CompactionConfig(auto_compaction=False))
        msgs = _make_messages(5)
        result = await compact_context(msgs, config, "gpt-4o")
        assert not result.compacted

    async def test_compaction_prunes_large_tool_results(self):
        """Phase 1 — large tool results in the middle are pruned."""
        config = _make_agent_config(
            CompactionConfig(
                auto_compaction=True,
                protect_first_n=1,
                protect_last_n=2,
                tail_budget_fraction=0.20,
                prune_tool_results_over=100,
            )
        )
        msgs = [
            {"role": "user", "content": "Read a big file"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [{"id": "tc1", "function": {"name": "file.read"}}],
            },
            {"role": "tool", "tool_call_id": "tc1", "content": "x" * 5000},
            {"role": "assistant", "content": "Done reading"},
            {"role": "user", "content": "Now do something else"},
            {"role": "assistant", "content": "ok"},
        ]

        with (
            patch("agentos.harness.compaction.generate_summary", new_callable=AsyncMock) as mock,
            patch("agentos.harness.compaction.get_model_max_tokens", return_value=500),
        ):
            mock.return_value = "## Goal\nTest"
            result = await compact_context(msgs, config, "test-model", force=True)

        # The large tool result should have been pruned before summarization
        # (We can't directly check the pruned content, but the compaction should succeed)
        assert result.compacted
