"""W10 accounting — non-run model calls land on the same ledger:
provider validation probes, memory extraction, session titles."""

from types import SimpleNamespace

import pytest
from sqlalchemy import select

from agentos.harness.scripted_model import ScriptedResponse
from agentos.models.model_call import ModelCall
from agentos.services.model_ledger import response_cost


async def _calls(db):
    return (await db.execute(select(ModelCall))).scalars().all()


def _usage(**kw):
    return SimpleNamespace(
        prompt_tokens=kw.get("tin", 5),
        completion_tokens=kw.get("tout", 1),
        prompt_tokens_details=kw.get("prompt_details"),
        completion_tokens_details=kw.get("completion_details"),
    )


def _agent_config():
    from agentos.config_schema import AgentConfig, ModelConfig

    return AgentConfig(
        id="acc-agent",
        name="Acc Agent",
        model=ModelConfig(provider_id="p1", name="m1"),
    )


class _StubAdapter:
    """Enough of LiteLLMAdapter's surface for the catalog probe."""

    def __init__(self, raw=None, error=None, family="chat"):
        self._raw = raw
        self._error = error
        self._family = family

        async def completion(**kwargs):
            if self._error:
                raise self._error
            return self._raw

        async def responses(**kwargs):
            if self._error:
                raise self._error
            return self._raw

        self.transport = SimpleNamespace(completion=completion, responses=responses)

    async def _load_provider(self, provider_id):
        return {
            "type": "openai",
            "api_key": None,
            "base_url": None,
            "extra_params": {},
        }

    def _route_model(self, provider, name):
        return (f"openai/{name}", None)

    def _model_family(self, provider, name):
        return self._family

    async def complete(self, agent_model, messages, tools):
        if self._error:
            raise self._error
        return self._raw


async def test_probe_chat_records_ledger_row(db):
    from agentos.providers.model_catalog import LiteLLMModelCatalog

    raw = {
        "usage": {"prompt_tokens": 9, "completion_tokens": 1},
        "_hidden_params": {"response_cost": 0.0025},
    }
    catalog = LiteLLMModelCatalog(_StubAdapter(raw=raw))
    assert await catalog.validate_model("p1", "m1") is True

    rows = await _calls(db)
    assert len(rows) == 1
    row = rows[0]
    assert row.kind == "probe"
    assert row.purpose == "reasoning"
    assert row.run_id is None and row.agent_id is None
    assert row.provider_id == "p1" and row.model_name == "m1"
    assert row.tokens_in == 9 and row.tokens_out == 1
    # W11: hidden SDK cost hints are not billing — no local authority → unknown.
    assert row.cost == 0.0
    # Canonical receipt keys ride alongside the legacy fields — the probe's
    # rate capture failed (no catalog row), so usage/cost stay unknown.
    assert row.detail["operation"] == "validate"
    assert row.detail["cost_source"] == "unknown"
    assert row.detail["cost_assessment"]["amount"] is None
    assert row.detail["rate_authority"]["pricing_authority"]["source"] == "unknown"


async def test_probe_responses_uses_responses_usage(db):
    from agentos.providers.model_catalog import LiteLLMModelCatalog

    usage = SimpleNamespace(
        input_tokens=7,
        output_tokens=2,
        output_tokens_details=SimpleNamespace(reasoning_tokens=1),
    )
    raw = SimpleNamespace(usage=usage, _hidden_params={"response_cost": 0.001})
    catalog = LiteLLMModelCatalog(_StubAdapter(raw=raw, family="responses"))
    assert await catalog.validate_model("p1", "m1") is True

    row = (await _calls(db))[0]
    assert row.tokens_in == 7 and row.tokens_out == 2
    assert row.thinking_tokens == 1
    assert row.detail["cost_source"] == "unknown"


async def test_probe_error_and_timeout_status(db):
    from agentos.providers.model_catalog import LiteLLMModelCatalog

    catalog = LiteLLMModelCatalog(_StubAdapter(error=TimeoutError("slow")))
    with pytest.raises(TimeoutError):
        await catalog.validate_model("p1", "m1")
    row = (await _calls(db))[0]
    assert row.status == "timeout"
    assert row.tokens_in == 0 and row.tokens_out == 0

    catalog = LiteLLMModelCatalog(_StubAdapter(error=RuntimeError("refused")))
    with pytest.raises(RuntimeError):
        await catalog.validate_model("p1", "m1")
    rows = await _calls(db)
    assert rows[-1].status == "error"
    # Provider error bodies may echo private request content — the
    # receipt records the exception TYPE only.
    assert rows[-1].error == "RuntimeError"


