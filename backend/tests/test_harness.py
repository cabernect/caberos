"""Test the harness loop with a scripted model double."""

import asyncio
import uuid
from types import SimpleNamespace

import pytest

from agentos.config import settings
from agentos.config_schema import AgentConfig, CapabilityGrant, ModelConfig
from agentos.harness.context import assemble_system_prompt
from agentos.harness.litellm_adapter import LiteLLMAdapter
from agentos.harness.loop import ApprovalBatch, Harness
from agentos.harness.scripted_model import ScriptedModel, ScriptedResponse
from agentos.knowledge.ingest import ingest_document
from agentos.models.provider import Provider
from agentos.providers import ProviderRegistry
from agentos.providers.registry import LiteLLMProviderAdapter, OpenCodeZenProviderAdapter
from agentos.syscall.mediator import StubSyscallHandler
from agentos.syscall.protocol import SyscallResult


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


def test_language_rule_covers_thinking():
    """The base prompt's language rule covers both output and thinking."""
    config = AgentConfig(
        id="test",
        name="Test",
        model=ModelConfig(provider_id="test", name="scripted"),
        capabilities=[],
    )
    prompt = assemble_system_prompt(config)
    assert "Match the user's language" in prompt
    assert "thinking and replies" in prompt
    assert "Stay consistent" in prompt


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
    assert any(tok == "https://example.com" for tok in user_msg["content"].split())
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
                "path": "attachments/notes.txt",
            }
        ],
    )
    content = history[1]["content"]
    assert "attachments/notes.txt" in content
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
    assert any(tok == "https://x.com" for tok in content.split())
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


async def _make_run_rows(db, agent_id: str, run_id: str):
    from agentos.models.agent import Agent
    from agentos.models.contact import Contact
    from agentos.models.run import Run
    from agentos.models.session import Session

    agent = Agent(id=agent_id, name="Test Agent", enabled=True)
    contact = Contact(
        id=f"c-{run_id}", channel="dashboard_chat", bot_id=agent_id, external_user_id="e"
    )
    session = Session(id=f"s-{run_id}", contact_id=contact.id, agent_id=agent_id)
    run = Run(id=run_id, session_id=session.id, contact_id=contact.id, agent_id=agent_id)
    db.add_all([agent, contact, session, run])
    await db.commit()
    return session


@pytest.mark.asyncio
async def test_harness_records_each_model_call(db, workspace):
    """Every model request lands as a ModelCall row with turn, tokens, status."""
    from sqlalchemy import select

    from agentos.models.model_call import ModelCall
    from agentos.syscall.mediator import SyscallHandler

    await _make_run_rows(db, "a-mc", "r-mc")
    config = AgentConfig(
        id="a-mc",
        name="MC Agent",
        model=ModelConfig(provider_id="test-provider", name="test-model"),
        capabilities=[CapabilityGrant(name="datetime_now")],
    )
    model = ScriptedModel(
        [
            ScriptedResponse(
                tool_calls=[{"id": "t1", "name": "datetime_now", "args": {}}],
                content="",
                tokens_in=10,
                tokens_out=5,
            ),
            ScriptedResponse(tool_calls=[], content="done", tokens_in=20, tokens_out=8),
        ]
    )

    result = await Harness(model=model).run(
        agent_config=config,
        session=None,
        message="hi",
        syscall_handler=SyscallHandler(db=db, workspace_path=workspace),
        run_id="r-mc",
    )
    assert result.status == "completed"

    rows = (await db.execute(select(ModelCall).where(ModelCall.run_id == "r-mc"))).scalars().all()
    assert len(rows) == 2
    assert {r.turn for r in rows} == {1, 2}
    assert all(r.status == "ok" for r in rows)
    assert rows[0].tokens_in == 10
    assert rows[1].tokens_in == 20
    assert all(r.provider_id == "test-provider" for r in rows)


