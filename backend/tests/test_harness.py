"""Test the harness loop with a scripted model double."""

import asyncio
import uuid
from types import SimpleNamespace

import pytest

from agentos.config import settings
from agentos.config_schema import AgentConfig, CapabilityGrant, ModelConfig
from agentos.harness.context import assemble_system_prompt
from agentos.harness.litellm_adapter import LiteLLMAdapter
from agentos.harness.loop import Harness
from agentos.harness.scripted_model import ScriptedModel, ScriptedResponse
from agentos.syscall.mediator import StubSyscallHandler


@pytest.mark.asyncio
async def test_streaming_model_idle_timeout_ends_stalled_stream(monkeypatch):
    async def stalled_stream():
        yield SimpleNamespace(
            choices=[
                SimpleNamespace(
                    delta=SimpleNamespace(
                        reasoning_content="Checking the date",
                        content=None,
                        tool_calls=None,
                    )
                )
            ],
        )
        await asyncio.Event().wait()

    async def acompletion(**_kwargs):
        return stalled_stream()

    adapter = LiteLLMAdapter(db=None)

    async def load_provider(_provider_id):
        return {
            "api_key": "",
            "base_url": None,
            "org_id": None,
            "extra_params": {},
            "type": "openai",
        }

    monkeypatch.setattr(adapter, "_load_provider", load_provider)
    monkeypatch.setattr("agentos.harness.litellm_adapter.litellm.acompletion", acompletion)
    monkeypatch.setattr(settings, "model_stream_idle_timeout", 0.01)

    stream = adapter.complete_stream(
        agent_model=ModelConfig(provider_id="test", name="test-model"),
        messages=[{"role": "user", "content": "hello"}],
    )
    assert await anext(stream) == ("thinking", "Checking the date")
    with pytest.raises(TimeoutError, match="Model stream was idle"):
        await anext(stream)


@pytest.mark.asyncio
async def test_harness_reports_stream_timeout_to_the_user(db, workspace):
    class TimedOutModel:
        async def complete_stream(self, **_kwargs):
            raise TimeoutError("Model stream was idle for 30s")
            yield

    config = AgentConfig(
        id="timeout-test",
        name="Timeout Test",
        model=ModelConfig(provider_id="test", name="scripted"),
        capabilities=[],
    )
    events = []

    async def emit(event_type, payload):
        events.append((event_type, payload))

    run_id = str(uuid.uuid4())
    result = await Harness(model=TimedOutModel()).run(
        agent_config=config,
        session=None,
        message="Who won?",
        syscall_handler=StubSyscallHandler(db=db, workspace_path=workspace),
        run_id=run_id,
        event_emitter=emit,
    )

    assert result.status == "failed"
    assert "timed out" in result.final_answer
    assert events[-1] == (
        "message_complete",
        {
            "run_id": run_id,
            "total_cost": 0.0,
            "total_turns": 1,
            "status": "failed",
        },
    )


def test_base_system_prompt_present():
    """Every agent's system prompt starts with the base platform instructions."""
    config = AgentConfig(
        id="test",
        name="Test",
        model=ModelConfig(provider_id="test", name="scripted"),
        soul="I am a test agent.",
        capabilities=[],
    )
    prompt = assemble_system_prompt(config)
    # Base prompt is always first
    assert "CaberOS Agent Operating Instructions" in prompt
    # Soul comes after the base prompt
    assert "I am a test agent." in prompt
    # Base prompt sections are present
    assert "Workspace" in prompt
    assert "Capabilities" in prompt
    assert "Output Rules" in prompt
    assert "agent_ask_user" in prompt


def test_base_prompt_present_even_without_identity():
    """The base prompt is injected even if soul/persona/task are all empty."""
    config = AgentConfig(
        id="test",
        name="Test",
        model=ModelConfig(provider_id="test", name="scripted"),
        capabilities=[],
    )
    prompt = assemble_system_prompt(config)
    assert "CaberOS Agent Operating Instructions" in prompt
    assert "Workspace" in prompt


def test_base_prompt_before_soul():
    """The base prompt comes before the soul in the assembled prompt."""
    config = AgentConfig(
        id="test",
        name="Test",
        model=ModelConfig(provider_id="test", name="scripted"),
        soul="MY_UNIQUE_SOUL_MARKER",
        capabilities=[],
    )
    prompt = assemble_system_prompt(config)
    base_pos = prompt.index("CaberOS Agent Operating Instructions")
    soul_pos = prompt.index("MY_UNIQUE_SOUL_MARKER")
    assert base_pos < soul_pos, "Base prompt must come before soul"


