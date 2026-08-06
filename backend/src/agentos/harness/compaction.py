"""Context compaction — head/middle/tail summarization (Hermes-style).

4-phase pipeline:
  Phase 1: Prune old tool results (no LLM cost)
  Phase 2: Determine head/tail boundaries (no LLM cost)
  Phase 3: Generate structured summary of the middle (1 LLM call)
  Phase 4: Reassemble — head + summary + tail, sanitize tool pairs

The compacted context preserves the narrative thread while fitting within
the model's context window budget.
"""

import json
import logging
from dataclasses import dataclass, field
from typing import Any

from ..config_schema import AgentConfig, CompactionConfig

logger = logging.getLogger(__name__)

# --- Token counting ---

_token_cache: dict[str, int] = {}


def count_tokens(messages: list[dict[str, Any]], model: str = "gpt-4o") -> int:
    """Count tokens for a list of messages using litellm's tokenizer.

    Falls back to char-based estimate if tokenizer unavailable.
    """
    try:
        import litellm

        return litellm.token_counter(model=model, messages=messages)
    except Exception:
        # Fallback: ~4 chars per token
        total = 0
        for msg in messages:
            content = msg.get("content", "")
            if isinstance(content, str):
                total += len(content) // 4
            elif isinstance(content, list):
                for part in content:
                    if isinstance(part, dict) and "text" in part:
                        total += len(part["text"]) // 4
        return total


def count_text_tokens(text: str, model: str = "gpt-4o") -> int:
    """Count tokens for a plain text string (e.g. system prompt)."""
    if not text:
        return 0
    return count_tokens([{"role": "system", "content": text}], model)


def count_tool_tokens(tools: list[dict[str, Any]], model: str = "gpt-4o") -> int:
    """Estimate token count for tool schemas.

    Tool schemas are sent as a separate `tools` parameter, not as messages.
    We estimate by serializing to JSON and counting tokens.
    """
    if not tools:
        return 0
    try:
        import json

        # OpenAI counts tool tokens roughly as the JSON representation
        # plus some overhead per tool definition
        tool_json = json.dumps(tools, separators=(",", ":"))
        return count_text_tokens(tool_json, model) + len(tools) * 4  # overhead per tool
    except Exception:
        return 0


def get_model_max_tokens(model_str: str, override: int | None = None) -> int:
    """Get the max input tokens for a model.

    Resolution order:
      1. Explicit override from agent config (max_context_tokens)
      2. litellm's registry (exact match on model_str)
      3. Fuzzy match — strip provider prefix and try known model families
      4. Conservative default (32K)

    Results are cached per model_str.
    """
    cache_key = f"{model_str}:{override or 'auto'}"
    if cache_key in _token_cache:
        return _token_cache[cache_key]

    # 1. Explicit override
    if override and override > 0:
        _token_cache[cache_key] = override
        return override

    # 2. litellm registry — exact match
    try:
        import litellm

        info = litellm.get_model_info(model_str)
        max_tokens = info.get("max_input_tokens")
        if max_tokens:
            _token_cache[cache_key] = max_tokens
            return max_tokens
    except Exception:
        pass

    # 3. Fuzzy match — try to find a close match in litellm's registry
    try:
        import litellm

        bare = model_str.split("/", 1)[-1] if "/" in model_str else model_str

        # 3a. Try common provider prefixes with the bare name
        for prefix in ("openai/", "anthropic/", "google/", "meta/", "mistral/", "deepseek/"):
            try:
                info = litellm.get_model_info(f"{prefix}{bare}")
                max_tokens = info.get("max_input_tokens")
                if max_tokens:
                    _token_cache[cache_key] = max_tokens
                    return max_tokens
            except Exception:
                continue

        # 3b. Progressive suffix stripping — handle variant names like
        # "deepseek-v4-flash-free" → "deepseek-v4-flash" → match
        # "gpt-4o-2024-08-06-preview" → "gpt-4o" → match
        parts = bare.split("-")
        for i in range(len(parts) - 1, 0, -1):
            candidate = "-".join(parts[:i])
            # Try bare and with common prefixes
            for name in [candidate, f"deepseek/{candidate}", f"openai/{candidate}"]:
                try:
                    info = litellm.get_model_info(name)
                    max_tokens = info.get("max_input_tokens")
                    if max_tokens:
                        _token_cache[cache_key] = max_tokens
                        return max_tokens
                except Exception:
                    continue

        # 3c. Substring match against registry keys
        # e.g. "big-pickle" won't match, but "deepseek-v4-flash-free" contains
        # "deepseek-v4-flash" which is in the registry
        lower = bare.lower()
        # Sort by key length descending so we match the most specific entry first
        sorted_keys = sorted(litellm.model_cost.keys(), key=len, reverse=True)
        for key in sorted_keys:
            key_lower = key.lower()
            # Check if the bare name contains a known model name as a substring
            # or vice versa
            key_bare = key_lower.split("/", 1)[-1] if "/" in key_lower else key_lower
            if key_bare in lower and len(key_bare) >= 8:  # min length to avoid false positives
                entry = litellm.model_cost[key]
                max_tokens = entry.get("max_input_tokens")
                if max_tokens:
                    _token_cache[cache_key] = max_tokens
                    return max_tokens
    except Exception:
        pass

    # 4. Conservative default
    _token_cache[cache_key] = 32000
    return 32000


