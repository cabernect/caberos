"""Syscall mediator — the real implementation of the mediation pipeline (D10, D11).

For each tool call, in order:
1. Resolve capability from the registry
2. Check grant (agent config capabilities)
3. Resolve subject (if subject-scoped — from session Contact, never model-supplied)
4. Narrow scope (sub-agent intersection — stubbed for now, no sub-agents yet)
5. Check approval — if require_approval on the grant or capability def,
   create an ApprovalRequest, emit a pending_approval event, and block
   on an asyncio.Event until the operator decides (Ticket 04).
5b. Handle elicitation — if the capability is agent.ask_user, create an
   ElicitationRequest, emit a clarifying_question event, and block until
   the user responds. The response becomes the tool call result.
6. Inject credentials (stubbed — no connectors yet)
7. Execute under timeout
8. Write audit record
"""

import asyncio
import json
import time
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..capabilities.registry import registry
from ..config import settings
from ..config_schema import AgentConfig
from ..models.approval import ApprovalRequest
from ..models.audit import AuditRecord
from ..models.contact import Contact
from ..models.elicitation import ElicitationRequest
from ..models.mcp import McpServer
from .approval_registry import approval_registry
from .elicitation_registry import elicitation_registry
from .protocol import SyscallResult, ToolCall


class SyscallHandler:
    """Real syscall handler — mediates every capability call (I2, I3, I4).

    Replaces StubSyscallHandler from ticket 01. Adds:
    - Subject resolution from session Contact (D10)
    - Running state emission via event_emitter
    """

    def __init__(self, db: AsyncSession, workspace_path: str, sandbox_mode: str = "strict") -> None:
        self.db = db
        self.workspace_path = workspace_path
        self.sandbox_mode = sandbox_mode
        self._event_emitter: Any = None
        self._spawn_context: dict[str, Any] = {}
        self.supports_vision = False
        # Serialize DB operations — asyncio.gather may run multiple tool
        # calls concurrently, but SQLAlchemy async sessions are not safe
        # for concurrent flush/commit.
        self._db_lock = asyncio.Lock()

    async def mediate(
        self,
        call: ToolCall,
        session: Any,
        agent_config: AgentConfig,
        run_id: str,
        is_sub_agent: bool = False,
        sub_agent_id: str | None = None,
        event_emitter: Any = None,
        parent_config: AgentConfig | None = None,
    ) -> SyscallResult:
        start = time.monotonic()
        self._event_emitter = event_emitter

        # 1. Resolve capability
        cap = registry.get(call.name)
        if cap is None:
            return await self._deny(
                run_id, call, agent_config, "capability not found", start, sub_agent_id
            )

        # 2. Check grant
        # capabilities is None = all tools enabled (default), [] = none
        # For sub-agents, intersect with parent's effective capability set.
        if is_sub_agent and parent_config is not None:
            # Compute the parent's effective granted set
            if parent_config.capabilities is not None:
                parent_granted = {g.name for g in parent_config.capabilities}
            else:
                # Parent has all tools — sub-agent is bounded by its own set
                parent_granted = None

            if parent_granted is not None:
                # Sub-agent's requested set must be within parent's set
                if agent_config.capabilities is not None:
                    sub_granted = {g.name for g in agent_config.capabilities}
                else:
                    # Sub-agent says "all tools" — but it can only get what
                    # the parent has
                    sub_granted = parent_granted

                effective_granted = sub_granted & parent_granted
                if call.name not in effective_granted:
                    return await self._deny(
                        run_id,
                        call,
                        agent_config,
                        "not granted by parent agent",
                        start,
                        sub_agent_id,
                    )
            # If parent has all tools (parent_granted is None), fall through
            # to the normal grant check below
        elif agent_config.capabilities is not None:
            granted_names = {g.name for g in agent_config.capabilities}
            if call.name not in granted_names:
                return await self._deny(
                    run_id, call, agent_config, "not granted", start, sub_agent_id
                )

        # 3. Resolve subject (D10 — for subject-scoped capabilities)
        subject_contact_id: str | None = None
        if cap.subject_scoped:
            # Resolve the Contact from the session
            async with self._db_lock:
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

        # 5. Check approval (Ticket 04)
        # The grant's require_approval flag takes precedence, then the capability def's.
        # When capabilities is None (all tools), there's no per-grant override —
        # fall back to the capability definition's require_approval.
        grant = (
            next((g for g in agent_config.capabilities if g.name == call.name), None)
            if agent_config.capabilities is not None
            else None
        )
        needs_approval = grant.require_approval if grant else cap.require_approval
        if needs_approval and not settings.yolo_mode:
            # External channel sessions use a configurable approval policy
            # (v0.1.3: replaces the hardcoded channel bypass).
            if session.channel:
                policy = getattr(self, "_channel_approval_policy", None)
                if policy is None:
                    # Look up the policy from the channel config in the DB
                    policy = await self._resolve_channel_policy(session, agent_config)

                if policy == "auto_approve":
                    pass  # Execute without waiting
                elif policy == "deny":
                    return await self._deny(
                        run_id,
                        call,
                        agent_config,
                        "denied by channel approval policy (deny)",
                        start,
                        sub_agent_id,
                    )
                elif policy == "operator":
                    # Create a pending approval for the dashboard operator
                    approval_result = await self._await_approval(
                        call=call,
                        run_id=run_id,
                        agent_config=agent_config,
                        session_id=session.id,
                        event_emitter=event_emitter,
                    )
                    if not approval_result:
                        return await self._deny(
                            run_id,
                            call,
                            agent_config,
                            "approval denied by operator",
                            start,
                            sub_agent_id,
                        )
                else:
                    # Unknown or missing policy — default to deny for safety
                    return await self._deny(
                        run_id,
                        call,
                        agent_config,
                        "denied by channel approval policy (default: deny)",
                        start,
                        sub_agent_id,
                    )
            # Check session-scoped allowlist first — if the operator previously
            # approved this exact capability+args with "remember for this session",
            # skip the approval gate.
            elif approval_registry.is_session_approved(session.id, call.name, call.args):
                pass  # Auto-approved for this session
            else:
                approval_result = await self._await_approval(
                    call=call,
                    run_id=run_id,
                    agent_config=agent_config,
                    session_id=session.id,
                    event_emitter=event_emitter,
                )
                if not approval_result:
                    # Denied (or rejected by operator)
                    return await self._deny(
                        run_id,
                        call,
                        agent_config,
                        "approval denied by operator",
                        start,
                        sub_agent_id,
                    )
                # Approved — continue to execution

        # 5b. Handle elicitation — agent.ask_user is intercepted here.
        # It has no execute function; the mediator pauses the run and waits
        # for the user to respond via the elicitation API.
        if call.name == "agent_ask_user":
            return await self._handle_elicitation(
                run_id, call, agent_config, session, start, sub_agent_id
            )

        # 6. Handle MCP tool calls — resolve binding, inject credentials, forward
        if cap.kind == "mcp_tool":
            return await self._execute_mcp_tool(
                call=call,
                cap=cap,
                agent_config=agent_config,
                session=session,
                run_id=run_id,
                subject_contact_id=subject_contact_id,
                start=start,
                sub_agent_id=sub_agent_id,
            )

        # 7. Execute under timeout
        # (The harness emits the 'running' state before calling mediate)

        # For run_subagent, inject the parent context so the sub-agent can
        # run through the same harness with the parent's model, workspace, etc.
        extra_kwargs: dict[str, Any] = {}
        if call.name == "run_subagent":
            extra_kwargs["parent_config"] = agent_config
            extra_kwargs["_spawn_context"] = getattr(self, "_spawn_context", {})

        # For memory capabilities, inject db + agent_id + contact_id + run_id
        # (subject-scoped caps get contact_id from the session — D10)
        # Also inject the db_lock so memory tools serialize their flushes
        # with the mediator's audit record writes (prevents "Session is
        # already flushing" when asyncio.gather runs tools concurrently).
        if cap.kind == "memory" or call.name in (
            "doc_list",
            "doc_search",
            "doc_inspect",
            "web_search",
        ):
            extra_kwargs["db"] = self.db
            extra_kwargs["agent_id"] = agent_config.id
            extra_kwargs["run_id"] = run_id
            extra_kwargs["db_lock"] = getattr(self, "_db_lock", None)
            if cap.subject_scoped:
                extra_kwargs["contact_id"] = subject_contact_id

        # For skill capabilities, inject agent_id (needed to find skill dirs)
        if call.name in ("skills_list", "skills_load", "skills_read_resource"):
            extra_kwargs["agent_id"] = agent_config.id

        if call.name in ("read_file", "doc_search", "doc_inspect"):
            extra_kwargs["supports_vision"] = self.supports_vision

        try:
            result = await cap.execute(
                args=call.args,
                workspace_path=self.workspace_path,
                sandbox_mode=self.sandbox_mode,
                **extra_kwargs,
            )
            elapsed = int((time.monotonic() - start) * 1000)

            # Some existing tools can request provider-native content (for
            # example, an image returned by read_file). Keep that payload out
            # of the UI and audit record; it is only for the next model call.
            model_content = None
            if isinstance(result, dict):
                model_content = result.pop("_model_content", None)

            # 8. Write audit record
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
            async with self._db_lock:
                self.db.add(audit)
                await self.db.flush()

            return SyscallResult(
                output=result,
                allowed=True,
                cost=0.0,
                latency_ms=elapsed,
                audit_id=audit.id,
                model_content=model_content,
            )
        except Exception as e:
            elapsed = int((time.monotonic() - start) * 1000)
            return await self._deny(
                run_id, call, agent_config, f"execution error: {e}", start, sub_agent_id
            )

    async def _execute_mcp_tool(
        self,
        call: ToolCall,
        cap: Any,
        agent_config: AgentConfig,
        session: Any,
        run_id: str,
        subject_contact_id: str | None,
        start: float,
        sub_agent_id: str | None,
    ) -> SyscallResult:
        """Execute an MCP tool call — resolve binding, inject creds, forward."""
        import json as _json

        from ..mcp import binding as mcp_binding
        from ..mcp import credentials as mcp_creds
        from ..mcp import registry as mcp_registry

        # Resolve the capability name → (server_id, tool_name)
        mapping = mcp_registry._tool_map.get(call.name)
        if mapping is None:
            return await self._deny(
                run_id, call, agent_config, "MCP tool not registered", start, sub_agent_id
            )
        server_id, tool_name = mapping

        # Look up the server config to check if it needs credentials
        server_result = await self.db.execute(select(McpServer).where(McpServer.id == server_id))
        server = server_result.scalar_one_or_none()
        if server is None:
            return await self._deny(
                run_id, call, agent_config, "MCP server config not found", start, sub_agent_id
            )

        # For servers that need credentials (env_template or headers), resolve
        # the subject binding to get the decrypted credential.
        # For no-auth servers (no env_template, no headers), skip the binding.
        needs_creds = bool(server.env_template) or bool(server.headers)

        if needs_creds:
            if subject_contact_id is None:
                return await self._deny(
                    run_id,
                    call,
                    agent_config,
                    "no subject binding (MCP tools require a Contact)",
                    start,
                    sub_agent_id,
                )

            resolved = await mcp_binding.resolve_binding(self.db, subject_contact_id, server_id)
            if resolved is None:
                return await self._deny(
                    run_id,
                    call,
                    agent_config,
                    "no MCP server binding for this Contact",
                    start,
                    sub_agent_id,
                )
            _binding, _server, cred = resolved

            # Decrypt the credential
            cred_value = mcp_creds.decrypt_credential(cred)

            # Render env/headers templates with the credential
            env_template = _json.loads(server.env_template) if server.env_template else {}
            headers_template = _json.loads(server.headers) if server.headers else {}
            env, headers = mcp_creds.inject_credential(env_template, headers_template, cred_value)
        else:
            env = {}
            headers = {}

        # Forward the call through the MCP client
        try:
            result = await mcp_registry.execute_mcp_tool(
                call.name, call.args, env=env, headers=headers
            )
            elapsed = int((time.monotonic() - start) * 1000)

            # Write audit record
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
            async with self._db_lock:
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
            # Write audit record for the failure
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
                result=json.dumps({"error": str(e)}),
            )
            async with self._db_lock:
                self.db.add(audit)
                await self.db.flush()
            return await self._deny(
                run_id, call, agent_config, f"MCP tool error: {e}", start, sub_agent_id
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
        async with self._db_lock:
            self.db.add(audit)
            await self.db.flush()
        return SyscallResult(
            output=None,
            allowed=False,
            denied_reason=reason,
            cost=0.0,
            latency_ms=elapsed,
        )

    async def _resolve_channel_policy(self, session: Any, agent_config: AgentConfig) -> str:
        """Look up the approval policy for the session's channel.

        Returns one of: auto_approve, operator, deny.
        Defaults to deny if no channel config is found.
        """
        if not session.channel:
            return "operator"  # Dashboard sessions use normal approval

        from ..models.channel_config import ChannelConfig

        try:
            async with self._db_lock:
                result = await self.db.execute(
                    select(ChannelConfig).where(
                        ChannelConfig.platform == session.channel,
                        ChannelConfig.agent_id == agent_config.id,
                    )
                )
                config = result.scalar_one_or_none()
                if config and config.approval_policy:
                    return config.approval_policy
        except Exception:
            pass

        # Default to deny for safety if no config is found
        return "deny"

    async def _await_approval(
        self,
        call: ToolCall,
        run_id: str,
        agent_config: AgentConfig,
        session_id: str,
        event_emitter: Any = None,
    ) -> bool:
        """Create an ApprovalRequest, emit pending_approval, and block until decided.

        Returns True if approved, False if rejected.
        If the operator chose "remember for this session," the capability+args
        is added to the session allowlist so subsequent identical calls skip the gate.
        """
        approval_id = str(uuid.uuid4())
        approval = ApprovalRequest(
            id=approval_id,
            run_id=run_id,
            capability_name=call.name,
            args=json.dumps(call.args),
            status="pending",
        )
        # Use a separate session to avoid "Session is already flushing" errors
        # when the event emitter's persistence layer triggers a flush concurrently.
        # Also commit the main session to release any pending write lock
        # so the separate session can write the approval request.
        from ..db import async_session_factory

        async with self._db_lock:
            await self.db.commit()

        async with async_session_factory() as session:
            session.add(approval)
            await session.commit()

        # Register the asyncio.Event so the API can resolve it
        pending = approval_registry.register(approval_id)

        # Emit pending_approval event so the frontend shows approve/deny buttons
        if event_emitter:
            result_emit = event_emitter(
                "tool_call",
                {
                    "id": call.id,
                    "capability": call.name,
                    "args": call.args,
                    "status": "pending_approval",
                    "approval_id": approval_id,
                },
            )
            if hasattr(result_emit, "__await__"):
                await result_emit

        # Block until the operator decides, or timeout (auto-reject)
        timeout = settings.hitl_timeout
        try:
            if timeout > 0:
                await asyncio.wait_for(pending.event.wait(), timeout=timeout)
            else:
                await pending.event.wait()
        except TimeoutError:
            # Auto-reject on timeout — the run continues with a denied result
            approval_registry.resolve(approval_id, "rejected", "system_timeout")
            if event_emitter:
                result_emit = event_emitter(
                    "tool_call",
                    {
                        "id": call.id,
                        "capability": call.name,
                        "args": call.args,
                        "status": "denied",
                        "result": {"error": "Approval timed out — auto-rejected"},
                    },
                )
                if hasattr(result_emit, "__await__"):
                    await result_emit

        # Read the decision
        decision = pending.decision or "rejected"
        approval_registry.cleanup(approval_id)

        # If approved with "remember for this session", add to session allowlist
        if decision == "approved" and pending.remember:
            approval_registry.remember_approval(
                session_id,
                call.name,
                call.args,
                scope=pending.remember_scope,
                pattern=pending.remember_pattern,
            )

        # Update the ApprovalRequest row in a separate session
        # (the approval was created in a separate session above, so we
        # can't update it via self.db which may be mid-flush)
        from ..db import async_session_factory

        async with async_session_factory() as upd_session:
            result = await upd_session.execute(
                select(ApprovalRequest).where(ApprovalRequest.id == approval_id)
            )
            ap = result.scalar_one_or_none()
            # The approval API persists operator decisions before waking this
            # task. Only write here for timeout/cancellation decisions that
            # still leave the row pending.
            if ap and ap.status == "pending":
                ap.status = decision
                ap.decided_by = pending.decided_by
                ap.decided_at = datetime.now(UTC)
                await upd_session.commit()

        return decision == "approved"

    async def _handle_elicitation(
        self,
        run_id: str,
        call: ToolCall,
        agent_config: AgentConfig,
        session: Any,
        start: float,
        sub_agent_id: str | None = None,
    ) -> SyscallResult:
        """Handle agent.ask_user — pause the run and wait for user input.

        Creates an ElicitationRequest, emits a clarifying_question event,
        and blocks on an asyncio.Event until the user responds via the API.
        The user's response becomes the tool call result.
        """
        question = call.args.get("question", "")
        raw_options = call.args.get("options")  # list[str] | list[{label, description}]
        multi_select = call.args.get("multi_select", False)

        # Normalize options to [{label, description}] format
        options = None
        if raw_options:
            options = []
            for opt in raw_options:
                if isinstance(opt, str):
                    options.append({"label": opt, "description": ""})
                elif isinstance(opt, dict):
                    options.append(
                        {
                            "label": opt.get("label", ""),
                            "description": opt.get("description", ""),
                        }
                    )

        elicitation_id = str(uuid.uuid4())
        elicitation = ElicitationRequest(
            id=elicitation_id,
            run_id=run_id,
            question=question,
            options=json.dumps(options) if options else None,
            status="pending",
        )
        # Use a separate session to avoid "database is locked" errors.
        # Commit the main session first to release any pending write lock.
        from ..db import async_session_factory

        async with self._db_lock:
            await self.db.commit()

        async with async_session_factory() as el_session:
            el_session.add(elicitation)
            await el_session.commit()

        # Register the asyncio.Event so the API can resolve it
        pending = elicitation_registry.register(elicitation_id)

        # Emit clarifying_question event so the frontend shows the question + input
        if self._event_emitter:
            result_emit = self._event_emitter(
                "clarifying_question",
                {
                    "id": elicitation_id,
                    "tool_call_id": call.id,
                    "question": question,
                    "options": options,
                    "multi_select": multi_select,
                },
            )
            if hasattr(result_emit, "__await__"):
                await result_emit

        # Also emit a tool_call event so the tool call block shows the question
        if self._event_emitter:
            result_emit = self._event_emitter(
                "tool_call",
                {
                    "id": call.id,
                    "capability": call.name,
                    "args": call.args,
                    "status": "pending_input",
                    "elicitation_id": elicitation_id,
                },
            )
            if hasattr(result_emit, "__await__"):
                await result_emit

        # Block until the user responds, or timeout (auto-respond with empty)
        timeout = settings.hitl_timeout
        try:
            if timeout > 0:
                await asyncio.wait_for(pending.event.wait(), timeout=timeout)
            else:
                await pending.event.wait()
        except TimeoutError:
            # Auto-respond on timeout — the run continues with an empty response
            elicitation_registry.resolve(elicitation_id, "", "system_timeout")
            if self._event_emitter:
                result_emit = self._event_emitter(
                    "tool_call",
                    {
                        "id": call.id,
                        "capability": call.name,
                        "args": call.args,
                        "status": "complete",
                        "result": {"response": "", "error": "Elicitation timed out"},
                    },
                )
                if hasattr(result_emit, "__await__"):
                    await result_emit

        response = pending.response or ""
        responded_by = pending.responded_by
        elicitation_registry.cleanup(elicitation_id)

        # Update the ElicitationRequest row in a separate session
        from ..db import async_session_factory

        async with async_session_factory() as upd_session:
            result = await upd_session.execute(
                select(ElicitationRequest).where(ElicitationRequest.id == elicitation_id)
            )
            el = result.scalar_one_or_none()
            if el:
                el.status = "answered"
                el.response = response
                el.responded_by = responded_by
                el.responded_at = datetime.now(UTC)
                await upd_session.commit()

        # Emit tool_call complete event
        if self._event_emitter:
            result_emit = self._event_emitter(
                "tool_call",
                {
                    "id": call.id,
                    "capability": call.name,
                    "args": call.args,
                    "status": "complete",
                    "result": {"response": response},
                },
            )
            if hasattr(result_emit, "__await__"):
                await result_emit

        elapsed = int((time.monotonic() - start) * 1000)

        # Write audit record
        audit = AuditRecord(
            id=str(uuid.uuid4()),
            run_id=run_id,
            agent_id=agent_config.id,
            sub_agent_id=sub_agent_id,
            capability_name=call.name,
            allowed=True,
            denied_reason=None,
            cost=0.0,
            latency_ms=elapsed,
            args=json.dumps(call.args),
            result=json.dumps({"response": response}),
        )
        async with self._db_lock:
            self.db.add(audit)
            await self.db.flush()

        return SyscallResult(
            output={"response": response},
            allowed=True,
            denied_reason=None,
            cost=0.0,
            latency_ms=elapsed,
        )


# Keep the old name for backward compatibility with existing code
StubSyscallHandler = SyscallHandler
