"""Syscall layer — the single boundary every capability call crosses (I2, I3, I4).

Protocol interface (D10 — the subject is never model-supplied).
"""

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass
class ToolCall:
    """A tool call from the model."""

    id: str
    name: str
    args: dict[str, Any]


@dataclass
class SyscallResult:
    """Result of a mediated syscall."""

    output: Any = None
    allowed: bool = True
    denied_reason: str | None = None
    cost: float = 0.0
    latency_ms: int = 0
    audit_id: str | None = None
    # Optional provider-native content to add to the next model request.
    # Normal tool output remains safe for the UI and audit log.
    model_content: Any = None


class SyscallHandler(Protocol):
    """Protocol for the syscall handler.

    Decision 1: harness depends on interface, not concrete impl.
    """

    async def mediate(
        self,
        call: ToolCall,
        session: Any,  # Session model
        agent_config: Any,  # AgentConfig
        run_id: str,
        is_sub_agent: bool = False,
        sub_agent_id: str | None = None,
        event_emitter: Any = None,
        capability_catalog: Any = None,
    ) -> SyscallResult: ...