# --- Phase 1: Prune old tool results ---


def _is_tool_result(msg: dict[str, Any]) -> bool:
    """Check if a message is a tool result (role=tool)."""
    return msg.get("role") == "tool"


def prune_tool_results(
    messages: list[dict[str, Any]],
    tail_start: int,
    prune_over: int = 200,
) -> list[dict[str, Any]]:
    """Phase 1: Replace long tool results outside the protected tail with a stub.

    This is a pure string swap — no LLM cost. Targets the biggest token hogs
    (file reads, web fetches, shell output) while preserving small results.
    """
    pruned = []
    for i, msg in enumerate(messages):
        if i < tail_start and _is_tool_result(msg):
            content = msg.get("content", "")
            if isinstance(content, str) and len(content) > prune_over:
                msg = {**msg, "content": "[Old tool output cleared to save context space]"}
        pruned.append(msg)
    return pruned


# --- Phase 2: Determine boundaries ---


def _align_boundary_backward(
    messages: list[dict[str, Any]], boundary: int
) -> int:
    """Move the boundary backward to avoid splitting tool_call/tool_result pairs.

    If the message at `boundary` is a tool result, move back to include the
    matching tool call. If it's a tool call, move back to exclude it (so it
    stays in the middle to be summarized, not orphaned in the tail).
    """
    if boundary <= 0 or boundary >= len(messages):
        return boundary

    # Walk backward to find a safe split point
    while boundary > 0:
        msg = messages[boundary]
        role = msg.get("role", "")

        if role == "tool":
            # Tool result — need to include the matching tool call
            # Walk backward to find the assistant message with tool_calls
            boundary -= 1
            continue

        if role == "assistant" and msg.get("tool_calls"):
            # Assistant message with tool calls — if the results are in the
            # middle (not tail), move boundary back to exclude this call
            # so the call+result pair stays together in the middle
            boundary -= 1
            continue

        break

    return boundary


def determine_boundaries(
    messages: list[dict[str, Any]],
    config: CompactionConfig,
    threshold_tokens: int,
    model: str = "gpt-4o",
) -> tuple[int, int]:
    """Phase 2: Determine head and tail boundaries.

    Returns (head_end, tail_start) indices.
    - Messages[0:head_end] = head (protected, verbatim)
    - Messages[head_end:tail_start] = middle (summarized)
    - Messages[tail_start:] = tail (protected, verbatim)

    Head: first protect_first_n messages (hardcoded).
    Tail: walk backward accumulating tokens until tail_budget is spent,
          falling back to protect_last_n if that would protect fewer.
    """
    n = len(messages)

    # Head: first N messages
    head_end = min(config.protect_first_n, n)

    # If the conversation is short, everything is head+tail, no middle
    if n <= head_end + config.protect_last_n:
        return head_end, n  # no middle

    # Tail: token-budget based
    tail_budget = int(threshold_tokens * config.tail_budget_fraction)
    tail_start = n
    tail_tokens = 0

    for i in range(n - 1, head_end - 1, -1):
        msg_tokens = count_tokens([messages[i]], model)
        if tail_tokens + msg_tokens > tail_budget:
            break
        tail_tokens += msg_tokens
        tail_start = i

    # Ensure minimum tail size
    min_tail_start = n - config.protect_last_n
    if tail_start > min_tail_start:
        tail_start = min_tail_start

    # Don't let tail overlap head
    if tail_start < head_end:
        tail_start = head_end

    # Align boundary to avoid splitting tool pairs
    tail_start = _align_boundary_backward(messages, tail_start)

    # Final safety: if alignment pushed tail into head, no middle
    if tail_start <= head_end:
        tail_start = head_end

    return head_end, tail_start


# --- Phase 3: Structured summary ---


