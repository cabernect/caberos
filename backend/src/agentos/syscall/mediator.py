"""Syscall mediator — the real implementation of the mediation pipeline.

For ticket 01 (smoke test), this is a stub that auto-approves all calls
and writes audit records. The full implementation (approval flow, scope
narrowing, credential injection) comes in later tickets.
"""

import json
import time
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ..capabilities.registry import registry
from ..config_schema import AgentConfig
from ..models.audit import AuditRecord
from .protocol import SyscallResult, ToolCall


class StubSyscallHandler:
    """Stub syscall handler that auto-approves all calls (ticket 01).

    The real implementation (plan 04) adds: subject resolution, scope narrowing,
    approval flow, credential injection. For the tracer bullet, we auto-approve
    everything and just execute + audit.
    """

    def __init__(self, db: AsyncSession, workspace_path: str) -> None:
        self.db = db
        self.workspace_path = workspace_path

    async def mediate(
        self,
        call: ToolCall,
        session: Any,
        agent_config: AgentConfig,
        run_id: str,
        is_sub_agent: bool = False,
        sub_agent_id: str | None = None,
        event_emitter: Any = None,
    ) -> SyscallResult:
        start = time.monotonic()

        # 1. Resolve capability
        cap = registry.get(call.name)
        if cap is None:
            return self._deny(
                run_id, call, agent_config, "capability not found", start, sub_agent_id
            )

        # 2. Check grant (for the stub, we trust the agent config)
        granted_names = {g.name for g in agent_config.capabilities}
        if call.name not in granted_names:
            return self._deny(run_id, call, agent_config, "not granted", start, sub_agent_id)

        # 3. Execute (no approval flow in stub — auto-approve)
        try:
            result = await cap.execute(
                args=call.args,
                workspace_path=self.workspace_path,
            )
            elapsed = int((time.monotonic() - start) * 1000)

            # 4. Write audit record
            audit = AuditRecord(
                id=str(uuid.uuid4()),
                run_id=run_id,
                agent_id=agent_config.id,
                sub_agent_id=sub_agent_id,
                capability_name=call.name,
                subject_contact_id=None,  # stub doesn't resolve subject yet
                allowed=True,
                denied_reason=None,
                cost=0.0,
                latency_ms=elapsed,
                args=json.dumps(call.args),
                result=json.dumps(result) if result else None,
            )
            self.db.add(audit)
            await self.db.flush()

            return SyscallResult(
                output=result,
                allowed=True,
                cost=0.0,
                latency_ms=elapsed,
                audit_id=audit.id,
            )
        except Exception as e:
            elapsed = int((time.monotonic() - start) * 1000)
            return self._deny(
                run_id, call, agent_config, f"execution error: {e}", start, sub_agent_id
            )

    def _deny(
        self,
        run_id: str,
        call: ToolCall,
        agent_config: AgentConfig,
        reason: str,
        start: float,
        sub_agent_id: str | None = None,
    ) -> SyscallResult:
        elapsed = int((time.monotonic() - start) * 1000)
        # Write denied audit record
        audit = AuditRecord(
            id=str(uuid.uuid4()),
            run_id=run_id,
            agent_id=agent_config.id,
            sub_agent_id=sub_agent_id,
            capability_name=call.name,
            allowed=False,
            denied_reason=reason,
            cost=0.0,
            latency_ms=elapsed,
            args=json.dumps(call.args),
        )
        self.db.add(audit)
        return SyscallResult(
            output=None,
            allowed=False,
            denied_reason=reason,
            cost=0.0,
            latency_ms=elapsed,
        )
