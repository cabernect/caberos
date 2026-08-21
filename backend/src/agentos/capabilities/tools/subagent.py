"""Sub-agent tools — run_subagent and read_subagent.

run_subagent spawns a throwaway sub-agent that runs in-memory (not persisted).
By default it blocks until the sub-agent finishes and returns the result.
Set async=true to run in the background — returns a subagent_id you can poll
with read_subagent.

All capabilities are kind="tool" — no special sub_agent kind.
"""

import asyncio
import uuid
from dataclasses import dataclass
from typing import Any

from ...config_schema import AgentConfig, CapabilityGrant, Limits, ModelConfig
from ..registry import CapabilityDef, registry


@dataclass
class SubAgentTask:
    """Tracks a background sub-agent execution."""

    subagent_id: str
    task: str
    status: str = "running"  # running, done, failed
    result: dict[str, Any] | None = None
    asyncio_task: asyncio.Task | None = None


# In-memory registry of background sub-agents (process-global, like approval_registry)
_subagent_registry: dict[str, SubAgentTask] = {}


async def run_subagent(
    args: dict[str, Any],
    workspace_path: str = "",
    **kwargs: Any,
) -> dict[str, Any]:
    """Run a sub-agent for a one-off task.

    Args:
        task: What the sub-agent should do (required).
        async: If true, return subagent_id immediately and run in background.
        soul: Optional identity override.
        capabilities: Optional list of capability names. Use "*" to inherit parent's.
        model: Optional model override.

    Returns (sync mode):
        {"result": "...", "turns": N, "tokens_in": N, "tokens_out": N, "cost": N}
    Returns (async mode):
        {"subagent_id": "...", "status": "running"}
    """
    task_str = args.get("task", "").strip()
    if not task_str:
        return {"error": "task is required"}

    is_async = args.get("async", False)
    subagent_id = f"sub-{uuid.uuid4().hex[:8]}"

    if is_async:
        # Launch in background
        sa_task = SubAgentTask(subagent_id=subagent_id, task=task_str)
        _subagent_registry[subagent_id] = sa_task

        sa_task.asyncio_task = asyncio.create_task(
            _execute_subagent(subagent_id, args, workspace_path, kwargs)
        )

        return {"subagent_id": subagent_id, "status": "running"}

    # Sync mode — block until done
    return await _execute_subagent(subagent_id, args, workspace_path, kwargs)


async def read_subagent(
    args: dict[str, Any],
    workspace_path: str = "",
    **kwargs: Any,
) -> dict[str, Any]:
    """Read the status/result of a background sub-agent.

    Returns:
        {"status": "running"} if still running
        {"status": "done", "result": {...}} if finished
        {"status": "failed", "error": "..."} if failed
    """
    subagent_id = args.get("subagent_id", "")
    sa_task = _subagent_registry.get(subagent_id)
    if sa_task is None:
        return {"error": f"subagent not found: {subagent_id}"}

    if sa_task.status == "running":
        return {"subagent_id": subagent_id, "status": "running"}

    # Done or failed — return result and clean up
    result = sa_task.result or {"error": "no result"}
    result["subagent_id"] = subagent_id
    result["status"] = sa_task.status
    del _subagent_registry[subagent_id]
    return result


async def _execute_subagent(
    subagent_id: str,
    args: dict[str, Any],
    workspace_path: str,
    kwargs: dict[str, Any],
) -> dict[str, Any]:
    """Execute a sub-agent and return its result."""
    task_str = args.get("task", "").strip()
    parent_config: AgentConfig | None = kwargs.get("parent_config")
    spawn_context: dict = kwargs.get("_spawn_context", {})
    parent_harness = spawn_context.get("harness")
    parent_syscall_handler = spawn_context.get("syscall_handler")
    parent_session = spawn_context.get("session")
    parent_run_id = spawn_context.get("run_id")
    event_emitter = spawn_context.get("event_emitter")

    if parent_harness is None or parent_config is None:
        return {"error": "run_subagent is only available inside a running agent"}

    # Determine capabilities
    caps_arg = args.get("capabilities", [])
    if caps_arg == "*":
        sub_caps = (
            list(parent_config.capabilities) if parent_config.capabilities is not None else []
        )
    elif isinstance(caps_arg, list) and caps_arg:
        sub_caps = [CapabilityGrant(name=name) for name in caps_arg]
    else:
        # Default: safe file tools + search + datetime
        sub_caps = [
            CapabilityGrant(name="read_file"),
            CapabilityGrant(name="write_file"),
            CapabilityGrant(name="search_files"),
            CapabilityGrant(name="datetime_now"),
        ]

    # Determine model — default to parent's
    model_arg = args.get("model")
    if isinstance(model_arg, dict) and model_arg.get("provider_id"):
        sub_model = ModelConfig(
            provider_id=model_arg["provider_id"],
            name=model_arg.get("name", ""),
        )
    else:
        sub_model = parent_config.model

    # Build soul — default to a focused task-oriented soul
    soul = args.get("soul", "").strip()
    if not soul:
        soul = (
            "You are a focused sub-agent spawned for a single task. "
            "Do the task efficiently and return your result. "
            "Do not ask questions — make reasonable assumptions. "
            "Be concise and direct."
        )

    sub_config = AgentConfig(
        id=subagent_id,
        name=f"SubAgent-{subagent_id[:8]}",
        model=sub_model,
        soul=soul,
        persona="Direct, concise, task-focused. No filler.",
        task=task_str,
        capabilities=sub_caps,
        limits=Limits(
            max_turns_per_run=10,
            max_context_tokens=16000,
            max_cost_per_run=0.50,
        ),
        workspace=workspace_path,
        sandbox_mode=parent_config.sandbox_mode,
    )

    sub_syscall = _SubAgentSyscallHandler(
        parent_handler=parent_syscall_handler,
        sub_agent_id=subagent_id,
        parent_run_id=parent_run_id,
        parent_config=parent_config,
    )

    # Wrap the event emitter so sub-agent events are tagged with subagent_id.
    # This lets the frontend nest sub-agent streaming (thinking, tokens, tool calls)
    # under the parent's run_subagent tool call block.
    tagged_emitter = _make_tagged_emitter(event_emitter, subagent_id)

    try:
        result = await parent_harness.run(
            agent_config=sub_config,
            session=parent_session,
            message=task_str,
            syscall_handler=sub_syscall,
            run_id=f"{parent_run_id}:{subagent_id}",
            recent_messages=[],
            trigger="user_message",
            event_emitter=tagged_emitter,
        )

        return {
            "result": result.final_answer or "(sub-agent produced no output)",
            "turns": result.total_turns,
            "tokens_in": result.tokens_in,
            "tokens_out": result.tokens_out,
            "cost": result.total_cost,
            "status": result.status,
        }
    except Exception as e:
        return {"error": f"sub-agent failed: {e}", "result": ""}


