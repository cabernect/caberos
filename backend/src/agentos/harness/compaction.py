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
import time
from dataclasses import dataclass, field
from typing import Any

from ..config_schema import AgentConfig, CompactionConfig
from .memory_prompts import SUMMARY_TEMPLATE, UPDATE_TEMPLATE

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
        # Fallback: conservative byte upper-bound of the serialized message
        # structure (arguments, roles, nested parts — not just content).
        return len(
            json.dumps(messages, ensure_ascii=False, separators=(",", ":"), default=str).encode(
                "utf-8"
            )
        )


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
    tail_token_budget: int | None = None,
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

    # If the conversation is short, everything is head+tail, no middle:
    # tail starts where head ends so the tail still covers the rest.
    if n <= head_end + config.protect_last_n:
        return head_end, head_end  # no middle

    # Tail: token-budget based — a caller-supplied allowance reserves room
    # for the fixed system/tool section instead of sharing the full budget.
    tail_budget = (
        tail_token_budget
        if tail_token_budget is not None
        else int(threshold_tokens * config.tail_budget_fraction)
    )
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


async def generate_summary(
    middle_messages: list[dict[str, Any]],
    previous_summary: str | None,
    model_str: str,
    api_key: str | None = None,
    base_url: str | None = None,
    extra_params: dict | None = None,
    use_responses: bool = False,
    accounting: Any | None = None,
    provider_id: str | None = None,
    input_budget: int | None = None,
    model_name: str | None = None,
    agent_id: str | None = None,
    run_id: str | None = None,
    session_id: str | None = None,
    source_ids: list[str] | None = None,
) -> str:
    """Phase 3: Generate or update a structured summary of the middle messages.

    Uses an auxiliary LLM call with a fixed template. On later compressions,
    passes the previous summary and asks the model to update it.
    """
    if not middle_messages:
        return previous_summary or ""

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
            # Tool results already pruned by Phase 1 — included in full.
            transcript_lines.append(f"[Tool result]: {content}")
        elif role == "assistant" and msg.get("tool_calls"):
            tool_names = [tc.get("function", {}).get("name", "?") for tc in msg["tool_calls"]]
            transcript_lines.append(f"Assistant: [called {', '.join(tool_names)}]")
            if content:
                transcript_lines.append(f"  {content}")
        else:
            transcript_lines.append(f"{role.capitalize()}: {content}")

    transcript = "\n\n".join(transcript_lines)

    if previous_summary:
        prompt = UPDATE_TEMPLATE.format(
            previous_summary=previous_summary,
            new_messages=transcript,
        )
    else:
        prompt = f"{SUMMARY_TEMPLATE}\n\n### Conversation to Summarize\n{transcript}"

    messages = [{"role": "user", "content": prompt}]
    if input_budget is not None and count_tokens(messages, model_str) > input_budget:
        # The rendered summary prompt alone exceeds the input budget — fail
        # before any provider request; the caller retains originals.
        raise RuntimeError("Summary prompt exceeds the model input budget")

    family = "responses" if use_responses else "chat"
    raw: Any = None
    error: Exception | None = None
    cap_ref = None
    started = time.monotonic()
    from ..providers.litellm_transport import LiteLLMTransport
    from ..services.context_capture import capture_dispatch, capture_scope

    _transport = LiteLLMTransport()
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
            # Provider extras (azure api_version, bedrock aws_*) — never
            # let them reroute the counted request fields.
            for k, v in (extra_params or {}).items():
                if k not in ("model", "input", "messages", "tools", "stream"):
                    kwargs[k] = v
            with capture_scope(
                purpose="compaction",
                agent_id=agent_id,
                run_id=run_id,
                session_id=session_id,
                model=model_str,
                source_message_ids=source_ids or [],
                source_message_ids_total=len(source_ids or []),
            ):
                raw, cap_ref = await capture_dispatch("responses", kwargs, _transport.responses)
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
        for k, v in (extra_params or {}).items():
            if k not in ("model", "input", "messages", "tools", "stream"):
                kwargs[k] = v

        with capture_scope(
            purpose="compaction",
            agent_id=agent_id,
            run_id=run_id,
            session_id=session_id,
            model=model_str,
            source_message_ids=source_ids or [],
            source_message_ids_total=len(source_ids or []),
        ):
            raw, cap_ref = await capture_dispatch("chat", kwargs, _transport.completion)
        return raw.choices[0].message.content or ""
    except Exception as e:
        error = e
        logger.warning("Compaction summary LLM call failed (%s)", type(e).__name__)
        # Never fabricate a summary — the caller returns the original
        # history untouched with a generic error instead.
        raise
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
                capture_ref=cap_ref or getattr(error, "capture_ref", None),
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
    capture_ref: Any = None,
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
            capture_ref=capture_ref,
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