@pytest.mark.asyncio
async def test_harness_records_failed_model_call(db, workspace):
    """A provider exception still leaves a ModelCall row with status=error."""
    from sqlalchemy import select

    from agentos.models.model_call import ModelCall
    from agentos.syscall.mediator import SyscallHandler

    await _make_run_rows(db, "a-mf", "r-mf")
    config = AgentConfig(
        id="a-mf",
        name="MF Agent",
        model=ModelConfig(provider_id="test-provider", name="test-model"),
        capabilities=[],
    )

    class BrokenModel:
        async def complete(self, **_kwargs):
            raise RuntimeError("provider exploded")

    result = await Harness(model=BrokenModel()).run(
        agent_config=config,
        session=None,
        message="hi",
        syscall_handler=SyscallHandler(db=db, workspace_path=workspace),
        run_id="r-mf",
    )
    assert result.status == "failed"

    row = await db.scalar(select(ModelCall).where(ModelCall.run_id == "r-mf"))
    assert row is not None
    assert row.status == "error"
    assert "provider exploded" in row.error


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
async def test_harness_runs_multiple_tool_calls_concurrently(db, workspace):
    config = AgentConfig(
        id="harness-serial-tools",
        name="Serialized Tools Test",
        model=ModelConfig(provider_id="test", name="scripted"),
        capabilities=[CapabilityGrant(name="read_file")],
    )
    model = ScriptedModel(
        [
            ScriptedResponse(
                tool_calls=[
                    {"id": "read-1", "name": "read_file", "args": {"path": "one.txt"}},
                    {"id": "read-2", "name": "read_file", "args": {"path": "two.txt"}},
                    {"id": "read-3", "name": "read_file", "args": {"path": "three.txt"}},
                ]
            ),
            ScriptedResponse(content="Done"),
        ]
    )

    class RecordingSyscall:
        def __init__(self):
            self.active = 0
            self.max_active = 0
            self.order: list[str] = []

        async def mediate(self, call, **kwargs):
            self.active += 1
            self.max_active = max(self.max_active, self.active)
            self.order.append(call.id)
            await asyncio.sleep(0)
            self.active -= 1
            return SyscallResult(output={"path": call.args["path"]}, allowed=True)

    syscall = RecordingSyscall()
    result = await Harness(model=model).run(
        agent_config=config,
        session=None,
        message="Read three files",
        syscall_handler=syscall,
        run_id=str(uuid.uuid4()),
    )

    assert result.status == "completed"
    assert syscall.max_active == 3
    assert syscall.order == ["read-1", "read-2", "read-3"]


@pytest.mark.asyncio
async def test_approval_batch_waits_for_all_decisions():
    batch = ApprovalBatch(["a", "b", "c"])
    tasks = [
        asyncio.create_task(batch.arrive("a", True)),
        asyncio.create_task(batch.arrive("b", False)),
    ]

    await asyncio.sleep(0)
    assert not any(task.done() for task in tasks)
    tasks.append(asyncio.create_task(batch.arrive("c", True)))
    assert await asyncio.gather(*tasks) == [True, False, True]


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


@pytest.mark.asyncio
async def test_agent_answers_question_using_doc_search(db, workspace, tmp_path):
    root = tmp_path / "knowledge"
    root.mkdir()
    path = root / "guide.md"
    path.write_text("The deployment requires a signed release tag.", encoding="utf-8")
    await ingest_document(db, path, root)
    await db.commit()

    config = AgentConfig(
        id="knowledge-agent",
        name="Knowledge Agent",
        model=ModelConfig(provider_id="test", name="scripted"),
        soul="Test soul.",
        capabilities=[CapabilityGrant(name="doc_search", require_approval=False)],
    )
    model = ScriptedModel(
        [
            ScriptedResponse(
                tool_calls=[
                    {"id": "call-doc", "name": "doc_search", "args": {"query": "release tag"}}
                ]
            ),
            ScriptedResponse(content="The deployment requires a signed release tag."),
        ]
    )

    result = await Harness(model=model).run(
        agent_config=config,
        session=None,
        message="What does deployment require?",
        syscall_handler=StubSyscallHandler(db=db, workspace_path=workspace),
        run_id=str(uuid.uuid4()),
    )

    assert result.final_answer == "The deployment requires a signed release tag."
    assert result.tool_calls_made[0]["name"] == "doc_search"
    assert result.tool_calls_made[0]["allowed"] is True
    assert result.tool_calls_made[0]["result"]["count"] == 1


