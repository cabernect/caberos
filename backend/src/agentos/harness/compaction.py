"""Context compaction — head/middle/tail summarization (Hermes-style).

4-phase pipeline:
  Phase 1: Prune old tool results (no LLM cost)
  Phase 2: Determine head/tail boundaries (no LLM cost)
  Phase 3: Generate structured summary of the middle (1 LLM call)
  Phase 4: Reassemble — head + summary + tail, sanitize tool pairs

The compacted context preserves the narrative thread while fitting within
the model's context window budget.
"""

import logging
import time
from dataclasses import dataclass
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


def get_model_max_tokens(
    model_str: str,
    override: int | None = None,
    *,
    resolved_model: dict | None = None,
    model_override: int | None = None,
    output_tokens: int | None = None,
) -> int:
    """Resolved input budget via the catalog authority — never an SDK
    registry, fuzzy name match, or a 200K default. ``model_str`` is a
    routing/tokenizer name only, not a capability identity.

    Args:
        model_str: kept for signature compatibility — not consulted.
        override: run-level input ceiling (limits.max_context_tokens).
        resolved_model: resolved offering fields (limits with provenance).
        model_override: explicit model-declared budget (wins over catalog).
        output_tokens: output reserve.
    """
    from ..providers.catalog_policy import resolve_input_budget

    return resolve_input_budget(
        resolved_model,
        model_override=model_override,
        run_override=override,
        output_tokens=output_tokens,
    )["tokens"]


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


def _align_boundary_backward(messages: list[dict[str, Any]], boundary: int) -> int:
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
    use_responses: bool = False,
    accounting: Any | None = None,
    provider_id: str | None = None,
    model_name: str | None = None,
    agent_id: str | None = None,
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

    family = "responses" if use_responses else "chat"
    raw: Any = None
    error: Exception | None = None
    started = time.monotonic()
    try:
        if use_responses:
            # Responses API — the default for api.openai.com models. Reasoning
            # models reject max_tokens/chat-completions entirely, so summaries
            # must go through /v1/responses too. Generous output cap: reasoning
            # tokens share the budget with the summary text.
            kwargs: dict[str, Any] = {
                "model": model_str,
                "input": messages,
                "max_output_tokens": 2000,
            }
            if api_key:
                kwargs["api_key"] = api_key
            if base_url:
                kwargs["api_base"] = base_url
            raw = await litellm.aresponses(**kwargs)
            content = ""
            for item in getattr(raw, "output", []) or []:
                if getattr(item, "type", "") == "message":
                    for block in getattr(item, "content", []) or []:
                        if getattr(block, "type", "") in ("output_text", "text"):
                            content += getattr(block, "text", "") or ""
            return content
        kwargs = {
            "model": model_str,
            "messages": messages,
            "max_tokens": 1000,  # Summary should be compact
        }
        if api_key:
            kwargs["api_key"] = api_key
        if base_url:
            kwargs["api_base"] = base_url

        raw = await litellm.acompletion(**kwargs)
        return raw.choices[0].message.content or ""
    except Exception as e:
        error = e
        logger.warning(f"Compaction summary LLM call failed: {e}")
        # Fallback: use previous summary or a minimal stub
        if previous_summary:
            return previous_summary
        return f"[Compaction summary unavailable — {len(middle_messages)} messages compacted]"
    finally:
        # Exactly one ledger attempt per actual provider request — success,
        # error, or timeout all record.
        if raw is not None or error is not None:
            await _record_summary_call(
                accounting,
                raw,
                family,
                provider_id=provider_id,
                model_name=model_name,
                agent_id=agent_id,
                model_str=model_str,
                error=error,
                latency_ms=int((time.monotonic() - started) * 1000),
            )


async def _record_summary_call(
    accounting: Any | None,
    raw: Any,
    family: str,
    *,
    provider_id: str | None,
    model_name: str | None,
    agent_id: str | None,
    model_str: str | None,
    error: Exception | None = None,
    latency_ms: int = 0,
) -> None:
    """Ledger the summary aux call — one row per provider request, even
    with no rate snapshot (genuine reported amounts still count)."""
    try:
        from ..harness.scripted_model import ScriptedResponse
        from ..services.call_accounting import unknown_call_rates
        from ..services.model_ledger import record_system_call

        # No caller snapshot → an unknown-authority snapshot still yields
        # normalized native usage/cost (incl. a genuine explicit amount).
        snap = accounting or unknown_call_rates(provider_id or "", model_name or "", {"type": ""})
        assessment = snap.assess(raw, family=family)
        usage = getattr(assessment, "usage", None)
        cost_receipt = snap.receipt(assessment)
        response = None
        if error is None:
            cost = float(assessment.amount) if assessment.amount is not None else 0.0
            response = ScriptedResponse(
                tokens_in=int(usage.input_tokens or 0) if usage else 0,
                tokens_out=int(usage.output_tokens or 0) if usage else 0,
                cached_tokens=usage.cache_read_tokens if usage else None,
                thinking_tokens=usage.reasoning_tokens if usage else None,
                cost=cost,
                cost_source=assessment.source,
                cost_receipt=cost_receipt,
            )
        await record_system_call(
            kind="chat",
            purpose="compaction",
            provider_id=provider_id,
            model_name=model_name,
            model_str=model_str,
            agent_id=agent_id,
            response=response,
            error=error,
            latency_ms=latency_ms,
            detail={
                "operation": "compaction_summary",
                "cost_source": assessment.source,
                **(cost_receipt or {}),
            },
        )
    except Exception:
        logger.debug("summary accounting record failed", exc_info=True)


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
                    sanitized.append(
                        {
                            "role": "tool",
                            "tool_call_id": tc_id,
                            "content": "[Tool result not available after compaction]",
                        }
                    )
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
    use_responses: bool = False,
    input_budget: int | None = None,
    resolved_model: dict | None = None,
    accounting: Any | None = None,
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
    model_cfg = agent_config.model
    max_tokens = (
        input_budget
        if input_budget is not None
        else get_model_max_tokens(
            model_str,
            agent_config.limits.max_context_tokens,
            resolved_model=resolved_model,
            model_override=(model_cfg.max_context_tokens if model_cfg else None),
            output_tokens=(model_cfg.max_tokens if model_cfg else None),
        )
    )
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
    pruned_head = prune_tool_results(
        head, tail_start=len(head), prune_over=config.prune_tool_results_over
    )
    pruned_middle = prune_tool_results(
        middle, tail_start=len(middle), prune_over=config.prune_tool_results_over
    )

    # Phase 3: Generate structured summary
    summary = await generate_summary(
        pruned_middle,
        previous_summary=previous_summary,
        model_str=model_str,
        api_key=api_key,
        base_url=base_url,
        use_responses=use_responses,
        accounting=accounting,
        provider_id=(model_cfg.provider_id if model_cfg else None),
        model_name=(model_cfg.name if model_cfg else None),
        agent_id=agent_config.id,
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
