"""Harness — the agent execution loop (D2, D19 steps 7-11).

Assembles context, calls the model, iterates on tool calls (mediated by
the syscall layer), enforces turn/cost limits, and emits SSE events.
"""

import asyncio
import hashlib
import json
import logging
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from ..capabilities.catalog import CapabilityRunCatalog
from ..config_schema import AgentConfig
from ..services.context_capture import capture_scope, current_capture_scope
from ..services.tool_status import tool_event_status
from ..syscall.protocol import SyscallHandler, SyscallResult, ToolCall
from .context import (
    TOOL_RESULT_MAX_CHARS,
    assemble_system_prompt,
    assemble_tool_schemas,
    attachment_lines,
    build_message_history,
)
from .conversation import Conversation
from .guardrails import apply_guardrails
from .scripted_model import ScriptedModel, ScriptedResponse

logger = logging.getLogger(__name__)


@dataclass
class RunResult:
    """Result of a harness run."""

    final_answer: str = ""
    total_turns: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    cached_tokens: int | None = None
    thinking_tokens: int | None = None
    total_cost: float = 0.0
    tool_calls_made: list[dict[str, Any]] = field(default_factory=list)
    status: str = "completed"  # completed, failed, limit_exceeded
    error: str | None = None
    guardrail_warnings: list[str] = field(default_factory=list)
    guardrail_redactions: list[str] = field(default_factory=list)
    # Compaction metadata (for context bar)
    context_tokens: int = 0  # tokens actually sent to the model
    max_context_tokens: int = 0  # model's context window
    compacted: bool = False  # whether compaction occurred this run
    context_breakdown: dict[str, int] = field(default_factory=dict)  # per-section token counts
    # W11 additive — how max_context_tokens was resolved, never a guessed capacity.
    context_budget_source: str | None = None
    loaded_capabilities: list[str] = field(default_factory=list)
    terminals_active: list[str] = field(default_factory=list)


# SSE event emitter type: async callable that takes (event_type: str, payload: dict)
EventEmitter = Callable[[str, dict[str, Any]], Any] | None

_CONTEXT_OVERFLOW_PATTERNS = (
    "context length",
    "context_length",
    "context window",
    "maximum context",
    "contextwindowexceeded",
    "too many tokens",
    "request too large",
    "reduce the length",
    "input is too long",
    "prompt is too long",
    "exceeds the limit",
    "exceeded the token",
)


def _is_context_overflow(err: Exception) -> bool:
    """Provider rejected the request for exceeding the context window —
    recoverable via forced compaction, unlike generic errors."""
    if type(err).__name__ == "ContextWindowExceededError":
        return True
    msg = str(err).lower()
    return any(p in msg for p in _CONTEXT_OVERFLOW_PATTERNS)


# Backoff before each retry — one entry per retry, so 3 attempts total.
_MODEL_RETRY_DELAYS_S = (2.0, 8.0)
_TRANSIENT_ERROR_NAMES = frozenset(
    {
        "APIConnectionError",
        "APITimeoutError",
        "Timeout",
        "ConnectError",
        "ConnectTimeout",
        "ReadTimeout",
        "RemoteProtocolError",
        "ReadError",
        "WriteError",
        "PoolTimeout",
        "NetworkError",
        "ServiceUnavailableError",
        "InternalServerError",
        "BadGatewayError",
        "GatewayTimeout",
    }
)


def _is_transient_model_error(err: BaseException) -> bool:
    """Network/5xx/429 failures worth retrying — auth, context overflow and
    request-shape errors are not. Timeout/connection classes are checked
    before status_code: litellm.Timeout reports 408 and is not a builtin
    TimeoutError."""
    if isinstance(err, (TimeoutError, ConnectionError)):
        return True
    status = getattr(err, "status_code", None)
    if isinstance(status, int):
        return status in (408, 429) or status >= 500
    return type(err).__name__ in _TRANSIENT_ERROR_NAMES


class ApprovalBatch:
    """Barrier for all calls emitted by one model turn."""

    def __init__(self, call_ids: list[str]) -> None:
        self.id = str(uuid.uuid4())
        self.call_ids = tuple(call_ids)
        self._pending = set(call_ids)
        self._event = asyncio.Event()
        self._lock = asyncio.Lock()

    @property
    def size(self) -> int:
        return len(self.call_ids)

    @property
    def pending_count(self) -> int:
        return len(self._pending)

    async def arrive(self, call_id: str, approved: bool) -> bool:
        async with self._lock:
            self._pending.discard(call_id)
            if not self._pending:
                self._event.set()
        await self._event.wait()
        return approved


def _approval_batch_for(
    agent_config: AgentConfig,
    session: Any,
    calls: list[ToolCall],
) -> ApprovalBatch | None:
    """Create one barrier for the calls emitted in a model turn.

    The barrier includes calls that will be denied by the syscall layer as well
    as calls that require approval. Each call must reach a terminal decision
    before any approved call from the same turn can execute.
    """
    if len(calls) < 2:
        return None
    return ApprovalBatch([call.id for call in calls])


def _call_purpose(trigger: str) -> str:
    return "reflection" if trigger == "reflection" else "reasoning"


@dataclass
class _RunState:
    """Shared mutable state for one harness run.

    The loop phases — _assemble_context, _call_model,
    _mediate_tool_calls, _finalize_answer — read and write through this
    object instead of closing over ~20 locals, so each phase is a named,
    independently readable unit.
    """

    # Inputs (set once by run())
    agent_config: AgentConfig
    session: Any
    message: str
    syscall_handler: SyscallHandler
    run_id: str
    recent_messages: list[Any] | None = None
    conversation: Conversation | None = None
    current_message_id: str | None = None
    trigger: str = "user_message"
    event_emitter: EventEmitter = None
    attachments: list[Any] | None = None
    skill: str | None = None
    parent_config: AgentConfig | None = None
    resolved_skills: list[Any] | None = None
    core_snapshot: Any | None = None
    system_prompt_override: str | None = None

    # Step 7 outputs — assembled context
    history: list[dict[str, Any]] = field(default_factory=list)
    system_prompt: str = ""
    tool_schemas: list[dict[str, Any]] = field(default_factory=list)
    capability_catalog: Any = None
    restrictions: Any = None
    visible_capability_names: list[str] = field(default_factory=list)

    # Model info + resolved input budget
    model_str: str = "gpt-4o"  # fallback
    api_key: Any = None
    base_url: Any = None
    extra_params: dict[str, Any] = field(default_factory=dict)
    use_responses: bool = False
    resolved_model: dict[str, Any] = field(default_factory=dict)
    accounting: Any = None
    resolved_input_budget: int = 0
    context_budget_source: str | None = None

    # Run result + per-turn loop state
    result: RunResult = field(default_factory=RunResult)
    call_receipts: dict[str, dict] = field(default_factory=dict)
    current_user_row: Any = None
    failed_auto_fingerprints: set[str] = field(default_factory=set)
    compaction_runs: list[Any] = field(default_factory=list)
    consecutive_tool_failures: int = 0
    max_consecutive_failures: int = 5
    overflow_retried: bool = False
    # Set by _call_model when it returns None: "retry" redoes the turn after
    # a successful forced compaction, "stop" breaks the loop, "abort" returns
    # the failed result immediately.
    turn_outcome: str | None = None
    # Per-dispatch model-call bookkeeping for run()'s ok receipt.
    call_started: float = 0.0
    streamed_call: bool = False
    capture_ref: Any = None