SUMMARY_TEMPLATE = """You are a conversation summarizer. Summarize the conversation segment below into a structured summary.

Use this exact format:

## Goal
What the user is trying to accomplish (1-2 sentences)

## Constraints & Preferences
Rules, formats, limits the user specified

## Progress
### Done
- Completed steps
### In Progress
- Current work
### Blocked
- Obstacles encountered

## Key Decisions
Choices made during the conversation

## Relevant Files
Files created, read, or modified

## Next Steps
What's likely to happen next

## Critical Context
Anything else essential for continuing the conversation

Keep each section concise. Omit empty sections. Do not include information that is not in the conversation.
"""

UPDATE_TEMPLATE = """You are updating a conversation summary. Below is the previous summary and new conversation messages. Update the summary to reflect the new messages.

- Move items from "In Progress" to "Done" as they complete
- Add new items to appropriate sections
- Remove items that are no longer relevant
- Keep the same format

### Previous Summary
{previous_summary}

### New Conversation Messages
{new_messages}

Output the updated summary in the same format.
"""


async def generate_summary(
    middle_messages: list[dict[str, Any]],
    previous_summary: str | None,
    model_str: str,
    api_key: str | None = None,
    base_url: str | None = None,
) -> str:
    """Phase 3: Generate or update a structured summary of the middle messages.

    Uses an auxiliary LLM call with a fixed template. On later compressions,
    passes the previous summary and asks the model to update it.
    """
    if not middle_messages:
        return previous_summary or ""

    import litellm

    # Format middle messages as a conversation transcript
    transcript_lines = []
    for msg in middle_messages:
        role = msg.get("role", "unknown")
        content = msg.get("content", "")
        if isinstance(content, list):
            # Multimodal — extract text parts
            text_parts = [p.get("text", "") for p in content if isinstance(p, dict) and "text" in p]
            content = "\n".join(text_parts)
        if role == "tool":
            # Include tool results (already pruned in Phase 1)
            transcript_lines.append(f"[Tool result]: {content[:500]}")
        elif role == "assistant" and msg.get("tool_calls"):
            tool_names = [tc.get("function", {}).get("name", "?") for tc in msg["tool_calls"]]
            transcript_lines.append(f"Assistant: [called {', '.join(tool_names)}]")
            if content:
                transcript_lines.append(f"  {content[:300]}")
        else:
            transcript_lines.append(f"{role.capitalize()}: {content[:500]}")

    transcript = "\n\n".join(transcript_lines)

    if previous_summary:
        prompt = UPDATE_TEMPLATE.format(
            previous_summary=previous_summary,
            new_messages=transcript,
        )
    else:
        prompt = f"{SUMMARY_TEMPLATE}\n\n### Conversation to Summarize\n{transcript}"

    messages = [{"role": "user", "content": prompt}]

    kwargs: dict[str, Any] = {
        "model": model_str,
        "messages": messages,
        "max_tokens": 1000,  # Summary should be compact
    }
    if api_key:
        kwargs["api_key"] = api_key
    if base_url:
        kwargs["api_base"] = base_url

    try:
        response = await litellm.acompletion(**kwargs)
        return response.choices[0].message.content or ""
    except Exception as e:
        logger.warning(f"Compaction summary LLM call failed: {e}")
        # Fallback: use previous summary or a minimal stub
        if previous_summary:
            return previous_summary
        return f"[Compaction summary unavailable — {len(middle_messages)} messages compacted]"


# --- Phase 4: Reassemble ---


