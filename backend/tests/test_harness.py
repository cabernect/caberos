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
from agentos.models.provider import Provider
from agentos.providers import ProviderRegistry
from agentos.providers.registry import LiteLLMProviderAdapter, OpenCodeZenProviderAdapter
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
    # message_complete is no longer emitted by the loop — it's emitted by
    # runner.py after the pipeline finishes, with full context metadata.
    # The loop now just returns the result without emitting message_complete.


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


def test_attachment_references_do_not_enter_model_context():
    """Attachments are metadata-only until the agent uses an existing tool."""
    from agentos.harness.context import build_message_history
    from agentos.pipeline import Attachment

    attachments = [
        Attachment(
            type="image",
            mime_type="image/png",
            data="iVBORw0KGgoAAAANSUhEUg==",
            filename="screenshot.png",
        ),
        Attachment(
            type="url",
            mime_type="text/uri-list",
            data="https://example.com",
            filename="",
        ),
        Attachment(
            type="file",
            mime_type="text/plain",
            data="Hello world from the file!",
            filename="notes.txt",
        ),
    ]
    history = build_message_history("system prompt", [], "Inspect these", attachments)

    user_msg = history[1]
    assert user_msg["role"] == "user"
    assert isinstance(user_msg["content"], str)
    assert "screenshot.png" in user_msg["content"]
    assert "https://example.com" in user_msg["content"]
    assert "notes.txt" in user_msg["content"]
    assert "iVBORw0KGgoAAAANSUhEUg==" not in user_msg["content"]
    assert "Hello world from the file!" not in user_msg["content"]


def test_workspace_attachment_references_are_used():
    """Prepared attachment records expose paths without exposing file contents."""
    from agentos.harness.context import build_message_history

    history = build_message_history(
        "sys",
        [],
        "Read this file",
        [
            {
                "id": "attachment_1",
                "type": "file",
                "mime_type": "text/plain",
                "filename": "notes.txt",
                "path": "attachments/attachment_1_notes.txt",
            }
        ],
    )
    content = history[1]["content"]
    assert "attachments/attachment_1_notes.txt" in content
    assert "Hello world" not in content


def test_no_attachments_plain_text():
    """Without attachments, the user message is a plain string (saves tokens)."""
    from agentos.harness.context import build_message_history

    history = build_message_history("sys", [], "Hello", None)
    user_msg = history[1]
    assert user_msg["role"] == "user"
    assert isinstance(user_msg["content"], str)
    assert user_msg["content"] == "Hello"


def test_multiple_attachments_produce_one_reference_message():
    """Multiple attachments are listed without inline content."""
    from agentos.harness.context import build_message_history
    from agentos.pipeline import Attachment

    attachments = [
        Attachment(type="image", mime_type="image/png", data="abc123==", filename="a.png"),
        Attachment(type="image", mime_type="image/jpeg", data="def456==", filename="b.jpg"),
        Attachment(type="url", mime_type="text/uri-list", data="https://x.com", filename=""),
    ]
    history = build_message_history("sys", [], "Compare these", attachments)
    content = history[1]["content"]
    assert isinstance(content, str)
    assert "a.png" in content
    assert "b.jpg" in content
    assert "https://x.com" in content
    assert "abc123==" not in content
    assert "def456==" not in content


@pytest.mark.asyncio
async def test_harness_tool_call_then_answer(db, workspace):
    """Scripted model returns a tool call, then a final answer."""
    from agentos.sandbox import get_backend

    backend = get_backend()
    if not backend.is_available():
        pytest.skip("Sandbox backend not available")
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


def test_litellm_cached_token_usage_is_extracted():
    usage = SimpleNamespace(
        prompt_tokens_details=SimpleNamespace(cached_tokens=350),
    )
    assert LiteLLMAdapter._cached_tokens(usage) == 350

    anthropic_usage = SimpleNamespace(cache_read_input_tokens=275)
    assert LiteLLMAdapter._cached_tokens(anthropic_usage) == 275


@pytest.mark.asyncio
async def test_harness_preserves_cached_token_usage(db, workspace):
    config = AgentConfig(
        id="harness-cached-tokens",
        name="Cached Tokens Test",
        model=ModelConfig(provider_id="test", name="scripted"),
        capabilities=[],
    )
    model = ScriptedModel([ScriptedResponse(content="Done", tokens_in=500, cached_tokens=350)])

    result = await Harness(model=model).run(
        agent_config=config,
        session=None,
        message="test",
        syscall_handler=StubSyscallHandler(db=db, workspace_path=workspace),
        run_id=str(uuid.uuid4()),
    )

    assert result.tokens_in == 500
    assert result.cached_tokens == 350


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
    # message_complete is now emitted by runner.py, not the loop
    assert "message_complete" not in event_types

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


@pytest.mark.asyncio
async def test_provider_registry_selects_litellm_adapter(db):
    db.add(
        Provider(
            id="provider-openai",
            name="OpenAI",
            type="openai",
            base_url="https://api.openai.com/v1",
        )
    )
    db.add(
        Provider(
            id="provider-zen",
            name="OpenCode Zen",
            type="openai",
            base_url="https://opencode.ai/zen/v1",
        )
    )
    await db.commit()

    registry = ProviderRegistry(db)
    assert isinstance(await registry.for_provider("provider-openai"), LiteLLMProviderAdapter)
    assert isinstance(await registry.for_provider("provider-zen"), OpenCodeZenProviderAdapter)