def _make_tagged_emitter(parent_emitter: Any, subagent_id: str) -> Any:
    """Wrap the parent event emitter so sub-agent events are tagged.

    Every event emitted by the sub-agent gets an extra `subagent_id` field
    in its payload. The frontend uses this to nest sub-agent streaming
    (thinking, tokens, tool calls) under the parent's run_subagent block.
    """
    if parent_emitter is None:
        return None

    async def tagged_emitter(event_type: str, payload: dict[str, Any]) -> None:
        tagged = {**payload, "subagent_id": subagent_id}
        result = parent_emitter(event_type, tagged)
        if hasattr(result, "__await__"):
            await result

    return tagged_emitter


class _SubAgentSyscallHandler:
    """Wrapper around the parent's syscall handler that injects sub_agent_id."""

    def __init__(
        self,
        parent_handler: Any,
        sub_agent_id: str,
        parent_run_id: str,
        parent_config: Any = None,
    ) -> None:
        self._parent = parent_handler
        self._sub_agent_id = sub_agent_id
        self._parent_run_id = parent_run_id
        self._parent_config = parent_config

    @property
    def workspace_path(self) -> str:
        return self._parent.workspace_path

    @property
    def sandbox_mode(self) -> str:
        return self._parent.sandbox_mode

    @property
    def db(self) -> Any:
        return self._parent.db

    async def mediate(
        self,
        call: Any,
        session: Any,
        agent_config: Any,
        run_id: str,
        is_sub_agent: bool = True,
        sub_agent_id: str | None = None,
        event_emitter: Any = None,
        parent_config: Any = None,
    ) -> Any:
        # Use the parent config passed at construction time, or the one
        # passed to this call (for nested sub-agents)
        effective_parent = parent_config or self._parent_config
        return await self._parent.mediate(
            call=call,
            session=session,
            agent_config=agent_config,
            run_id=self._parent_run_id,
            is_sub_agent=True,
            sub_agent_id=self._sub_agent_id,
            event_emitter=event_emitter,
            parent_config=effective_parent,
        )


def register_subagent_tools() -> None:
    """Register run_subagent and read_subagent capabilities."""

    registry.register(
        CapabilityDef(
            name="run_subagent",
            kind="tool",
            description=(
                "Run a sub-agent for a one-off task. The sub-agent runs independently "
                "with its own context and tool loop, shares your workspace and model, "
                "and returns its result when done. By default blocks until the sub-agent "
                "finishes. Set async=true to run in the background — returns a subagent_id "
                "you can poll with read_subagent. Multiple sub-agents in one turn run in "
                "parallel. When you delegate a task, do NOT also do it yourself — wait for "
                "the sub-agent's result."
            ),
            parameters_schema={
                "type": "object",
                "properties": {
                    "task": {
                        "type": "string",
                        "description": "What the sub-agent should do. Be specific — "
                        "the sub-agent starts with no context other than this task.",
                    },
                    "async": {
                        "type": "boolean",
                        "description": "If true, run in background and return subagent_id immediately. "
                        "Use read_subagent to poll for the result.",
                        "default": False,
                    },
                    "soul": {
                        "type": "string",
                        "description": "Optional identity override for the sub-agent. "
                        "Defaults to a focused, task-oriented agent that doesn't ask questions.",
                    },
                    "capabilities": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Capability names to grant the sub-agent. "
                        "Defaults to read_file, write_file, search_files, datetime_now. "
                        "Use '*' to inherit the parent's capabilities.",
                    },
                    "model": {
                        "type": "object",
                        "properties": {
                            "provider_id": {"type": "string"},
                            "name": {"type": "string"},
                        },
                        "description": "Optional model override. Defaults to the parent's model.",
                    },
                },
                "required": ["task"],
            },
            egress=False,
            require_approval=False,
            subject_scoped=False,
            execute=run_subagent,
        )
    )

    registry.register(
        CapabilityDef(
            name="read_subagent",
            kind="tool",
            description=(
                "Read the status and result of a background sub-agent. "
                "Returns status='running' if still executing, or the final result if done."
            ),
            parameters_schema={
                "type": "object",
                "properties": {
                    "subagent_id": {
                        "type": "string",
                        "description": "Sub-agent ID from run_subagent(async=true)",
                    },
                },
                "required": ["subagent_id"],
            },
            egress=False,
            require_approval=False,
            subject_scoped=False,
            execute=read_subagent,
        )
    )
