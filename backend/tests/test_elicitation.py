"""Tests for the elicitation (clarifying question) HITL mechanism."""

import asyncio
import json
import uuid

import pytest
from sqlalchemy import select

from agentos.config_schema import AgentConfig, CapabilityGrant, ModelConfig
from agentos.models.elicitation import ElicitationRequest
from agentos.syscall.elicitation_registry import elicitation_registry
from agentos.syscall.mediator import SyscallHandler
from agentos.syscall.protocol import ToolCall


@pytest.fixture
def workspace(tmp_path):
    return str(tmp_path / "ws")


@pytest.fixture
def agent_config():
    return AgentConfig(
        id="elicit-test",
        name="Elicitation Test",
        model=ModelConfig(provider_id="test", name="scripted"),
        soul="Test soul.",
        capabilities=[CapabilityGrant(name="agent.ask_user", require_approval=False)],
    )


class FakeSession:
    """Minimal session stub for the mediator."""
    id = "test-session-1"
    contact_id = "test-contact-1"


@pytest.mark.asyncio
async def test_elicitation_basic_flow(db, workspace, agent_config):
    """Agent calls agent.ask_user → mediator pauses → user responds → agent gets answer."""
    handler = SyscallHandler(db=db, workspace_path=workspace)
    call = ToolCall(
        id="call_1",
        name="agent.ask_user",
        args={"question": "Which file?", "options": ["a.txt", "b.txt"]},
    )

    # Start the mediate call in the background — it will block on the event
    task = asyncio.create_task(
        handler.mediate(
            call=call,
            session=FakeSession(),
            agent_config=agent_config,
            run_id="test-run-1",
        )
    )
    # Give it a moment to create the ElicitationRequest and register the event
    await asyncio.sleep(0.1)

    # Verify the ElicitationRequest was created
    result = await db.execute(select(ElicitationRequest))
    elicitations = result.scalars().all()
    assert len(elicitations) == 1
    assert elicitations[0].status == "pending"
    assert elicitations[0].question == "Which file?"
    assert json.loads(elicitations[0].options) == [
        {"label": "a.txt", "description": ""},
        {"label": "b.txt", "description": ""},
    ]

    # Simulate the user responding via the API
    elicitation_id = elicitations[0].id
    resolved = elicitation_registry.resolve(elicitation_id, "a.txt", "operator-1")
    assert resolved

    # Wait for the mediate call to complete
    syscall_result = await asyncio.wait_for(task, timeout=5.0)

    # Verify the result
    assert syscall_result.allowed is True
    assert syscall_result.output == {"response": "a.txt"}

    # Verify the ElicitationRequest was updated
    await db.refresh(elicitations[0])
    assert elicitations[0].status == "answered"
    assert elicitations[0].response == "a.txt"
    assert elicitations[0].responded_by == "operator-1"


@pytest.mark.asyncio
async def test_elicitation_free_text(db, workspace, agent_config):
    """Elicitation without options → user provides free-text response."""
    handler = SyscallHandler(db=db, workspace_path=workspace)
    call = ToolCall(
        id="call_2",
        name="agent.ask_user",
        args={"question": "What should I name the file?"},
    )

    task = asyncio.create_task(
        handler.mediate(
            call=call,
            session=FakeSession(),
            agent_config=agent_config,
            run_id="test-run-2",
        )
    )
    await asyncio.sleep(0.1)

    # Verify no options were stored
    result = await db.execute(select(ElicitationRequest))
    elicitations = result.scalars().all()
    assert len(elicitations) == 1
    assert elicitations[0].options is None

    # User responds with free text
    elicitation_registry.resolve(elicitations[0].id, "my_report.txt", "operator-1")

    syscall_result = await asyncio.wait_for(task, timeout=5.0)
    assert syscall_result.output == {"response": "my_report.txt"}


@pytest.mark.asyncio
async def test_elicitation_not_granted(db, workspace):
    """If agent.ask_user is not in the agent's capabilities, it's denied."""
    from agentos.config_schema import AgentConfig, ModelConfig

    config = AgentConfig(
        id="no-elicit",
        name="No Elicit",
        model=ModelConfig(provider_id="test", name="scripted"),
        soul="Test.",
        capabilities=[],  # no agent.ask_user
    )
    handler = SyscallHandler(db=db, workspace_path=workspace)
    call = ToolCall(
        id="call_3",
        name="agent.ask_user",
        args={"question": "Hello?"},
    )

    result = await handler.mediate(
        call=call,
        session=FakeSession(),
        agent_config=config,
        run_id="test-run-3",
    )

    assert result.allowed is False
    assert "not granted" in (result.denied_reason or "")


@pytest.mark.asyncio
async def test_elicitation_emits_events(db, workspace, agent_config):
    """The mediator emits clarifying_question and tool_call events."""
    handler = SyscallHandler(db=db, workspace_path=workspace)
    call = ToolCall(
        id="call_4",
        name="agent.ask_user",
        args={"question": "Pick one", "options": ["x", "y"]},
    )

    events = []

    async def event_emitter(event_type, payload):
        events.append((event_type, payload))

    task = asyncio.create_task(
        handler.mediate(
            call=call,
            session=FakeSession(),
            agent_config=agent_config,
            run_id="test-run-4",
            event_emitter=event_emitter,
        )
    )
    await asyncio.sleep(0.2)

    # Should have emitted clarifying_question and tool_call (pending_input)
    event_types = [e[0] for e in events]
    assert "clarifying_question" in event_types
    assert "tool_call" in event_types

    # Find the clarifying_question event
    cq = next(p for t, p in events if t == "clarifying_question")
    assert cq["question"] == "Pick one"
    assert cq["options"] == [
        {"label": "x", "description": ""},
        {"label": "y", "description": ""},
    ]
    assert cq["tool_call_id"] == "call_4"

    # Find the pending_input tool_call event
    tc_pending = next(
        p for t, p in events if t == "tool_call" and p["status"] == "pending_input"
    )
    assert tc_pending["elicitation_id"] is not None

    # Resolve
    elicitation_registry.resolve(cq["id"], "x", "operator-1")
    await asyncio.wait_for(task, timeout=5.0)

    # Should have emitted a complete tool_call event
    tc_complete = next(
        p for t, p in events if t == "tool_call" and p["status"] == "complete"
    )
    assert tc_complete["result"] == {"response": "x"}


@pytest.mark.asyncio
async def test_elicitation_writes_audit_record(db, workspace, agent_config):
    """An audit record is written for the elicitation call."""
    handler = SyscallHandler(db=db, workspace_path=workspace)
    call = ToolCall(
        id="call_5",
        name="agent.ask_user",
        args={"question": "Test?"},
    )

    task = asyncio.create_task(
        handler.mediate(
            call=call,
            session=FakeSession(),
            agent_config=agent_config,
            run_id="test-run-5",
        )
    )
    await asyncio.sleep(0.1)

    result = await db.execute(select(ElicitationRequest))
    elicitation_registry.resolve(result.scalars().first().id, "yes", "op-1")
    await asyncio.wait_for(task, timeout=5.0)

    from agentos.models.audit import AuditRecord

    result = await db.execute(select(AuditRecord).where(AuditRecord.run_id == "test-run-5"))
    audits = result.scalars().all()
    assert len(audits) == 1
    assert audits[0].capability_name == "agent.ask_user"
    assert audits[0].allowed is True
    assert json.loads(audits[0].result) == {"response": "yes"}
