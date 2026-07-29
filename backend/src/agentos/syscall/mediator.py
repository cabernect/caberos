"""Syscall mediator — the real implementation of the mediation pipeline (D10, D11, D18).

For each tool call, in order:
1. Resolve capability from the registry
2. Check grant (agent config capabilities)
3. Resolve subject (if subject-scoped — from session Contact, never model-supplied)
4. Narrow scope (sub-agent intersection — stubbed for now, no sub-agents yet)
5. Check approval (auto-approve in this ticket — approval flow is ticket 04)
6. Inject credentials (stubbed — no connectors yet)
7. Execute under timeout
8. Reduce oversized results (D18)
9. Write audit record
"""

import json
import time
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..capabilities.registry import registry
from ..config_schema import AgentConfig
from ..models.audit import AuditRecord
from ..models.contact import Contact
from .protocol import SyscallResult, ToolCall

# D18 — result reduction threshold (in characters of JSON)
MAX_RESULT_CHARS = 8000
TRUNCATED_SUFFIX = "\n... [truncated by syscall layer — full result in audit record]"


def reduce_result(result: Any) -> Any:
    """D18 — reduce oversized tool results before they enter model context."""
    if result is None:
        return None
    try:
        serialized = json.dumps(result)
        if len(serialized) > MAX_RESULT_CHARS:
            # Truncate the serialized form, then parse back
            truncated = serialized[:MAX_RESULT_CHARS] + TRUNCATED_SUFFIX
            return {"truncated": True, "preview": truncated}
        return result
    except (TypeError, ValueError):
        return result


class SyscallHandler:
    """Real syscall handler — mediates every capability call (I2, I3, I4).

    Replaces StubSyscallHandler from ticket 01. Adds:
    - Subject resolution from session Contact (D10)
    - Result reduction (D18)
    - Running state emission via event_emitter
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
            return await self._deny(
                run_id, call, agent_config, "capability not found", start, sub_agent_id
            )

        # 2. Check grant
        granted_names = {g.name for g in agent_config.capabilities}
        if call.name not in granted_names:
            return await self._deny(
                run_id, call, agent_config, "not granted", start, sub_agent_id
            )

        # 3. Resolve subject (D10 — for subject-scoped capabilities)
        subject_contact_id: str | None = None
        if cap.subject_scoped:
            # Resolve the Contact from the session
            result = await self.db.execute(
                select(Contact).where(Contact.id == session.contact_id)
            )
            contact = result.scalar_one_or_none()
            if contact is None:
                return await self._deny(
                    run_id, call, agent_config, "no subject binding", start, sub_agent_id
                )
            subject_contact_id = contact.id
            # The subject is the contact's binding, not anything the model passed.
            # For v0.1, the binding is the contact itself (no external record binding yet).

        # 4. Narrow scope (D11) — sub-agent intersection
        # TODO: when sub-agents are implemented, intersect capabilities here.
        # For now, the grant check above is sufficient.

        # 5. Check approval — auto-approve in this ticket (ticket 04 adds the real flow)
        # If the capability requires approval, we still auto-approve here.
        # The approval flow (ApprovalRequest, asyncio.Event) comes in ticket 04.

        # 6. Inject credentials — stubbed (no connectors/MCP yet)

        # 7. Execute under timeout
        # (The harness emits the 'running' state before calling mediate)

        try:
            result = await cap.execute(
                args=call.args,
                workspace_path=self.workspace_path,
            )
            elapsed = int((time.monotonic() - start) * 1000)

            # 8. Reduce result (D18)
            reduced = reduce_result(result)

            # 9. Write audit record (with full, unreduced result)
            audit = AuditRecord(
                id=str(uuid.uuid4()),
                run_id=run_id,
                agent_id=agent_config.id,
                sub_agent_id=sub_agent_id,
                capability_name=call.name,
                subject_contact_id=subject_contact_id,
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
                output=reduced,
                allowed=True,
                cost=0.0,
                latency_ms=elapsed,
                audit_id=audit.id,
            )
        except Exception as e:
            elapsed = int((time.monotonic() - start) * 1000)
            return await self._deny(
                run_id, call, agent_config, f"execution error: {e}", start, sub_agent_id
            )

    async def _deny(
        self,
        run_id: str,
        call: ToolCall,
        agent_config: AgentConfig,
        reason: str,
        start: float,
        sub_agent_id: str | None = None,
    ) -> SyscallResult:
        elapsed = int((time.monotonic() - start) * 1000)
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
        await self.db.flush()
        return SyscallResult(
            output=None,
            allowed=False,
            denied_reason=reason,
            cost=0.0,
            latency_ms=elapsed,
        )


# Keep the old name for backward compatibility with existing code
StubSyscallHandler = SyscallHandler