def _align_boundary_forward(messages: list[dict[str, Any]], boundary: int) -> int:
    """Move a HEAD boundary forward so no multi-tool batch is split: when an
    assistant tool-call block ends the head, pull every following tool result
    into the head as well (never leave a call without its results)."""
    while boundary < len(messages) and messages[boundary].get("role") == "tool":
        boundary += 1
    return boundary


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


def _summary_message(
    summary: str, head: list[dict[str, Any]], tail: list[dict[str, Any]]
) -> dict[str, Any]:
    """Render a stored summary as exactly one model message."""
    return {
        "role": _choose_summary_role(head, tail),
        "content": f"[Previous conversation summary]\n{summary}",
    }


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
    error: str | None = None
    # Original (possibly pruned) head+tail messages WITHOUT any generated
    # summary row — lets a Conversation render cleanly on later turns.
    retained_messages: list[dict[str, Any]] = field(default_factory=list)
    # DB Message ids covered by a successfully summarized middle slice.
    covered_ids: set[str] = field(default_factory=set)


async def compact_context(
    messages: list[dict[str, Any]],
    agent_config: AgentConfig,
    model_str: str,
    previous_summary: str | None = None,
    api_key: str | None = None,
    base_url: str | None = None,
    extra_params: dict | None = None,
    force: bool = False,
    use_responses: bool = False,
    input_budget: int | None = None,
    resolved_model: dict | None = None,
    accounting: Any | None = None,
    reserved_tokens: int = 0,
    source_ids: list[set[str] | None] | None = None,
    protected_tail_start: int | None = None,
    run_id: str | None = None,
    session_id: str | None = None,
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

    # `messages` holds uncovered ORIGINALS only — a stored summary renders
    # exactly once, in front of them, on every returned path.
    rendered = (
        [_summary_message(previous_summary, [], messages), *messages]
        if previous_summary
        else list(messages)
    )
    original_tokens = reserved_tokens + count_tokens(rendered, model_str)

    # Check if compaction is needed — auto-disabled config bypasses
    # compaction entirely unless forced, but the summary still renders once.
    if not force and (not config.auto_compaction or original_tokens <= threshold_tokens):
        return CompactionResult(
            messages=rendered,
            summary=previous_summary,
            compacted=False,
            original_tokens=original_tokens,
            compacted_tokens=original_tokens,
            head_count=0,
            middle_count=0,
            tail_count=len(messages),
            retained_messages=list(messages),
        )

    # Phase 2: Determine boundaries
    prior_summary_tokens = (
        count_tokens([_summary_message(previous_summary, [], messages)], model_str)
        if previous_summary
        else 0
    )
    tail_allowance = max(0, threshold_tokens - reserved_tokens - prior_summary_tokens)
    head_end, tail_start = determine_boundaries(
        messages, config, threshold_tokens, model_str, tail_token_budget=tail_allowance
    )

    # The current turn's protected rows must stay uncovered — clamp the tail
    # start no later than the protected index, then re-align complete batches.
    if protected_tail_start is not None and tail_start > protected_tail_start:
        tail_start = _align_boundary_backward(messages, protected_tail_start)
        if tail_start < head_end:
            tail_start = head_end

    # Align BOTH protected ranges so no multi-tool batch is split: head
    # extends forward over tool results belonging to its last call...
    head_end = _align_boundary_forward(messages, head_end)
    if tail_start < head_end:
        tail_start = head_end

    head = messages[:head_end]
    middle = messages[head_end:tail_start]
    tail = messages[tail_start:]

    # If no middle to summarize, return as-is
    if not middle:
        return CompactionResult(
            messages=rendered,
            summary=previous_summary,
            compacted=False,
            original_tokens=original_tokens,
            compacted_tokens=original_tokens,
            head_count=len(head),
            middle_count=0,
            tail_count=len(tail),
            retained_messages=[*head, *tail],
        )

    # Phase 1: Prune old tool results in head and middle
    # (tail is protected — no pruning)
    pruned_head = prune_tool_results(
        head, tail_start=len(head), prune_over=config.prune_tool_results_over
    )
    pruned_middle = prune_tool_results(
        middle, tail_start=len(middle), prune_over=config.prune_tool_results_over
    )

    # Summary aux call reserves a fixed 2000-token output inside the SAME
    # resolved model ceiling — not the reasoning call's (possibly smaller)
    # reservation. An invalid auxiliary reservation fails before dispatch.
    try:
        summary_input_ceiling = get_model_max_tokens(
            model_str,
            agent_config.limits.max_context_tokens,
            resolved_model=resolved_model,
            model_override=(model_cfg.max_context_tokens if model_cfg else None),
            output_tokens=2000,
        )
    except Exception:
        summary_input_ceiling = 0
    if input_budget is not None:
        summary_input_ceiling = min(summary_input_ceiling, input_budget)
    if summary_input_ceiling <= 0:
        return CompactionResult(
            messages=rendered,
            summary=previous_summary,
            compacted=False,
            original_tokens=original_tokens,
            compacted_tokens=original_tokens,
            head_count=0,
            middle_count=0,
            tail_count=len(messages),
            error="Summary input budget could not be reserved",
            retained_messages=list(messages),
        )

    # Phase 3: Generate structured summary — a failed or empty summary
    # returns the ORIGINAL history untouched (never a fabricated stub);
    # cancellation propagates.
    try:
        summary = await generate_summary(
            pruned_middle,
            input_budget=summary_input_ceiling,
            previous_summary=previous_summary,
            model_str=model_str,
            api_key=api_key,
            base_url=base_url,
            extra_params=extra_params,
            use_responses=use_responses,
            accounting=accounting,
            provider_id=(model_cfg.provider_id if model_cfg else None),
            model_name=(model_cfg.name if model_cfg else None),
            agent_id=agent_config.id,
            run_id=run_id,
            session_id=session_id,
            source_ids=sorted({sid for group in (source_ids or []) for sid in (group or [])}),
        )
    except Exception:
        summary = ""
    if not summary or not summary.strip():
        return CompactionResult(
            messages=rendered,
            summary=previous_summary,
            compacted=False,
            original_tokens=original_tokens,
            compacted_tokens=original_tokens,
            head_count=0,
            middle_count=0,
            tail_count=len(messages),
            error="Conversation summary could not be generated",
            retained_messages=list(messages),
        )

    # Phase 4: Reassemble
    compacted = reassemble(pruned_head, summary, tail)
    compacted_tokens = reserved_tokens + count_tokens(compacted, model_str)
    if compacted_tokens >= original_tokens:
        # An ineffective summary must not advance coverage — originals
        # stay with the prior summary untouched.
        return CompactionResult(
            messages=rendered,
            summary=previous_summary,
            compacted=False,
            original_tokens=original_tokens,
            compacted_tokens=compacted_tokens,
            head_count=0,
            middle_count=0,
            tail_count=len(messages),
            error="Summary did not reduce token usage",
            retained_messages=list(messages),
        )

    logger.info(
        f"Compaction: {len(messages)} msgs → {len(compacted)} msgs, "
        f"{original_tokens} → {compacted_tokens} tokens "
        f"(head={len(head)}, middle={len(middle)}, tail={len(tail)})"
    )

    covered_ids: set[str] = set()
    if source_ids:
        for ids in source_ids[head_end:tail_start]:
            if ids:
                covered_ids.update(ids)

    return CompactionResult(
        messages=compacted,
        summary=summary,
        compacted=True,
        original_tokens=original_tokens,
        compacted_tokens=compacted_tokens,
        head_count=len(head),
        middle_count=len(middle),
        tail_count=len(tail),
        retained_messages=[*pruned_head, *tail],
        covered_ids=covered_ids,
    )