def test_multimodal_message_with_image():
    """When attachments are present, the user message is a multimodal content array."""
    from agentos.harness.context import build_message_history
    from agentos.pipeline import Attachment

    attachments = [
        Attachment(
            type="image",
            mime_type="image/png",
            data="iVBORw0KGgoAAAANSUhEUg==",
            filename="screenshot.png",
        )
    ]
    history = build_message_history("system prompt", [], "What's in this image?", attachments)

    # System message is plain text
    assert history[0]["role"] == "system"
    assert history[0]["content"] == "system prompt"

    # User message is a content array
    user_msg = history[1]
    assert user_msg["role"] == "user"
    assert isinstance(user_msg["content"], list)

    # First part is text, second is image_url
    parts = user_msg["content"]
    assert parts[0]["type"] == "text"
    assert parts[0]["text"] == "What's in this image?"
    assert parts[1]["type"] == "image_url"
    assert "data:image/png;base64," in parts[1]["image_url"]["url"]


def test_multimodal_message_with_url():
    """URL attachments are sent as image_url with the URL directly."""
    from agentos.harness.context import build_message_history
    from agentos.pipeline import Attachment

    attachments = [
        Attachment(
            type="url",
            mime_type="image/jpeg",
            data="https://example.com/photo.jpg",
            filename="",
        )
    ]
    history = build_message_history("sys", [], "Describe this", attachments)
    user_msg = history[1]
    parts = user_msg["content"]
    assert parts[1]["type"] == "image_url"
    assert parts[1]["image_url"]["url"] == "https://example.com/photo.jpg"


def test_multimodal_message_with_text_file():
    """Text file attachments are appended to the message content."""
    from agentos.harness.context import build_message_history
    from agentos.pipeline import Attachment

    attachments = [
        Attachment(
            type="file",
            mime_type="text/plain",
            data="Hello world from the file!",
            filename="notes.txt",
        )
    ]
    history = build_message_history("sys", [], "Read this file", attachments)
    user_msg = history[1]
    parts = user_msg["content"]
    # Should have text part + file content part
    assert len(parts) == 2
    assert parts[0]["type"] == "text"
    assert "Read this file" in parts[0]["text"]
    assert parts[1]["type"] == "text"
    assert "Hello world from the file!" in parts[1]["text"]
    assert "notes.txt" in parts[1]["text"]


def test_no_attachments_plain_text():
    """Without attachments, the user message is a plain string (saves tokens)."""
    from agentos.harness.context import build_message_history

    history = build_message_history("sys", [], "Hello", None)
    user_msg = history[1]
    assert user_msg["role"] == "user"
    assert isinstance(user_msg["content"], str)
    assert user_msg["content"] == "Hello"


def test_multimodal_multiple_attachments():
    """Multiple attachments produce multiple content parts."""
    from agentos.harness.context import build_message_history
    from agentos.pipeline import Attachment

    attachments = [
        Attachment(type="image", mime_type="image/png", data="abc123==", filename="a.png"),
        Attachment(type="image", mime_type="image/jpeg", data="def456==", filename="b.jpg"),
        Attachment(type="url", mime_type="image/gif", data="https://x.com/c.gif", filename=""),
    ]
    history = build_message_history("sys", [], "Compare these", attachments)
    parts = history[1]["content"]
    # 1 text + 3 attachments = 4 parts
    assert len(parts) == 4
    assert parts[0]["type"] == "text"
    assert parts[1]["type"] == "image_url"
    assert parts[2]["type"] == "image_url"
    assert parts[3]["type"] == "image_url"


@pytest.mark.asyncio
async def test_harness_tool_call_then_answer(db, workspace):
    """Scripted model returns a tool call, then a final answer."""
    config = AgentConfig(
        id="harness-test-1",
        name="Harness Test",
        model=ModelConfig(provider_id="test", name="scripted"),
        soul="Test soul.",
        capabilities=[CapabilityGrant(name="terminal", require_approval=False)],
    )

    model = ScriptedModel(
        [
            ScriptedResponse(
                tool_calls=[
                    {
                        "id": "call_1",
                        "name": "terminal",
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
    assert result.tool_calls_made[0]["name"] == "terminal"
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
        capabilities=[CapabilityGrant(name="terminal", require_approval=False)],
        limits=__import__("agentos.config_schema", fromlist=["Limits"]).Limits(max_turns_per_run=2),
    )

    # Model always returns tool calls, never a final answer
    model = ScriptedModel(
        [
            ScriptedResponse(
                tool_calls=[{"id": "c1", "name": "terminal", "args": {"command": "echo 1"}}]
            ),
            ScriptedResponse(
                tool_calls=[{"id": "c2", "name": "terminal", "args": {"command": "echo 2"}}]
            ),
            ScriptedResponse(
                tool_calls=[{"id": "c3", "name": "terminal", "args": {"command": "echo 3"}}]
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
        capabilities=[CapabilityGrant(name="terminal", require_approval=False)],
    )

    model = ScriptedModel(
        [
            ScriptedResponse(
                tool_calls=[{"id": "c1", "name": "terminal", "args": {"command": "echo hi"}}]
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
                tool_calls=[{"id": "c1", "name": "terminal", "args": {"command": "echo hi"}}]
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