def test_opencode_zen_routes_by_model_family():
    provider = {"type": "openai", "base_url": "https://opencode.ai/zen/v1"}

    assert OpenCodeZenProviderAdapter._model_family(provider, "gpt-5.2") == "responses"
    assert OpenCodeZenProviderAdapter._model_family(provider, "grok-4.5") == "responses"
    assert (
        OpenCodeZenProviderAdapter._model_family(provider, "claude-opus-4-8")
        == "anthropic_messages"
    )
    assert OpenCodeZenProviderAdapter._model_family(provider, "qwen3.7-max") == "anthropic_messages"
    assert OpenCodeZenProviderAdapter._model_family(provider, "gemini-3.5-flash") == "gemini"
    assert OpenCodeZenProviderAdapter._model_family(provider, "big-pickle") == "chat_completions"

    assert OpenCodeZenProviderAdapter._route_model(provider, "claude-opus-4-8")[0] == (
        "anthropic/claude-opus-4-8"
    )
    assert OpenCodeZenProviderAdapter._route_model(provider, "gpt-5.2")[0] == "openai/gpt-5.2"
    assert OpenCodeZenProviderAdapter._route_model(provider, "big-pickle")[0] == "openai/big-pickle"


@pytest.mark.asyncio
async def test_opencode_gpt_uses_responses_reasoning(monkeypatch):
    adapter = OpenCodeZenProviderAdapter(db=None)
    provider = {
        "type": "openai",
        "base_url": "https://opencode.ai/zen/v1",
        "api_key": "zen-key",
        "org_id": None,
        "extra_params": {},
    }

    async def load_provider(_provider_id):
        return provider

    captured = {}

    async def fake_aresponses(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(
            output=[
                SimpleNamespace(
                    type="message",
                    content=[SimpleNamespace(type="output_text", text="done")],
                )
            ],
            usage=SimpleNamespace(input_tokens=4, output_tokens=1),
            cost=0.0,
        )

    monkeypatch.setattr(adapter, "_load_provider", load_provider)
    monkeypatch.setattr("agentos.harness.litellm_adapter.litellm.aresponses", fake_aresponses)

    result = await adapter.complete(
        agent_model=ModelConfig(
            provider_id="zen",
            name="gpt-5.2",
            thinking_enabled=True,
            thinking_effort="high",
        ),
        messages=[{"role": "user", "content": "Review this"}],
    )

    assert result.content == "done"
    assert captured["model"] == "openai/gpt-5.2"
    assert captured["api_base"] == "https://opencode.ai/zen/v1"
    assert captured["reasoning"] == {"effort": "high"}
    assert "reasoning_effort" not in captured


def test_opencode_zen_reasoning_fields_match_endpoint():
    provider = {"type": "openai", "base_url": "https://opencode.ai/zen/v1"}

    kwargs: dict = {}
    OpenCodeZenProviderAdapter._apply_thinking_kwargs(
        kwargs,
        ModelConfig(provider_id="p", name="gpt-5.2", thinking_enabled=True, thinking_effort="high"),
        provider,
        "responses",
    )
    assert kwargs == {}

    kwargs = {}
    OpenCodeZenProviderAdapter._apply_thinking_kwargs(
        kwargs,
        ModelConfig(
            provider_id="p",
            name="claude-opus-4-8",
            thinking_enabled=True,
            thinking_effort="high",
        ),
        provider,
        "anthropic_messages",
    )
    assert kwargs == {"thinking": {"type": "enabled", "budget_tokens": 16384}}

    kwargs = {}
    OpenCodeZenProviderAdapter._apply_thinking_kwargs(
        kwargs,
        ModelConfig(
            provider_id="p",
            name="gemini-3.5-flash",
            thinking_enabled=True,
            thinking_effort="medium",
        ),
        provider,
        "gemini",
    )
    assert kwargs == {
        "extra_body": {"generationConfig": {"thinkingConfig": {"thinkingBudget": 8192}}}
    }

    kwargs = {}
    OpenCodeZenProviderAdapter._apply_thinking_kwargs(
        kwargs,
        ModelConfig(
            provider_id="p",
            name="big-pickle",
            thinking_enabled=True,
            thinking_effort="high",
        ),
        provider,
        "chat_completions",
    )
    assert kwargs == {"extra_body": {"reasoning_effort": "high"}}


def test_responses_input_converts_tool_turns():
    result = OpenCodeZenProviderAdapter._responses_input(
        [
            {"role": "user", "content": "Use the tool"},
            {
                "role": "assistant",
                "tool_calls": [
                    {"id": "call-1", "function": {"name": "lookup", "arguments": '{"q":"x"}'}}
                ],
            },
            {"role": "tool", "tool_call_id": "call-1", "content": "result"},
        ]
    )
    assert result[1] == {
        "type": "function_call",
        "call_id": "call-1",
        "name": "lookup",
        "arguments": '{"q":"x"}',
    }
    assert result[2] == {
        "type": "function_call_output",
        "call_id": "call-1",
        "output": "result",
    }
