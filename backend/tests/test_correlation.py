"""W10 stage 2 — call_id/sub_agent_id correlation across the ledger.

Every mediated call stamps call_id on its audit row; domain rows
(approvals, elicitations, terminal sessions, artifact revisions, run
sources) carry call_id + sub_agent_id so the timeline can join exactly —
never by timestamp.
"""

import asyncio
import sys
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from agentos.config_schema import AgentConfig, CapabilityGrant, ModelConfig
from agentos.models.approval import ApprovalRequest
from agentos.models.audit import AuditRecord
from agentos.models.elicitation import ElicitationRequest
from agentos.models.terminal import TerminalSession
from agentos.services.tool_status import tool_event_status
from agentos.syscall.approval_registry import approval_registry
from agentos.syscall.mediator import SyscallHandler
from agentos.syscall.protocol import ToolCall

posix_only = pytest.mark.skipif(
    sys.platform == "win32", reason="needs POSIX /bin/sh for open-mode spawn"
)


def _config(caps, approval_caps=()):
    approval_set = set(approval_caps)
    return AgentConfig(
        id="corr-agent",
        name="Corr Agent",
        model=ModelConfig(provider_id="test-provider", name="test-model"),
        capabilities=[CapabilityGrant(name=c, require_approval=(c in approval_set)) for c in caps],
    )


def _session():
    return SimpleNamespace(contact_id="contact-1", id="sess-1", channel=None)


async def _audits(db, run_id):
    return (
        (await db.execute(select(AuditRecord).where(AuditRecord.run_id == run_id))).scalars().all()
    )


async def test_audit_carries_call_subagent_effects_and_time(db, workspace):
    handler = SyscallHandler(db=db, workspace_path=workspace)
    result = await handler.mediate(
        call=ToolCall(id="call-42", name="datetime_now", args={}),
        session=_session(),
        agent_config=_config(["datetime_now"]),
        run_id="run-1",
        sub_agent_id="sub-7",
    )
    assert result.allowed

    from agentos.capabilities.registry import registry

    row = (await _audits(db, "run-1"))[0]
    assert row.call_id == "call-42"
    assert row.sub_agent_id == "sub-7"
    assert row.created_at is not None
    assert row.effects == sorted(registry.get("datetime_now").effects)


async def test_concurrent_same_capability_calls_keep_exact_ids(db, workspace):
    """asyncio.gather'd calls share the handler but never share call_id."""
    handler = SyscallHandler(db=db, workspace_path=workspace)
    results = await asyncio.gather(
        *[
            handler.mediate(
                call=ToolCall(id=f"call-{i}", name="datetime_now", args={}),
                session=_session(),
                agent_config=_config(["datetime_now"]),
                run_id="run-2",
            )
            for i in range(3)
        ]
    )
    assert all(r.allowed for r in results)
    rows = await _audits(db, "run-2")
    assert {r.call_id for r in rows} == {"call-0", "call-1", "call-2"}
    assert len(rows) == 3


async def test_parent_and_subagent_same_call_id_do_not_cross(db, workspace):
    """The (sub_agent_id, call_id) pair scopes the join — a parent's call-1
    and a sub-agent's call-1 stay separate."""
    handler = SyscallHandler(db=db, workspace_path=workspace)
    config = _config(["datetime_now"])
    await handler.mediate(
        call=ToolCall(id="call-1", name="datetime_now", args={}),
        session=_session(),
        agent_config=config,
        run_id="run-3",
    )
    await handler.mediate(
        call=ToolCall(id="call-1", name="datetime_now", args={}),
        session=_session(),
        agent_config=config,
        run_id="run-3",
        is_sub_agent=True,
        sub_agent_id="sub-1",
        parent_config=config,
    )
    rows = await _audits(db, "run-3")
    by_scope = {(r.sub_agent_id, r.call_id) for r in rows}
    assert by_scope == {(None, "call-1"), ("sub-1", "call-1")}


async def test_denied_and_error_calls_keep_call_id(db, workspace):
    handler = SyscallHandler(db=db, workspace_path=workspace)
    denied = await handler.mediate(
        call=ToolCall(id="c-denied", name="terminal", args={"command": "x"}),
        session=_session(),
        agent_config=_config([]),  # no grant → policy denial
        run_id="run-4",
    )
    assert denied.status == "denied"
    row = (await _audits(db, "run-4"))[0]
    assert row.outcome == "denied"
    assert row.call_id == "c-denied"


async def test_unknown_capability_fails_safely_with_call_id(db, workspace):
    handler = SyscallHandler(db=db, workspace_path=workspace)
    result = await handler.mediate(
        call=ToolCall(id="c-mystery", name="no_such_tool", args={}),
        session=_session(),
        agent_config=_config(["no_such_tool"]),
        run_id="run-5",
    )
    assert result.allowed is False
    row = (await _audits(db, "run-5"))[0]
    assert row.call_id == "c-mystery"
    assert row.outcome == "denied"
    # Unknown capability → no effects snapshot (never re-read for history).
    assert row.effects is None