@pytest.mark.asyncio
async def test_tool_result_hard_cap(db, workspace):
    """A single tool result can never exceed TOOL_RESULT_MAX_CHARS in history."""
    from agentos.harness.loop import TOOL_RESULT_MAX_CHARS
    from agentos.syscall.protocol import SyscallResult

    class RecordingModel(ScriptedModel):
        def __init__(self, responses):
            super().__init__(responses)
            self.seen: list[list[dict]] = []

        async def complete_stream(self, agent_model=None, messages=None, tools=None, **kw):
            self.seen.append(messages)
            async for item in super().complete_stream(
                agent_model=agent_model, messages=messages, tools=tools
            ):
                yield item

    class GiantSyscall:
        async def mediate(self, call, **kwargs):
            return SyscallResult(output={"content": "x" * 60_000}, allowed=True)

    config = AgentConfig(
        id="cap-test",
        name="Cap Test",
        model=ModelConfig(provider_id="test", name="scripted"),
        capabilities=[CapabilityGrant(name="read_file")],
    )
    model = RecordingModel(
        [
            ScriptedResponse(
                tool_calls=[{"id": "r1", "name": "read_file", "args": {"path": "big.txt"}}]
            ),
            ScriptedResponse(content="done"),
        ]
    )
    result = await Harness(model=model).run(
        agent_config=config,
        session=None,
        message="read big.txt",
        syscall_handler=GiantSyscall(),
        run_id=str(uuid.uuid4()),
    )
    assert result.status == "completed"
    tool_msg = next(m for m in model.seen[1] if m["role"] == "tool")
    assert len(tool_msg["content"]) < 60_000
    assert "[truncated" in tool_msg["content"]
    assert str(TOOL_RESULT_MAX_CHARS) in tool_msg["content"]


@pytest.mark.asyncio
async def test_context_overflow_forces_compaction_and_retries(
    db, workspace, monkeypatch
):
    """A mid-run context-window error triggers one forced compaction + retry."""
    from types import SimpleNamespace

    from agentos.harness import compaction as compaction_mod

    async def fake_summary(middle, previous_summary, model_str, api_key=None, base_url=None):
        return "condensed earlier conversation"

    monkeypatch.setattr(compaction_mod, "generate_summary", fake_summary)

    class OverflowOnceModel(ScriptedModel):
        def __init__(self, responses):
            super().__init__(responses)
            self.overflows = 0
            self.seen: list[list[dict]] = []

        async def complete_stream(self, agent_model=None, messages=None, tools=None, **kw):
            if self.overflows == 0:
                self.overflows += 1
                raise Exception(
                    "Error code: 400 — this model's maximum context length is 8192 tokens"
                )
            self.seen.append(messages)
            async for item in super().complete_stream(
                agent_model=agent_model, messages=messages, tools=tools
            ):
                yield item

    # Prior messages fat enough that the token-budget tail walk stops before
    # reaching the head — leaving a middle section for compaction to summarize
    # (tail budget ≈ 18k tokens; ~4k chars ≈ ~1k tokens per message).
    recent = [
        SimpleNamespace(
            role="user" if i % 2 == 0 else "assistant", content=f"msg {i} " + "y" * 4000
        )
        for i in range(26)
    ]
    config = AgentConfig(
        id="overflow-test",
        name="Overflow Test",
        model=ModelConfig(provider_id="test", name="scripted"),
        capabilities=[],
    )
    model = OverflowOnceModel([ScriptedResponse(content="recovered")])
    result = await Harness(model=model).run(
        agent_config=config,
        session=None,
        message="continue",
        syscall_handler=StubSyscallHandler(db=db, workspace_path=workspace),
        run_id=str(uuid.uuid4()),
        recent_messages=recent,
    )
    assert result.status == "completed"
    assert result.final_answer == "recovered"
    assert result.compacted is True
    assert model.overflows == 1
    # The retry saw a compacted history — the summary stub replaced the middle.
    retry_text = str(model.seen[0])
    assert "condensed earlier conversation" in retry_text
    assert "msg 25" in retry_text  # tail survived


@pytest.mark.asyncio
async def test_context_overflow_fails_clearly_when_unrecoverable(db, workspace):
    """If compaction cannot shrink the context, the run fails with a clear message."""

    class AlwaysOverflowModel:
        async def complete_stream(self, **_kwargs):
            raise Exception("request too large for model context window")
            yield

    config = AgentConfig(
        id="overflow-fail",
        name="Overflow Fail",
        model=ModelConfig(provider_id="test", name="scripted"),
        capabilities=[],
    )
    result = await Harness(model=AlwaysOverflowModel()).run(
        agent_config=config,
        session=None,
        message="hi",
        syscall_handler=StubSyscallHandler(db=db, workspace_path=workspace),
        run_id=str(uuid.uuid4()),
    )
    assert result.status == "failed"
    assert "context" in result.final_answer.lower()


def test_is_context_overflow_patterns():
    from agentos.harness.loop import _is_context_overflow

    assert _is_context_overflow(Exception("maximum context length is 8192"))
    assert _is_context_overflow(Exception("Request too large for model"))
    assert _is_context_overflow(Exception("reduce the length of the messages"))

    class ContextWindowExceededError(Exception):
        pass

    assert _is_context_overflow(ContextWindowExceededError("litellm style"))
    assert not _is_context_overflow(Exception("rate limit exceeded"))
    assert not _is_context_overflow(TimeoutError("idle"))