async def test_title_generation_records_row(db, monkeypatch):
    from agentos import pipeline
    from agentos.providers import ProviderRegistry

    config = _agent_config()
    monkeypatch.setattr(
        ProviderRegistry,
        "for_model",
        lambda self, pid: _AsyncStub(
            ScriptedResponse(content="A Nice Title", tokens_in=11, tokens_out=4, cost=0.01)
        ),
    )
    title = await pipeline._generate_session_title(db, config, "hi", "hello")
    assert title == "A Nice Title"

    row = (await _calls(db))[0]
    assert row.kind == "title"
    assert row.agent_id == "acc-agent"
    assert row.run_id is None
    assert row.tokens_in == 11 and row.tokens_out == 4
    assert row.detail == {"operation": "session_title"}


async def test_title_records_run_session_link(db, monkeypatch):
    """Title calls carry the triggering run + session so they surface in
    the run's trace instead of as run-less ledger rows."""
    from agentos import pipeline
    from agentos.providers import ProviderRegistry

    config = _agent_config()
    monkeypatch.setattr(
        ProviderRegistry,
        "for_model",
        lambda self, pid: _AsyncStub(
            ScriptedResponse(content="Linked Title", tokens_in=5, tokens_out=2, cost=0.0)
        ),
    )
    await pipeline._generate_session_title(
        db, config, "hi", "hello", run_id="run-x", session_id="sess-x"
    )
    row = (await _calls(db))[0]
    assert row.kind == "title"
    assert row.run_id == "run-x"
    assert row.session_id == "sess-x"


async def test_title_prompt_uses_latest_messages(db, monkeypatch):
    """Selection must pick the conversation's END, not its start — the
    title should describe what the session ended up being about."""
    from types import SimpleNamespace

    from agentos import pipeline
    from agentos.providers import ProviderRegistry

    seen = {}

    class _Probe(_AsyncStub):
        async def complete(self, agent_model, messages, tools):
            seen["prompt"] = messages[0]["content"]
            return ScriptedResponse(content="T", tokens_in=1, tokens_out=1)

    monkeypatch.setattr(ProviderRegistry, "for_model", lambda self, pid: _Probe())
    config = _agent_config()

    # Oldest-first, as _bg_title supplies it — 9 user/assistant turns.
    msgs = [
        SimpleNamespace(role="user" if i % 2 == 0 else "assistant", content=f"turn-{i}")
        for i in range(9)
    ] + [SimpleNamespace(role="tool_call", content="ignore me")]

    await pipeline._generate_session_title_from_history(db, config, msgs)

    prompt = seen["prompt"]
    # Latest 6 = turn-8..turn-3 (tool_call row excluded), chronological.
    assert "turn-8" in prompt and "turn-3" in prompt
    assert "turn-0" not in prompt and "turn-2" not in prompt
    assert prompt.index("turn-3") < prompt.index("turn-8")


async def test_title_error_row_and_fallback_unchanged(db, monkeypatch):
    from agentos import pipeline
    from agentos.providers import ProviderRegistry

    config = _agent_config()
    monkeypatch.setattr(
        ProviderRegistry,
        "for_model",
        lambda self, pid: _AsyncStub(error=RuntimeError("provider down")),
    )
    title = await pipeline._generate_session_title(db, config, "hi", "hello")
    assert title is None  # fallback preserved

    row = (await _calls(db))[0]
    assert row.kind == "title" and row.status == "error"