async def test_approval_request_carries_call_and_subagent(db, workspace):
    handler = SyscallHandler(db=db, workspace_path=workspace)

    async def reject_when_pending():
        for _ in range(200):
            ids = approval_registry.list_pending_ids()
            if ids:
                approval_registry.resolve(ids[0], "rejected", "op-1")
                return
            await asyncio.sleep(0.01)
        raise AssertionError("approval never went pending")

    resolver = asyncio.create_task(reject_when_pending())
    result = await handler.mediate(
        call=ToolCall(id="c-approve", name="terminal", args={"command": "ls"}),
        session=_session(),
        agent_config=_config(["terminal"], approval_caps=["terminal"]),
        run_id="run-6",
        sub_agent_id="sub-a",
    )
    await resolver
    assert result.status == "denied"

    approval = await db.scalar(select(ApprovalRequest).where(ApprovalRequest.run_id == "run-6"))
    assert approval.call_id == "c-approve"
    assert approval.sub_agent_id == "sub-a"
    assert approval.status == "rejected"


async def test_elicitation_carries_call_and_subagent(db, workspace):
    handler = SyscallHandler(db=db, workspace_path=workspace)
    handler._is_test_run = True  # headless — resolves instantly
    result = await handler.mediate(
        call=ToolCall(id="c-ask", name="agent_ask_user", args={"question": "which?"}),
        session=_session(),
        agent_config=_config(["agent_ask_user"]),
        run_id="run-7",
        sub_agent_id="sub-e",
    )
    assert result.allowed

    row = await db.scalar(select(ElicitationRequest).where(ElicitationRequest.run_id == "run-7"))
    assert row.call_id == "c-ask"
    assert row.sub_agent_id == "sub-e"


@posix_only
async def test_terminal_session_carries_call_id(db, workspace):
    from agentos.terminal.registry import terminal_registry

    handler = SyscallHandler(db=db, workspace_path=workspace, sandbox_mode="open")
    result = await handler.mediate(
        call=ToolCall(id="c-term", name="terminal", args={"command": "echo hi", "async": True}),
        session=_session(),
        agent_config=_config(["terminal"]),
        run_id="run-8",
        sub_agent_id="sub-t",
    )
    assert result.allowed
    row = await db.scalar(select(TerminalSession).where(TerminalSession.run_id == "run-8"))
    assert row.call_id == "c-term"
    assert row.sub_agent_id == "sub-t"
    await terminal_registry.close(
        row.id, agent_id="corr-agent", session_id="sess-1", run_id="run-8"
    )


async def test_run_source_records_first_citation_call(db, monkeypatch):
    """doc_search tags the RunSource with the citing call; repeats keep the
    first-citation attribution (each repeat shows in its own audit row)."""
    from agentos.capabilities.tools import knowledge
    from agentos.models.source import RunSource

    async def fake_retrieve(db, query, limit=5, agent_id=None, run_id=None):
        return {
            "results": [
                {
                    "chunk_id": "ch-1",
                    "document_id": "doc-1",
                    "source_path": "notes.md",
                    "storage_path": "vault/notes.md",
                    "heading_path": [],
                    "page_number": None,
                    "sheet_name": None,
                    "source_location": None,
                    "text": "the excerpt",
                }
            ],
            "trace": {},
        }

    monkeypatch.setattr(knowledge, "retrieve", fake_retrieve)
    await knowledge.doc_search(
        {"query": "q"},
        db=db,
        agent_id="ag",
        run_id="run-9",
        call_id="c-search",
        sub_agent_id="sub-s",
    )
    row = await db.scalar(select(RunSource).where(RunSource.run_id == "run-9"))
    assert row.call_id == "c-search"
    assert row.sub_agent_id == "sub-s"

    # Second citation of the same chunk keeps the first call's attribution.
    await knowledge.doc_search(
        {"query": "q"},
        db=db,
        agent_id="ag",
        run_id="run-9",
        call_id="c-search-2",
    )
    rows = (await db.execute(select(RunSource))).scalars().all()
    assert len(rows) == 1
    assert rows[0].call_id == "c-search"


def test_tool_event_status_mapping():
    """Harness SSE and the timeline name outcomes identically; policy vs
    runtime outcomes stay distinct, unknown fails closed."""
    assert tool_event_status("ok") == "complete"
    assert tool_event_status("denied") == "denied"
    assert tool_event_status("error") == "failed"
    assert tool_event_status("timeout") == "timeout"
    assert tool_event_status("interrupted") == "interrupted"
    assert tool_event_status("mysterious") == "failed"
    assert tool_event_status(None) == "failed"
