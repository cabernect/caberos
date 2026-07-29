"""Test the harness loop with a scripted model double."""

import uuid

import pytest

from agentos.config_schema import AgentConfig, CapabilityGrant, ModelConfig
from agentos.harness.loop import Harness
from agentos.harness.scripted_model import ScriptedModel, ScriptedResponse
from agentos.syscall.mediator import StubSyscallHandler


@pytest.mark.asyncio
async def test_harness_tool_call_then_answer(db, workspace):
    """Scripted model returns a tool call, then a final answer."""
    config = AgentConfig(
        id="harness-test-1",
        name="Harness Test",
        model=ModelConfig(provider_id="test", name="scripted"),
        soul="Test soul.",
        capabilities=[CapabilityGrant(name="shell.run", require_approval=False)],
    )

    model = ScriptedModel(
        [
            ScriptedResponse(
                tool_calls=[
                    {
                        "id": "call_1",
                        "name": "shell.run",
                        "args": {"command": "echo hello"},
                    }
                ],
            ),
            ScriptedResponse(content="The command output: hello"),
        ]
    )

    harness = Harness(model=model)
    syscall = StubSyscallHandler(db=db, workspace_path=workspace)

    result = await harness.run(
        agent_config=config,
        session=None,
        message="Run echo hello",
        syscall_handler=syscall,
        run_id=str(uuid.uuid4()),
    )

    assert result.status == "completed"
    assert result.total_turns == 2  # one for tool call, one for final answer
    assert len(result.tool_calls_made) == 1
    assert result.tool_calls_made[0]["name"] == "shell.run"
    assert result.tool_calls_made[0]["allowed"] is True
    assert "hello" in result.tool_calls_made[0]["result"]["stdout"]
    assert result.final_answer == "The command output: hello"


@pytest.mark.asyncio
async def test_harness_turn_limit(db, workspace):
    """Harness stops when turn limit is hit."""
    config = AgentConfig(
        id="harness-test-2",
        name="Turn Limit Test",
        model=ModelConfig(provider_id="test", name="scripted"),
        capabilities=[CapabilityGrant(name="shell.run", require_approval=False)],
        limits=__import__("agentos.config_schema", fromlist=["Limits"]).Limits(max_turns_per_run=2),
    )

    # Model always returns tool calls, never a final answer
    model = ScriptedModel(
        [
            ScriptedResponse(
                tool_calls=[{"id": "c1", "name": "shell.run", "args": {"command": "echo 1"}}]
            ),
            ScriptedResponse(
                tool_calls=[{"id": "c2", "name": "shell.run", "args": {"command": "echo 2"}}]
            ),
            ScriptedResponse(
                tool_calls=[{"id": "c3", "name": "shell.run", "args": {"command": "echo 3"}}]
            ),
        ]
    )

    harness = Harness(model=model)
    syscall = StubSyscallHandler(db=db, workspace_path=workspace)

    result = await harness.run(
        agent_config=config,
        session=None,
        message="Keep running",
        syscall_handler=syscall,
        run_id=str(uuid.uuid4()),
    )

    assert result.status == "limit_exceeded"
    assert result.total_turns == 2


@pytest.mark.asyncio
async def test_harness_event_emitter(db, workspace):
    """Harness emits SSE events."""
    config = AgentConfig(
        id="harness-test-3",
        name="Event Test",
        model=ModelConfig(provider_id="test", name="scripted"),
        capabilities=[CapabilityGrant(name="shell.run", require_approval=False)],
    )

    model = ScriptedModel(
        [
            ScriptedResponse(
                tool_calls=[{"id": "c1", "name": "shell.run", "args": {"command": "echo hi"}}]
            ),
            ScriptedResponse(content="Done!"),
        ]
    )

    events: list[tuple[str, dict]] = []

    async def emitter(event_type: str, payload: dict) -> None:
        events.append((event_type, payload))

    harness = Harness(model=model)
    syscall = StubSyscallHandler(db=db, workspace_path=workspace)

    await harness.run(
        agent_config=config,
        session=None,
        message="test",
        syscall_handler=syscall,
        run_id=str(uuid.uuid4()),
        event_emitter=emitter,
    )

    event_types = [e[0] for e in events]
    assert "typing" in event_types
    assert "tool_call" in event_types
    assert "turn_complete" in event_types
    assert "message_complete" in event_types

    # Check tool_call events have the right statuses
    tool_call_events = [e for e in events if e[0] == "tool_call"]
    statuses = [e[1].get("status") for e in tool_call_events]
    assert "pending" in statuses
    assert "complete" in statuses


@pytest.mark.asyncio
async def test_harness_denied_capability(db, workspace):
    """Harness handles denied tool calls."""
    config = AgentConfig(
        id="harness-test-4",
        name="Denied Test",
        model=ModelConfig(provider_id="test", name="scripted"),
        capabilities=[],  # no capabilities granted
    )

    model = ScriptedModel(
        [
            ScriptedResponse(
                tool_calls=[{"id": "c1", "name": "shell.run", "args": {"command": "echo hi"}}]
            ),
            ScriptedResponse(content="Okay, I couldn't run that."),
        ]
    )

    harness = Harness(model=model)
    syscall = StubSyscallHandler(db=db, workspace_path=workspace)

    result = await harness.run(
        agent_config=config,
        session=None,
        message="test",
        syscall_handler=syscall,
        run_id=str(uuid.uuid4()),
    )

    assert len(result.tool_calls_made) == 1
    assert result.tool_calls_made[0]["allowed"] is False