class Harness:
    """The agent execution loop."""

    def __init__(self, model: ScriptedModel | Any) -> None:
        """Initialize with a model (ScriptedModel for tests, or a real adapter later)."""
        self.model = model

    async def run(
        self,
        agent_config: AgentConfig,
        session: Any,
        message: str,
        syscall_handler: SyscallHandler,
        run_id: str,
        recent_messages: list[Any] | None = None,
        conversation: Conversation | None = None,
        current_message_id: str | None = None,
        trigger: str = "user_message",
        event_emitter: EventEmitter = None,
        attachments: list[Any] | None = None,
        skill: str | None = None,
        parent_config: AgentConfig | None = None,
        resolved_skills: list[Any] | None = None,
        core_snapshot: Any | None = None,
        system_prompt_override: str | None = None,
    ) -> RunResult:
        """Execute the agent loop (D19 steps 7-11).

        7. Assemble context   → _assemble_context
        8. Reason (call model) → _call_model
        9. Mediate (tool calls through syscall layer) → _mediate_tool_calls
        10. Check limits
        11. Iterate until final answer or limit hit → _finalize_answer
        """
        ctx = _RunState(
            agent_config=agent_config,
            session=session,
            message=message,
            syscall_handler=syscall_handler,
            run_id=run_id,
            recent_messages=recent_messages,
            conversation=conversation,
            current_message_id=current_message_id,
            trigger=trigger,
            event_emitter=event_emitter,
            attachments=attachments,
            skill=skill,
            parent_config=parent_config,
            resolved_skills=resolved_skills,
            core_snapshot=core_snapshot,
            system_prompt_override=system_prompt_override,
        )
        result = ctx.result

        # Step 7: Assemble context — returns False when the resolved model
        # budget is a configuration error (run fails before any model call).
        if not await self._assemble_context(ctx):
            return result

        # Inject spawn context into the syscall handler so run_subagent
        # can access the harness, session, run_id, and event_emitter.
        if hasattr(ctx.syscall_handler, "_spawn_context"):
            ctx.syscall_handler._spawn_context = {
                "harness": self,
                "session": ctx.session,
                "run_id": ctx.run_id,
                "event_emitter": ctx.event_emitter,
                "syscall_handler": ctx.syscall_handler,
            }

        max_turns = ctx.agent_config.limits.max_turns_per_run
        max_cost = (
            ctx.agent_config.heartbeat.max_cost_per_heartbeat
            if ctx.trigger == "heartbeat"
            else ctx.agent_config.limits.max_cost_per_run
        )

        # Steps 8-11: the loop
        while result.total_turns < max_turns:
            if result.total_cost >= max_cost:
                result.status = "limit_exceeded"
                result.error = "Run cost limit reached before model dispatch"
                break
            result.total_turns += 1
            await self._refresh_capabilities(ctx)
            # Per-dispatch full-budget gate: refreshed schemas + summary-aware
            # conversation count; compact under threshold, never dispatch an
            # oversized request.
            gate_error = await self._budget_gate(ctx)
            result.loaded_capabilities = sorted(ctx.capability_catalog.loaded)
            if gate_error:
                result.status = "failed"
                result.error = gate_error
                break

            # Per-turn signal that a model call is being dispatched — the
            # frontend renders the "thinking…" affordance from here until
            # this turn's first streamed output (thinking/token/tool_call).
            if ctx.event_emitter:
                await self._emit(ctx.event_emitter, "typing", {})

            # Step 8: Call model
            response = await self._call_model(ctx)
            if response is None:
                outcome = ctx.turn_outcome
                ctx.turn_outcome = None
                if outcome == "abort":
                    return result
                if outcome == "retry":
                    continue
                break  # "stop" — compaction persist failure already recorded

            # Accumulate tokens/cost
            result.tokens_in += response.tokens_in
            result.tokens_out += response.tokens_out
            result.cached_tokens = response.cached_tokens
            if response.thinking_tokens is not None:
                result.thinking_tokens = (result.thinking_tokens or 0) + response.thinking_tokens
            result.total_cost += response.cost

            # Per-model-call accounting (v0.2 foundations)
            await self._record_model_call(
                ctx.syscall_handler,
                run_id=ctx.run_id,
                agent_config=ctx.agent_config,
                session_id=getattr(ctx.session, "id", None),
                purpose=_call_purpose(ctx.trigger),
                turn=result.total_turns,
                model_str=ctx.model_str,
                streamed=ctx.streamed_call,
                latency_ms=int((time.monotonic() - ctx.call_started) * 1000),
                status="ok",
                tokens_in=response.tokens_in,
                tokens_out=response.tokens_out,
                cached_tokens=response.cached_tokens,
                thinking_tokens=response.thinking_tokens,
                cost=response.cost,
                cost_source=response.cost_source,
                cost_receipt=getattr(response, "cost_receipt", None),
                capture_ref=ctx.capture_ref or getattr(response, "request_capture", None),
            )

            # Step 9: Process tool calls, or Step 10/11: final answer
            if response.tool_calls:
                await self._mediate_tool_calls(ctx, response)
                continue

            await self._finalize_answer(ctx, response)

            # Step 10: Check limits
            if result.total_cost > max_cost:
                result.status = "limit_exceeded"
                result.final_answer = ctx.agent_config.fallback.on_limit_exceeded
                break

            break

        # Step 11: Check if we hit the turn limit
        if result.total_turns >= max_turns and not result.final_answer:
            result.status = "limit_exceeded"
            result.final_answer = "I've reached my turn limit for this run."

        # A run must not silently finish with live terminals — surface them so
        # the operator/model can read or close them.
        try:
            from ..terminal.registry import terminal_registry

            active = await terminal_registry.active_for_run(ctx.run_id)
            if active:
                result.terminals_active = active
                if ctx.event_emitter:
                    await self._emit(
                        ctx.event_emitter,
                        "terminals_active",
                        {"terminal_ids": active},
                    )
        except Exception:
            pass

        # Note: message_complete is emitted by runner.py after the pipeline
        # finishes, with full context metadata (context_tokens, max_context_tokens,
        # compacted, context_breakdown). Don't emit it here — the frontend closes
        # the SSE connection on the first message_complete it receives.

        return result

    async def _assemble_context(self, ctx: _RunState) -> bool:
        """Step 7: assemble system prompt, tool schemas, and history.

        Returns False when the resolved model context/output budget is a
        known configuration error — the run fails before any model call.
        """
        agent_config = ctx.agent_config
        session = ctx.session
        message = ctx.message
        syscall_handler = ctx.syscall_handler
        run_id = ctx.run_id
        skill = ctx.skill
        core_snapshot = ctx.core_snapshot
        attachments = ctx.attachments
        current_message_id = ctx.current_message_id
        recent_messages = ctx.recent_messages
        resolved_skills = ctx.resolved_skills
        system_prompt_override = ctx.system_prompt_override

        # Load KG facts for this contact (D34 — subject-scoped, D10)
        # Startup retrieval removed (bounded-core slice): no KG/snippet/
        # archive searches on dispatch — the tools/stores remain available
        # on demand. Pinned core covers standing context.
        kg_facts: list[dict] = []
        recall_snippets: list[dict] = []
        past_sessions: list[dict] = []

        # Check if the model supports vision (for system prompt awareness) —
        # resolved offering provenance, never a LiteLLM/heuristic guess.
        supports_vision = None
        if agent_config.model and agent_config.model.name:
            try:
                import json as _json

                from ..providers.model_catalog import get_offering

                _db = getattr(syscall_handler, "db", None)
                offering = (
                    await get_offering(_db, agent_config.model.provider_id, agent_config.model.name)
                    if _db is not None
                    else None
                )
                if offering is not None:
                    resolved = _json.loads(offering.resolved_json or "{}")
                    supports_vision = resolved.get("supports_vision")
            except Exception:
                supports_vision = None
        if hasattr(syscall_handler, "supports_vision"):
            syscall_handler.supports_vision = bool(supports_vision)

        ctx.capability_catalog = CapabilityRunCatalog(
            agent_config=agent_config,
            db=getattr(syscall_handler, "db", None),
            run_id=run_id,
            parent_config=ctx.parent_config,
        )
        await ctx.capability_catalog.prepare()
        ctx.restrictions = getattr(syscall_handler, "restrictions", None)
        ctx.visible_capability_names = self._visible_capability_names(ctx)

        # Saved browser logins (W4): operator-managed persistent profiles the
        # agent can't enumerate itself — inject name + domain scope so
        # browser_open(profile=…) is usable without the user spelling it out.
        browser_profiles: list[dict] = []
        if "browser_open" in ctx.visible_capability_names and getattr(syscall_handler, "db", None):
            from sqlalchemy import select as _select

            from ..models.browser_profile import BrowserProfile

            try:
                rows = (await syscall_handler.db.execute(_select(BrowserProfile))).scalars().all()
                browser_profiles = [
                    {
                        "name": p.name,
                        "allowed_domains": json.loads(p.allowed_domains or "[]"),
                        "description": p.description,
                    }
                    for p in rows
                ]
            except Exception:
                browser_profiles = []

        # W6: resolve the effective skill set from the DB (published +
        # assigned) + live agent-local workspace scan. The pipeline normally
        # resolves once and passes it in (so the manifest pins match the
        # menu); direct harness callers (subagents) resolve here.
        builder_draft: dict | None = None
        forced_skill_rendered: dict | None = None
        _db = getattr(syscall_handler, "db", None)
        if _db is not None:
            from sqlalchemy import select as _select

            from ..models.skill import Skill
            from ..skills.loader import render_skill_dir
            from ..skills.resolution import pinned_dir, resolve_effective_skills

            if resolved_skills is None:
                try:
                    resolved_skills = await resolve_effective_skills(_db, agent_config.id)
                except Exception:
                    resolved_skills = []

            # A draft Skill row linked to this session makes it a builder
            # session — force-load skill-creator and inject the overlay.
            if getattr(session, "id", None):
                try:
                    draft = await _db.scalar(
                        _select(Skill).where(
                            Skill.builder_session_id == session.id,
                            Skill.status == "draft",
                        )
                    )
                    if draft is not None:
                        builder_draft = {"id": draft.id, "name": draft.name}
                        if not skill:
                            skill = "skill-creator"
                except Exception:
                    builder_draft = None

            # Render a forced skill from the pinned revision dir so a mid-run
            # publish can't serve content the menu didn't advertise.
            if skill and resolved_skills:
                hit = next((s for s in resolved_skills if s.name == skill), None)
                if hit is not None:
                    try:
                        path = await pinned_dir(_db, hit, run_id)
                        forced_skill_rendered = render_skill_dir(path, hit.scope)
                    except Exception:
                        forced_skill_rendered = None

        ctx.system_prompt = assemble_system_prompt(
            agent_config,
            message,
            kg_facts=kg_facts,
            recall_snippets=recall_snippets,
            forced_skill=skill,
            past_sessions=past_sessions,
            supports_vision=supports_vision,
            enabled_caps=ctx.visible_capability_names,
            browser_profiles=browser_profiles,
            resolved_skills=resolved_skills,
            forced_skill_rendered=forced_skill_rendered,
            builder_draft=builder_draft,
            core_snapshot=core_snapshot,
        )
        if system_prompt_override is not None:
            ctx.system_prompt = system_prompt_override
        # A successfully rendered forced/slash skill is an activation —
        # recorded once after assembly, on an isolated session so a failed
        # write never poisons the run's shared session.
        if forced_skill_rendered is not None:
            _hit = next((s for s in (resolved_skills or []) if s.name == skill), None)
            if _hit is not None:
                from ..skills.usage import record_skill_activation_isolated

                await record_skill_activation_isolated(
                    _hit,
                    getattr(syscall_handler, "_parent_run_id", None) or run_id,
                    "forced",
                    sub_agent_id=getattr(syscall_handler, "_sub_agent_id", None),
                )

        ctx.tool_schemas = assemble_tool_schemas(
            agent_config,
            capability_names=ctx.visible_capability_names,
        )
        conversation = ctx.conversation
        if conversation is None:
            # Compat path for non-persistent callers (subagents, direct
            # harness tests): transient state, no coverage bookkeeping.
            conversation = Conversation(session_id="")
            history = build_message_history(
                ctx.system_prompt, recent_messages or [], message, attachments
            )
            conversation.messages = history[1:]
            conversation.source_ids = [set() for _ in conversation.messages]
            # Transient conversation — never imports the parent session's
            # summary (subagents spawn here too).
            history = history[:1] + conversation.render()
        else:
            # Stored records → deterministic uncovered originals; the user
            # row joins with its stored id so coverage can map it later.
            user_content = message
            if attachments:
                user_content = "\n".join([message, *attachment_lines(attachments)])
            user_row = {"role": "user", "content": user_content}
            conversation.append(user_row, {current_message_id} if current_message_id else set())
            history = [{"role": "system", "content": ctx.system_prompt}] + conversation.render()
        ctx.conversation = conversation
        ctx.history = history

        # Object reference for the current-turn user row — identity lookup
        # yields the protected tail index before every compaction.
        ctx.current_user_row = (
            conversation.messages[-1]
            if conversation.messages and conversation.messages[-1].get("role") == "user"
            else None
        )

        # Get model info for token counting + summary LLM call.
        # resolved_model + accounting come from the same frozen capture as
        # the execution calls — one resolved input budget for compaction,
        # the context bar, and any overflow retry.
        if hasattr(self.model, "get_model_info"):
            try:
                info = await self.model.get_model_info(agent_config.model)
                ctx.model_str = info["model_str"]
                ctx.api_key = info["api_key"]
                ctx.base_url = info["base_url"]
                ctx.extra_params = info.get("extra_params") or {}
                ctx.use_responses = bool(info.get("use_responses"))
                ctx.accounting = info.get("accounting")
                ctx.resolved_model = info.get("resolved_model") or {}
            except Exception:
                pass

        from ..providers.catalog_policy import resolve_input_budget

        try:
            _budget = resolve_input_budget(
                ctx.resolved_model,
                model_override=(
                    agent_config.model.max_context_tokens if agent_config.model else None
                ),
                run_override=agent_config.limits.max_context_tokens,
                output_tokens=(agent_config.model.max_tokens if agent_config.model else None),
            )
            ctx.resolved_input_budget = _budget["tokens"]
            ctx.context_budget_source = _budget["source"]
        except ValueError as exc:
            # A KNOWN-capacity model with a contradictory reservation/output
            # budget is a configuration error — never substitute a guessed
            # 32k budget and dispatch anyway. Genuine unknown-capacity models
            # fall through resolve_input_budget's own application_fallback.
            ctx.result.status = "failed"
            ctx.result.error = (
                f"Model context/output budget is invalid — check the agent's model limits: {exc}"
            )
            return False

        ctx.result.max_context_tokens = ctx.resolved_input_budget
        ctx.result.context_budget_source = ctx.context_budget_source
        return True

    def _visible_capability_names(self, ctx: _RunState) -> list[str]:
        names = ctx.capability_catalog.model_capability_names()
        if ctx.restrictions is not None:
            names = [name for name in names if name in ctx.restrictions.capability_names]
        return names

    async def _refresh_capabilities(self, ctx: _RunState) -> None:
        """Re-prepare the catalog and rebuild tool schemas for this turn —
        capabilities can appear mid-run (skill publish, profile add)."""
        await ctx.capability_catalog.prepare(refresh=True)
        ctx.visible_capability_names = self._visible_capability_names(ctx)
        ctx.tool_schemas = assemble_tool_schemas(
            ctx.agent_config,
            capability_names=ctx.visible_capability_names,
        )

    async def _mint_compaction_run(self, ctx: _RunState) -> str | None:
        """Auto/forced compaction is session maintenance, not parent-run
        work — give its summary call a standalone compaction Run so
        traces show it separately. Falls back to the parent run id when
        no DB session is available (transient/sub-agent conversations)."""
        from ..models.run import Run

        _db = getattr(ctx.syscall_handler, "db", None)
        sess_id = getattr(ctx.session, "id", None)
        contact_id = getattr(ctx.session, "contact_id", None)
        if _db is None or sess_id is None or not contact_id:
            return ctx.run_id
        compact_run = Run(
            session_id=sess_id,
            agent_id=ctx.agent_config.id,
            contact_id=contact_id,
            status="running",
            trigger="compaction",
        )
        _db.add(compact_run)
        await _db.flush()
        await _db.commit()
        ctx.compaction_runs.append(compact_run)
        return compact_run.id

    def _conv_fingerprint(self, ctx: _RunState) -> str:
        h = hashlib.sha256()
        for m in ctx.conversation.messages:
            h.update((m.get("role", "") + "|" + str(m.get("content", ""))[:200]).encode())
        return h.hexdigest()

    def _protected_tail_index(self, ctx: _RunState) -> int | None:
        if ctx.current_user_row is None:
            return None
        for i, m in enumerate(ctx.conversation.messages):
            if m is ctx.current_user_row:
                return i
        return None

    async def _apply_compaction(self, ctx: _RunState, *, force: bool) -> str | None:
        """Compact the conversation when it helps. Returns an error string
        when a *successful* summary could not be durably stored (CAS loss
        or DB failure) — the caller must then fail the run instead of
        dispatching on an unsaved summary."""
        from .compaction import compact_context, count_text_tokens, count_tool_tokens

        conversation = ctx.conversation
        reserved = count_text_tokens(ctx.system_prompt, ctx.model_str) + count_tool_tokens(
            ctx.tool_schemas, ctx.model_str
        )
        fp = self._conv_fingerprint(ctx)
        if not force and fp in ctx.failed_auto_fingerprints:
            return None
        cr = await compact_context(
            messages=list(conversation.messages),
            agent_config=ctx.agent_config,
            model_str=ctx.model_str,
            previous_summary=conversation.summary,
            api_key=ctx.api_key,
            base_url=ctx.base_url,
            extra_params=ctx.extra_params,
            force=force,
            use_responses=ctx.use_responses,
            input_budget=ctx.resolved_input_budget,
            resolved_model=ctx.resolved_model,
            accounting=ctx.accounting,
            reserved_tokens=reserved,
            session_id=getattr(ctx.session, "id", None),
            source_ids=list(conversation.source_ids),
            protected_tail_start=self._protected_tail_index(ctx),
            run_id=None,
            run_id_resolver=lambda: self._mint_compaction_run(ctx),
        )
        if ctx.compaction_runs:
            from datetime import UTC, datetime

            _cdb = getattr(ctx.syscall_handler, "db", None)
            for _cr in ctx.compaction_runs:
                _cr.status = "failed" if cr.error else "completed"
                _cr.completed_at = datetime.now(UTC)
            ctx.compaction_runs.clear()
            if _cdb is not None:
                await _cdb.commit()
        # The result always renders the summary exactly once + originals
        ctx.history = ctx.history[:1] + list(cr.messages)
        if cr.error:
            if not force:
                ctx.failed_auto_fingerprints.add(fp)
            return None
        if cr.compacted:
            # Persist FIRST: a CAS loser or DB failure means the stored
            # summary/coverage doesn't reflect this compaction — fail the
            # run rather than continue on unsaved bookkeeping.
            head_ids = conversation.source_ids[: cr.head_count]
            tail_ids = conversation.source_ids[len(conversation.source_ids) - cr.tail_count :]
            _db = getattr(ctx.syscall_handler, "db", None)
            if (
                conversation.session_id
                and _db is not None
                and getattr(ctx.session, "id", None) == conversation.session_id
            ):
                try:
                    _head_ids = {
                        sid
                        for group in conversation.source_ids[: cr.head_count]
                        for sid in (group or set())
                    }
                    _tail_ids = {
                        sid
                        for group in conversation.source_ids[
                            len(conversation.source_ids) - cr.tail_count :
                        ]
                        for sid in (group or set())
                    }
                    stored = await conversation.store_summary(
                        _db,
                        cr.summary,
                        conversation.covered_ids | cr.covered_ids,
                        retained_head_ids=_head_ids,
                        retained_tail_ids=_tail_ids,
                    )
                except Exception:
                    logger.warning(
                        "conversation summary persist failed for session %s",
                        conversation.session_id,
                    )
                    return "Context compaction could not be saved; the run stopped safely."
                if not stored:
                    return (
                        "Context compaction lost a concurrent write conflict; "
                        "the run stopped safely."
                    )
            conversation.messages = list(cr.retained_messages)
            conversation.source_ids = head_ids + tail_ids
            # Local summary update — next render keeps the summary row.
            conversation.summary = cr.summary
            conversation.covered_ids = conversation.covered_ids | cr.covered_ids
        ctx.result.compacted = ctx.result.compacted or cr.compacted
        return None

    async def _budget_gate(self, ctx: _RunState) -> str | None:
        """Per-dispatch full-budget gate. Returns an error message when
        the dispatch must not happen, else None."""
        from .compaction import count_text_tokens, count_tokens, count_tool_tokens

        reserved = count_text_tokens(ctx.system_prompt, ctx.model_str) + count_tool_tokens(
            ctx.tool_schemas, ctx.model_str
        )
        if reserved > ctx.resolved_input_budget:
            # Fixed system/tool schemas alone exceed the hard input
            # budget — no compaction can shrink a fixed section.
            return "Request too large: system context and tool schemas alone exceed the model input budget."
        if ctx.agent_config.compaction.auto_compaction:
            persist_error = await self._apply_compaction(ctx, force=False)
            if persist_error:
                return persist_error
        full = reserved + count_tokens(ctx.history[1:], ctx.model_str)
        ctx.result.context_breakdown = {
            "system_prompt": count_text_tokens(ctx.system_prompt, ctx.model_str),
            "conversation": count_tokens(ctx.history[1:], ctx.model_str),
            "tools": count_tool_tokens(ctx.tool_schemas, ctx.model_str),
        }
        ctx.result.context_tokens = sum(ctx.result.context_breakdown.values())
        if full > ctx.resolved_input_budget:
            return (
                "Context exceeds the model input budget and could not be "
                "compacted — summary generation unavailable."
            )
        return None

    async def _call_model(self, ctx: _RunState):
        """Step 8: dispatch one model call inside the capture scope.

        Returns the response, or None when the turn ended without one —
        ctx.turn_outcome then says how the loop should proceed:
        "retry" (forced compaction succeeded — redo this turn),
        "stop" (compaction could not be persisted — break the loop), or
        "abort" (unrecoverable model error — return the failed result).
        """
        agent_config = ctx.agent_config
        session = ctx.session
        syscall_handler = ctx.syscall_handler
        run_id = ctx.run_id
        result = ctx.result
        trigger = ctx.trigger
        core_snapshot = ctx.core_snapshot
        conversation = ctx.conversation

        # Use streaming if the adapter supports it (LiteLLMAdapter);
        # fall back to non-streaming for ScriptedModel
        call_started = time.monotonic()
        ctx.call_started = call_started
        streamed_call = hasattr(self.model, "complete_stream")
        ctx.streamed_call = streamed_call
        capture_ref = None
        _src_ids: list[str] = []
        for _group in getattr(conversation, "source_ids", []) or []:
            for _sid in _group or []:
                _src_ids.append(_sid)
        _src_ids = sorted(set(_src_ids))
        try:
            with capture_scope(
                run_id=getattr(syscall_handler, "_parent_run_id", None) or run_id,
                session_id=getattr(session, "id", None),
                agent_id=agent_config.id,
                sub_agent_id=getattr(syscall_handler, "_sub_agent_id", None),
                turn=result.total_turns,
                purpose=_call_purpose(trigger),
                core_revision_id=getattr(core_snapshot, "revision_id", None)
                if core_snapshot
                else None,
                core_identity_source_version_id=getattr(
                    core_snapshot, "identity_source_version_id", None
                )
                if core_snapshot
                else None,
                summary_version=getattr(conversation, "summary_version", None),
                conversation_summary_id=getattr(conversation, "summary_id", None),
                coverage_known=bool(getattr(conversation, "coverage_known", False)),
                source_message_ids=_src_ids[:200],
                source_message_ids_total=len(_src_ids),
                source_message_ids_truncated=len(_src_ids) > 200,
                component_budget=getattr(result, "context_breakdown", None) or None,
            ):
                if streamed_call:
                    response = await self._call_streaming(
                        agent_config, ctx.history, ctx.tool_schemas, ctx.event_emitter
                    )
                else:
                    response: ScriptedResponse = await self._complete_with_retry(
                        agent_config, ctx.history, ctx.tool_schemas, ctx.event_emitter
                    )
                    # Emit thinking if present (non-streaming path)
                    if response.thinking and ctx.event_emitter:
                        await self._emit(
                            ctx.event_emitter, "thinking", {"content": response.thinking}
                        )
                capture_ref = getattr(response, "request_capture", None) or (
                    current_capture_scope().get("capture_ref")
                )
        except asyncio.CancelledError:
            await self._record_model_call(
                syscall_handler,
                run_id=run_id,
                agent_config=agent_config,
                session_id=getattr(session, "id", None),
                turn=result.total_turns,
                model_str=ctx.model_str,
                streamed=streamed_call,
                latency_ms=int((time.monotonic() - call_started) * 1000),
                status="interrupted",
                error="CancelledError",
                capture_ref=current_capture_scope().get("capture_ref"),
                purpose=_call_purpose(trigger),
            )
            raise
        except Exception as e:
            # Mid-run context overflow: a tool result or accumulated turns
            # pushed the request over the window after the pre-loop
            # compaction ran. Force-compact once and retry the call —
            # the tail is protected, so if compaction can't shrink it,
            # there is no recovery and the run must fail.
            if ctx.restrictions is None and not ctx.overflow_retried and _is_context_overflow(e):
                ctx.overflow_retried = True
                logger.warning(
                    "Context window exceeded mid-run; forcing compaction and retrying once: %s",
                    str(e)[:200],
                )
                _persist_err = await self._apply_compaction(ctx, force=True)
                if _persist_err:
                    result.status = "failed"
                    result.error = _persist_err
                    ctx.turn_outcome = "stop"
                    return None
                if result.compacted:
                    result.total_turns -= 1  # the retry reuses this turn
                    ctx.turn_outcome = "retry"
                    return None
            _safe_err = (
                type(e).__name__
                if getattr(e, "capture_ref", None) is not None or capture_ref is not None
                else str(e)
            )
            await self._record_model_call(
                syscall_handler,
                run_id=run_id,
                agent_config=agent_config,
                session_id=getattr(session, "id", None),
                purpose=_call_purpose(trigger),
                turn=result.total_turns,
                model_str=ctx.model_str,
                streamed=streamed_call,
                latency_ms=int((time.monotonic() - call_started) * 1000),
                status=(
                    "timeout" if isinstance(e, (TimeoutError, asyncio.TimeoutError)) else "error"
                ),
                error=_safe_err,
                capture_ref=getattr(e, "capture_ref", None) or capture_ref,
            )
            import logging as _log

            _log.getLogger("agentos.harness.loop").exception(
                "Model call failed: model=%s provider=%s",
                agent_config.model.name if agent_config.model else "?",
                agent_config.model.provider_id if agent_config.model else "?",
            )
            result.status = "failed"
            result.error = str(e)
            # Show the actual error to the user instead of a generic message
            error_msg = str(e)
            if "429" in error_msg or "RateLimit" in error_msg or "rate" in error_msg.lower():
                result.final_answer = (
                    "The model is rate-limited right now. Please try again in a moment, "
                    "or select a different model."
                )
            elif isinstance(e, TimeoutError):
                result.final_answer = (
                    "I couldn't complete that request because the model connection "
                    "timed out. Please try again."
                )
            elif "401" in error_msg or "Authentication" in error_msg or "auth" in error_msg.lower():
                result.final_answer = (
                    "Authentication failed — check that the provider API key is valid."
                )
            elif (
                "tool use" in error_msg.lower()
                or "tool_use" in error_msg.lower()
                or "function" in error_msg.lower()
                and "not" in error_msg.lower()
            ):
                result.final_answer = (
                    "This model doesn't support tool use (function calling). "
                    "Please select a model that supports tools, or use a different provider."
                )
            elif _is_context_overflow(e):
                result.final_answer = (
                    "I ran out of context — the conversation plus recent tool "
                    "results exceeded the model's context window and could not "
                    "be compacted far enough. Start a fresh session or use a "
                    "model with a larger context window."
                )
            else:
                # Include the actual error so the user can diagnose the issue
                short_err = error_msg[:200] if len(error_msg) > 200 else error_msg
                result.final_answer = f"I couldn't complete that request. Error: {short_err}"
            # Note: message_complete is emitted by runner.py after the
            # pipeline finishes, with full context metadata (context_tokens,
            # max_context_tokens, etc.). Don't emit it here — the frontend
            # closes the SSE connection on the first message_complete.
            ctx.turn_outcome = "abort"
            return None

        ctx.capture_ref = capture_ref
        return response

    async def _mediate_tool_calls(self, ctx: _RunState, response: ScriptedResponse) -> None:
        """Step 9: mediate this turn's tool calls through the syscall layer.

        Normalizes call ids, appends the assistant row, emits pending/running
        events, dispatches calls concurrently (bounded for restricted runs),
        then folds results back into history/conversation in order.
        """
        agent_config = ctx.agent_config
        session = ctx.session
        syscall_handler = ctx.syscall_handler
        run_id = ctx.run_id
        result = ctx.result
        trigger = ctx.trigger
        conversation = ctx.conversation
        history = ctx.history
        event_emitter = ctx.event_emitter

        # Normalize call ids ONCE — the assistant history row and the
        # ToolCall objects must share the same ids.
        for tc in response.tool_calls:
            if not tc.get("id"):
                tc["id"] = str(uuid.uuid4())
        # Add the assistant message with tool_calls to history FIRST
        # (must precede the tool result messages for OpenAI API compliance)
        _assistant_batch = {
            "role": "assistant",
            "content": response.content or "",
            "tool_calls": [
                {
                    "id": tc["id"],
                    "type": "function",
                    "function": {
                        "name": tc["name"],
                        "arguments": json.dumps(tc.get("args", {})),
                    },
                }
                for tc in response.tool_calls
            ],
        }
        history.append(_assistant_batch)
        conversation.append(_assistant_batch)
        _batch_conv_idx = len(conversation.source_ids) - 1

        # Build ToolCall objects
        calls = [
            ToolCall(
                id=tc["id"],
                name=tc["name"],
                args=tc.get("args", {}),
            )
            for tc in response.tool_calls
        ]

        # Emit pending + running events for all calls (in order, before any execution)
        if event_emitter:
            for call in calls:
                await self._emit(
                    event_emitter,
                    "tool_call",
                    {
                        "id": call.id,
                        "capability": call.name,
                        "args": call.args,
                        "status": "pending",
                    },
                )
            for call in calls:
                await self._emit(
                    event_emitter,
                    "tool_call",
                    {
                        "id": call.id,
                        "capability": call.name,
                        "args": call.args,
                        "status": "running",
                    },
                )

        # Release any open write txn before dispatch — tool calls can
        # block for minutes (terminal sleep, MCP calls); a SQLite
        # writer lock held across them starves every other run's
        # writes under concurrency (B31).
        _loop_db = getattr(syscall_handler, "db", None)
        if _loop_db is not None:
            await _loop_db.commit()

        # Dispatch all tool calls concurrently within this reasoning step.
        # Restricted runs bound concurrency (not count) and skip the
        # full-response approval barrier — the mediator denies
        # approval-needing tools outright, and a barrier would
        # deadlock while slots drain oversized batches.
        approval_batch = (
            _approval_batch_for(agent_config, session, calls) if ctx.restrictions is None else None
        )
        _gate = (
            asyncio.Semaphore(max(1, ctx.restrictions.max_concurrent_tool_calls))
            if ctx.restrictions is not None
            else None
        )

        async def _mediate_one(call: ToolCall) -> SyscallResult:
            if _gate is not None:
                async with _gate:
                    return await syscall_handler.mediate(
                        call=call,
                        session=session,
                        agent_config=agent_config,
                        run_id=run_id,
                        event_emitter=event_emitter,
                        capability_catalog=ctx.capability_catalog,
                        approval_batch=approval_batch,
                        trigger=trigger,
                    )
            return await syscall_handler.mediate(
                call=call,
                session=session,
                agent_config=agent_config,
                run_id=run_id,
                event_emitter=event_emitter,
                capability_catalog=ctx.capability_catalog,
                approval_batch=approval_batch,
                trigger=trigger,
            )

        syscall_results = await asyncio.gather(*[_mediate_one(c) for c in calls])

        # Process results in order (to maintain history ordering)
        for call, syscall_result in zip(calls, syscall_results, strict=True):
            # Emit the outcome: complete, denied, failed, timeout,
            # or interrupted — the caller sees *how* a call ended.
            if event_emitter:
                _receipt = await self._emit(
                    event_emitter,
                    "tool_call",
                    {
                        "id": call.id,
                        "capability": call.name,
                        "args": call.args,
                        "status": tool_event_status(syscall_result.status),
                        "result": syscall_result.output,
                        # denied_reason so the UI and the audit row
                        # report the same failure/denial cause.
                        "reason": syscall_result.denied_reason,
                        "approval_batch_id": approval_batch.id if approval_batch else None,
                        "approval_batch_size": approval_batch.size if approval_batch else None,
                    },
                )
                if isinstance(_receipt, dict):
                    ctx.call_receipts[call.id] = _receipt

            result.tool_calls_made.append(
                {
                    "id": call.id,
                    "name": call.name,
                    "args": call.args,
                    "allowed": syscall_result.allowed,
                    "status": syscall_result.status,
                    "result": syscall_result.output,
                }
            )

            # Add tool result to history
            if syscall_result.allowed:
                output = syscall_result.output
                # Track consecutive failures (empty/error results)
                is_empty = (
                    output is None
                    or output == ""
                    or (isinstance(output, dict) and output.get("results") == [])
                )
                if is_empty:
                    ctx.consecutive_tool_failures += 1
                else:
                    ctx.consecutive_tool_failures = 0
                content: Any = (
                    syscall_result.model_content
                    if syscall_result.model_content is not None
                    else json.dumps(output)
                    if output
                    else ""
                )
                if isinstance(content, str) and len(content) > TOOL_RESULT_MAX_CHARS:
                    content = (
                        content[:TOOL_RESULT_MAX_CHARS]
                        + f"\n\n[truncated — result was {len(content)} chars; "
                        f"the {TOOL_RESULT_MAX_CHARS}-char limit applies. "
                        "Narrow the call or page through the data.]"
                    )
                _tool_row = {
                    "role": "tool",
                    "content": content,
                    "tool_call_id": call.id,
                    "name": call.name,
                }
                history.append(_tool_row)
                _rid = ctx.call_receipts.get(call.id) or {}
                conversation.append(
                    _tool_row,
                    {_rid["tool_message_id"]} if _rid.get("tool_message_id") else set(),
                )
            else:
                ctx.consecutive_tool_failures += 1
                # Tell the model *how* the call ended — a denial is a
                # policy decision, an error/timeout is a failure.
                prefix = {
                    "denied": "Denied",
                    "timeout": "Timed out",
                    "interrupted": "Interrupted",
                }.get(syscall_result.status, "Error")
                _tool_row = {
                    "role": "tool",
                    "content": f"{prefix}: {syscall_result.denied_reason}",
                    "tool_call_id": call.id,
                    "name": call.name,
                }
                history.append(_tool_row)
                _rid = ctx.call_receipts.get(call.id) or {}
                conversation.append(
                    _tool_row,
                    {_rid["tool_message_id"]} if _rid.get("tool_message_id") else set(),
                )

        # Coverage bookkeeping: the assistant batch row is covered by
        # every persisted tool row plus the flushed narration row.
        _batch_ids: set[str] = set()
        for _cid in (c.id for c in calls):
            _rc = ctx.call_receipts.get(_cid) or {}
            if _rc.get("tool_message_id"):
                _batch_ids.add(_rc["tool_message_id"])
            if _rc.get("assistant_message_id"):
                _batch_ids.add(_rc["assistant_message_id"])
        if _batch_ids:
            conversation.source_ids[_batch_conv_idx] = _batch_ids

        # Stop if too many consecutive tool failures
        if ctx.consecutive_tool_failures >= ctx.max_consecutive_failures:
            _note_row = {
                "role": "user",
                "content": f"Note: {ctx.consecutive_tool_failures} consecutive tool calls returned empty or failed results. Stop calling tools and respond with what you know.",
            }
            history.append(_note_row)
            conversation.append(_note_row)

        # Emit turn_complete
        result.loaded_capabilities = sorted(ctx.capability_catalog.loaded)
        if event_emitter:
            await self._emit(
                event_emitter,
                "turn_complete",
                {
                    "turn_number": result.total_turns,
                    "tokens_in": response.tokens_in,
                    "tokens_out": response.tokens_out,
                    "cached_tokens": response.cached_tokens,
                    "cost": response.cost,
                    "loaded_capabilities": list(result.loaded_capabilities),
                    "context_breakdown": dict(result.context_breakdown),
                    "context_tokens": result.context_tokens,
                    "max_context_tokens": result.max_context_tokens,
                    "compacted": result.compacted,
                },
            )

    async def _finalize_answer(self, ctx: _RunState, response: ScriptedResponse) -> None:
        """No tool calls — this is the final answer: append the assistant row,
        apply output guardrails, and emit the turn's closing events."""
        result = ctx.result
        event_emitter = ctx.event_emitter

        # Add the assistant message to history
        _final_row = {"role": "assistant", "content": response.content or ""}
        ctx.history.append(_final_row)
        ctx.conversation.append(_final_row)
        # Apply guardrails before emitting to the user (D2)
        guardrail_result = apply_guardrails(response.content)
        result.final_answer = guardrail_result.content
        result.guardrail_warnings = guardrail_result.warnings
        result.guardrail_redactions = guardrail_result.redactions

        # Emit turn_complete for the final turn
        # (tokens were already streamed via _call_streaming if streaming)
        if event_emitter:
            if not hasattr(self.model, "complete_stream"):
                # Non-streaming path: emit the guardrailed content as one token event
                await self._emit(event_emitter, "token", {"content": guardrail_result.content})
            else:
                # Streaming path: tokens were already emitted raw during streaming.
                # If guardrails modified the content, emit a correction event so
                # the frontend can replace the streamed output with the clean version.
                if guardrail_result.content != response.content:
                    await self._emit(
                        event_emitter,
                        "guardrail_correction",
                        {"content": guardrail_result.content},
                    )
            # Emit guardrail warnings (if any) so the UI can show a notice
            if guardrail_result.warnings:
                await self._emit(
                    event_emitter,
                    "guardrail_warning",
                    {"warnings": guardrail_result.warnings},
                )
            await self._emit(
                event_emitter,
                "turn_complete",
                {
                    "turn_number": result.total_turns,
                    "tokens_in": response.tokens_in,
                    "tokens_out": response.tokens_out,
                    "cached_tokens": response.cached_tokens,
                    "cost": response.cost,
                    "loaded_capabilities": list(result.loaded_capabilities),
                    "context_breakdown": dict(result.context_breakdown),
                    "context_tokens": result.context_tokens,
                    "max_context_tokens": result.max_context_tokens,
                    "compacted": result.compacted,
                },
            )

    async def _record_model_call(
        self,
        syscall_handler: Any,
        *,
        run_id: str,
        agent_config: AgentConfig,
        turn: int,
        model_str: str,
        streamed: bool,
        latency_ms: int,
        status: str,
        tokens_in: int = 0,
        tokens_out: int = 0,
        cached_tokens: int | None = None,
        thinking_tokens: int | None = None,
        cost: float = 0.0,
        cost_source: str | None = None,
        cost_receipt: dict | None = None,
        error: str | None = None,
        capture_ref: Any = None,
        session_id: str | None = None,
        purpose: str = "reasoning",
    ) -> None:
        """Write one ModelCall row per model request (v0.2 foundations).

        When a capture reference carries a per-attempt latency, it wins —
        the caller's broad timer would double-charge a retried call.

        Best-effort accounting on its OWN session (sub-agent handlers carry
        the parent's run id and their own sub-agent id): a write on the run's
        session would open the SQLite write txn it holds across whatever the
        run does next — tool calls can block for minutes, starving every
        other writer under concurrency (B31). A fresh session + lock-retry
        keeps the write short and can never poison the run's session.
        """
        if getattr(syscall_handler, "db", None) is None:
            return
        try:
            from ..db import persist_fresh_session
            from ..models.model_call import ModelCall

            record_run_id = getattr(syscall_handler, "_parent_run_id", None) or run_id
            sub_agent_id = getattr(syscall_handler, "_sub_agent_id", None)
            capture_id = getattr(capture_ref, "id", None) if capture_ref is not None else None
            row = ModelCall(
                id=capture_id or str(uuid.uuid4()),
                run_id=record_run_id,
                session_id=session_id,
                agent_id=agent_config.id,
                sub_agent_id=sub_agent_id,
                turn=turn,
                kind="chat",
                purpose=purpose,
                provider_id=agent_config.model.provider_id if agent_config.model else None,
                model_name=agent_config.model.name if agent_config.model else None,
                model_str=model_str or None,
                streamed=streamed,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                cached_tokens=cached_tokens,
                thinking_tokens=thinking_tokens,
                cost=cost,
                latency_ms=(
                    getattr(capture_ref, "latency_ms", None)
                    if getattr(capture_ref, "latency_ms", None) is not None
                    else latency_ms
                ),
                status=status,
                error=error[:2000] if error else None,
                detail={
                    **({"cost_source": cost_source} if cost_source is not None else {}),
                    **(cost_receipt or {}),
                    **(
                        {
                            "capture_id": getattr(capture_ref, "id", None),
                            "capture_state": getattr(capture_ref, "state", None),
                            "capture_surface": getattr(capture_ref, "surface", None),
                        }
                        if capture_ref is not None
                        else {}
                    ),
                }
                or None,
            )

            async def _persist(db: Any) -> None:
                existing = await db.get(ModelCall, row.id)
                if existing is None:
                    db.add(row)
                else:
                    for field in (
                        "run_id",
                        "agent_id",
                        "sub_agent_id",
                        "turn",
                        "kind",
                        "purpose",
                        "provider_id",
                        "model_name",
                        "model_str",
                        "streamed",
                        "tokens_in",
                        "tokens_out",
                        "cached_tokens",
                        "thinking_tokens",
                        "cost",
                        "latency_ms",
                        "status",
                        "error",
                        "detail",
                    ):
                        new_val = getattr(row, field)
                        if new_val is None:
                            continue
                        setattr(existing, field, new_val)

            await persist_fresh_session(_persist, f"model_call:{record_run_id}:{turn}")
        except Exception:
            import logging as _log

            _log.getLogger("agentos.harness.loop").debug(
                "Could not record model call for run %s", run_id
            )

    async def _emit(self, emitter: EventEmitter, event_type: str, payload: dict[str, Any]) -> Any:
        """Safely emit an SSE event; returns the emitter's result (persisting
        emitters hand back a receipt with stored Message ids)."""
        if emitter is None:
            return None
        result = emitter(event_type, payload)
        if hasattr(result, "__await__"):
            result = await result
        return result

    async def _emit_model_retry(
        self, event_emitter: EventEmitter, attempt: int, delay_s: float
    ) -> None:
        """Tell the UI a transient model-call failure is being retried."""
        await self._emit(
            event_emitter,
            "model_retry",
            {
                "attempt": attempt + 2,
                "max_attempts": len(_MODEL_RETRY_DELAYS_S) + 1,
                "delay_s": delay_s,
            },
        )

    async def _complete_with_retry(
        self,
        agent_config: AgentConfig,
        history: list[dict[str, str]],
        tool_schemas: list[dict[str, Any]],
        event_emitter: EventEmitter,
    ) -> ScriptedResponse:
        """Non-streaming complete with bounded retry on transient errors.
        Safe to retry — nothing is emitted or executed until it returns."""
        for attempt in range(len(_MODEL_RETRY_DELAYS_S) + 1):
            try:
                return await self.model.complete(
                    agent_model=agent_config.model,
                    messages=history,
                    tools=tool_schemas,
                )
            except Exception as e:
                if attempt == len(_MODEL_RETRY_DELAYS_S) or not _is_transient_model_error(e):
                    raise
                delay = _MODEL_RETRY_DELAYS_S[attempt]
                logger.warning(
                    "Transient model error (attempt %d), retrying in %.0fs: %s",
                    attempt + 1,
                    delay,
                    str(e)[:200],
                )
                await self._emit_model_retry(event_emitter, attempt, delay)
                await asyncio.sleep(delay)
        raise AssertionError("unreachable")

    async def _call_streaming(
        self,
        agent_config: AgentConfig,
        history: list[dict[str, str]],
        tool_schemas: list[dict[str, Any]],
        event_emitter: EventEmitter,
    ) -> ScriptedResponse:
        """Call the model with streaming, emitting token/thinking events as they arrive.

        Retries transient failures only before the first delta reaches the
        UI — once content has streamed, restarting would duplicate it."""
        response: ScriptedResponse | None = None
        emitted_output = False
        for attempt in range(len(_MODEL_RETRY_DELAYS_S) + 1):
            try:
                async for delta_type, content in self.model.complete_stream(
                    agent_model=agent_config.model,
                    messages=history,
                    tools=tool_schemas,
                ):
                    if delta_type in ("token", "thinking", "tool_call_progress"):
                        emitted_output = True
                    if delta_type == "token" and event_emitter:
                        await self._emit(event_emitter, "token", {"content": content})
                    elif delta_type == "thinking" and event_emitter:
                        await self._emit(event_emitter, "thinking", {"content": content})
                    elif delta_type == "tool_call_progress" and event_emitter:
                        await self._emit(event_emitter, "tool_call_progress", content)
                    elif delta_type == "done":
                        response = content
                break
            except Exception as e:
                if (
                    emitted_output
                    or attempt == len(_MODEL_RETRY_DELAYS_S)
                    or not _is_transient_model_error(e)
                ):
                    raise
                delay = _MODEL_RETRY_DELAYS_S[attempt]
                logger.warning(
                    "Transient model stream error (attempt %d), retrying in %.0fs: %s",
                    attempt + 1,
                    delay,
                    str(e)[:200],
                )
                await self._emit_model_retry(event_emitter, attempt, delay)
                await asyncio.sleep(delay)

        if response is None:
            raise RuntimeError("Streaming ended without a 'done' event")
        return response