def _sanitize_tool_pairs(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Remove orphaned tool results and inject stubs for orphaned tool calls.

    After compaction, the message list may have:
    - Tool results without a matching tool call (the call was in the head/middle)
      → remove these orphaned results
    - Tool calls without a matching tool result (the result was in the middle)
      → inject a stub result so the model doesn't error
    """
    # Collect all tool_call IDs
    call_ids: set[str] = set()
    for msg in messages:
        if msg.get("role") == "assistant" and msg.get("tool_calls"):
            for tc in msg["tool_calls"]:
                tc_id = tc.get("id", "")
                if tc_id:
                    call_ids.add(tc_id)

    # Collect all tool result IDs
    result_ids: set[str] = set()
    for msg in messages:
        if msg.get("role") == "tool":
            tid = msg.get("tool_call_id", "")
            if tid:
                result_ids.add(tid)

    # Build sanitized list
    sanitized: list[dict[str, Any]] = []
    for msg in messages:
        if msg.get("role") == "tool":
            tid = msg.get("tool_call_id", "")
            if tid and tid not in call_ids:
                # Orphaned tool result — skip
                continue
            sanitized.append(msg)
        elif msg.get("role") == "assistant" and msg.get("tool_calls"):
            sanitized.append(msg)
            # Check if any tool calls lack results
            for tc in msg["tool_calls"]:
                tc_id = tc.get("id", "")
                if tc_id and tc_id not in result_ids:
                    # Inject stub result
                    sanitized.append({
                        "role": "tool",
                        "tool_call_id": tc_id,
                        "content": "[Tool result not available after compaction]",
                    })
        else:
            sanitized.append(msg)

    return sanitized


def _choose_summary_role(head: list[dict[str, Any]], tail: list[dict[str, Any]]) -> str:
    """Choose the role for the summary message to preserve user/assistant alternation.

    The summary should not break the expected message ordering. If the last
    head message is an assistant, the summary should be "user" (so the next
    tail message can be assistant). If the last head is user, summary is "assistant".
    """
    if not head:
        return "system"
    last_role = head[-1].get("role", "system")
    if last_role == "assistant":
        return "user"
    elif last_role == "user":
        return "assistant"
    return "system"


def reassemble(
    head: list[dict[str, Any]],
    summary: str,
    tail: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Phase 4: Reassemble the final message list.

    head + summary message + tail, with tool pair sanitization.
    """
    summary_role = _choose_summary_role(head, tail)
    summary_msg = {
        "role": summary_role,
        "content": f"[Previous conversation summary]\n{summary}" if summary else "",
    }

    parts = head[:]
    if summary:
        parts.append(summary_msg)
    parts.extend(tail)

    return _sanitize_tool_pairs(parts)


# --- Main entry point ---


@dataclass
class CompactionResult:
    """Result of a compaction run."""
    messages: list[dict[str, Any]]
    summary: str | None
    compacted: bool
    original_tokens: int
    compacted_tokens: int
    head_count: int
    middle_count: int
    tail_count: int


async def compact_context(
    messages: list[dict[str, Any]],
    agent_config: AgentConfig,
    model_str: str,
    previous_summary: str | None = None,
    api_key: str | None = None,
    base_url: str | None = None,
    force: bool = False,
) -> CompactionResult:
    """Run the 4-phase compaction pipeline.

    Args:
        messages: Full message history (system prompt NOT included — it's
            prepended separately by build_message_history).
        agent_config: Agent config (for compaction settings).
        model_str: LiteLLM model string (e.g. "openai/gpt-4o").
        previous_summary: Existing conversation summary (for incremental updates).
        api_key: Provider API key for the summary LLM call.
        base_url: Provider base URL.
        force: If True, compact even if under threshold (manual /compact).

    Returns:
        CompactionResult with the compacted messages and metadata.
    """
    config = agent_config.compaction
    max_tokens = get_model_max_tokens(model_str)
    threshold_tokens = int(max_tokens * config.threshold)

    original_tokens = count_tokens(messages, model_str)

    # Check if compaction is needed
    if not force and original_tokens <= threshold_tokens:
        return CompactionResult(
            messages=messages,
            summary=previous_summary,
            compacted=False,
            original_tokens=original_tokens,
            compacted_tokens=original_tokens,
            head_count=0,
            middle_count=0,
            tail_count=len(messages),
        )

    # Phase 2: Determine boundaries
    head_end, tail_start = determine_boundaries(messages, config, threshold_tokens, model_str)

    head = messages[:head_end]
    middle = messages[head_end:tail_start]
    tail = messages[tail_start:]

    # If no middle to summarize, return as-is
    if not middle:
        return CompactionResult(
            messages=messages,
            summary=previous_summary,
            compacted=False,
            original_tokens=original_tokens,
            compacted_tokens=original_tokens,
            head_count=len(head),
            middle_count=0,
            tail_count=len(tail),
        )

    # Phase 1: Prune old tool results in head and middle
    # (tail is protected — no pruning)
    pruned_head = prune_tool_results(head, tail_start=len(head), prune_over=config.prune_tool_results_over)
    pruned_middle = prune_tool_results(middle, tail_start=len(middle), prune_over=config.prune_tool_results_over)

    # Phase 3: Generate structured summary
    summary = await generate_summary(
        pruned_middle,
        previous_summary=previous_summary,
        model_str=model_str,
        api_key=api_key,
        base_url=base_url,
    )

    # Phase 4: Reassemble
    compacted = reassemble(pruned_head, summary, tail)
    compacted_tokens = count_tokens(compacted, model_str)

    logger.info(
        f"Compaction: {len(messages)} msgs → {len(compacted)} msgs, "
        f"{original_tokens} → {compacted_tokens} tokens "
        f"(head={len(head)}, middle={len(middle)}, tail={len(tail)})"
    )

    return CompactionResult(
        messages=compacted,
        summary=summary,
        compacted=True,
        original_tokens=original_tokens,
        compacted_tokens=compacted_tokens,
        head_count=len(head),
        middle_count=len(middle),
        tail_count=len(tail),
    )