async def test_memory_extract_records_row_and_error(db, monkeypatch):
    from agentos.memory import auto_extract
    from agentos.providers import ProviderRegistry

    config = _agent_config()
    from agentos.memory import notebook

    monkeypatch.setattr(notebook, "read_memory", lambda agent_id: "")
    monkeypatch.setattr(notebook, "write_memory", lambda *a, **k: None)
    monkeypatch.setattr(
        ProviderRegistry,
        "for_model",
        lambda self, pid: _AsyncStub(
            ScriptedResponse(
                content='{"memories": [], "clarifications": [], "core_markdown": null, "core_source_ids": []}',
                tokens_in=20,
                tokens_out=2,
            )
        ),
    )
    # Extraction now only considers real persisted parent-run messages —
    # seed the run/session/messages it can cite.
    import uuid as _uuid

    from agentos.models.run import Message, Run
    from agentos.models.session import Session

    session = Session(id=str(_uuid.uuid4()), agent_id="acc-agent", contact_id="c1")
    run = Run(
        id=str(_uuid.uuid4()),
        session_id=session.id,
        contact_id="c1",
        agent_id="acc-agent",
        status="completed",
    )
    db.add_all([session, run])
    await db.commit()
    m1 = Message(id=str(_uuid.uuid4()), run_id=run.id, role="user", content="remember me", seq=0)
    m2 = Message(id=str(_uuid.uuid4()), run_id=run.id, role="assistant", content="ok", seq=1)
    db.add_all([m1, m2])
    await db.commit()
    messages = [m1, m2]
    await auto_extract.auto_extract_memory(
        db,
        config,
        agent_id="acc-agent",
        messages=messages,
        run_id=run.id,
        contact_id="c1",
        session_id=session.id,
    )
    row = (await _calls(db))[0]
    assert row.kind == "extract"
    assert row.agent_id == "acc-agent"
    assert row.run_id == run.id  # original run traced exactly
    assert row.detail == {"operation": "memory_extract"}

    monkeypatch.setattr(
        ProviderRegistry,
        "for_model",
        lambda self, pid: _AsyncStub(error=TimeoutError("t")),
    )
    with pytest.raises(TimeoutError):
        await auto_extract.auto_extract_memory(
            db,
            config,
            agent_id="acc-agent",
            messages=messages,
            run_id=run.id,
            contact_id="c1",
            session_id=session.id,
        )
    rows = await _calls(db)
    assert len(rows) == 2  # extraction raises but the row exists
    assert rows[-1].status == "timeout"


async def test_normal_harness_call_writes_one_ledger_row(db, workspace):
    """record_system_call never double-records — a harness run's model
    call lands exactly once, from the harness."""
    import uuid

    from agentos.harness.loop import Harness
    from agentos.harness.scripted_model import ScriptedModel
    from agentos.syscall.mediator import SyscallHandler

    run_id = str(uuid.uuid4())
    result = await Harness(
        model=ScriptedModel([ScriptedResponse(content="done", tokens_in=3, tokens_out=2)])
    ).run(
        agent_config=_agent_config(),
        session=None,
        message="hi",
        syscall_handler=SyscallHandler(db=db, workspace_path=workspace),
        run_id=run_id,
    )
    assert result.error is None
    rows = await _calls(db)
    assert len(rows) == 1
    assert rows[0].run_id == run_id
    assert rows[0].kind == "chat"


def test_response_cost_recipe():
    # A genuine provider amount wins — an explicit 0 counts as reported.
    raw = {"cost": 0.0, "_hidden_params": {"response_cost": 5.0}}
    assert response_cost(raw, "m") == (0.0, "provider")
    # W11: SDK-hidden cost hints are deliberately ignored, never billing.
    raw = {"_hidden_params": {"response_cost": 0.125}}
    assert response_cost(raw, "m") == (0.0, "unknown")
    raw = SimpleNamespace(cost=None, _hidden_params={})
    cost, source = response_cost(raw, "definitely-not-a-real-model-xyz")
    assert source == "unknown"
    assert isinstance(cost, float)


class _AsyncStub:
    """Awaitable adapter stub for ProviderRegistry.for_model."""

    def __init__(self, response=None, error=None):
        self._response = response
        self._error = error

    def __await__(self):
        async def _go():
            return self

        return _go().__await__()

    async def get_model_info(self, model):
        return {
            "model_str": "test-model",
            "resolved_model": {"context_window_tokens": 32768},
        }

    async def complete(self, agent_model, messages, tools):
        if self._error:
            raise self._error
        return self._response
