"""W11 accounting glue — real capture_call_rates → assess → receipt on
every execution seam. Only transport + tokenizer are mocked."""

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from agentos.config_schema import ModelConfig
from agentos.harness.litellm_adapter import LiteLLMAdapter
from agentos.models import Base
from agentos.models.model_call import ModelCall
from agentos.models.provider import Provider
from agentos.secret_store import encrypt

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def db(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/t.db")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    # System-call ledger writes go through the module-global factory —
    # pin it to this temp DB so no row can reach real data.
    import agentos.db as db_module

    monkeypatch.setattr(db_module, "async_session_factory", factory)
    yield factory
    await engine.dispose()


async def _seed(db, *, pricing, model_id="m1", provider_type="openai"):
    """A configured provider + operator pricing override — the real
    public seam (update_override), not a raw resolved_json write."""
    from agentos.providers.model_catalog import update_override

    provider = Provider(
        id=str(uuid.uuid4()),
        name="P",
        type=provider_type,
        encrypted_key=encrypt("sk-test"),
        base_url=None,
        org_id=None,
        extra_params="{}",
        custom_models="[]",
    )
    async with db() as session:
        session.add(provider)
        await session.commit()
        pid = provider.id
    async with db() as session:
        await update_override(session, pid, model_id, {"pricing": pricing})
        await session.commit()
    return pid


def _usage(prompt, completion):
    return SimpleNamespace(
        prompt_tokens=prompt,
        completion_tokens=completion,
        prompt_tokens_details=None,
        completion_tokens_details=None,
        output_tokens_details=None,
    )


def _chat_response(usage, cost=None):
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(tool_calls=None, content="hi"),
            )
        ],
        usage=usage,
        cost=cost,
        _hidden_params={},
    )


def _make_adapter(session, completion=None, responses=None):
    adapter = LiteLLMAdapter(session)
    adapter.transport = SimpleNamespace(
        completion=AsyncMock(return_value=completion)
        if not callable(completion)
        else AsyncMock(side_effect=completion),
        responses=AsyncMock(return_value=responses)
        if not callable(responses)
        else AsyncMock(side_effect=responses),
    )
    return adapter


class TestExecutionAccounting:
    async def test_real_snapshot_rates_priced(self, db):
        """Real pricing row → the assessor computes the Decimal amount.
        Lead-known example: input 2 / output 10 per Mtok → 1000 in + 100 out
        = 0.003."""
        # anthropic-family → chat completions path
        pid = await _seed(db, pricing={"input": 2, "output": 10}, provider_type="anthropic")
        async with db() as session:
            adapter = _make_adapter(session, completion=_chat_response(_usage(1000, 100)))
            response = await adapter.complete(
                agent_model=ModelConfig(provider_id=pid, name="m1"),
                messages=[{"role": "user", "content": "hi"}],
            )
        assert float(response.cost) == 0.003
        assert response.cost_source == "user_rate"
        assert response.tokens_in == 1000 and response.tokens_out == 100
        assert response.cost_receipt["rate_authority"]["provider_id"] == pid
        assessment = response.cost_receipt["cost_assessment"]
        assert assessment["amount"] == "0.003" and assessment["source"] == "user_rate"

    async def test_capture_is_pre_call_frozen(self, db):
        """An override applied mid-RPC cannot rewrite the receipt — the
        snapshot was captured before the transport call."""
        from agentos.providers.model_catalog import update_override

        pid = await _seed(db, pricing={"input": 2, "output": 10}, provider_type="anthropic")

        async def mutate_during_call(**_kw):
            async with db() as session:
                await update_override(session, pid, "m1", {"pricing": {"input": 99, "output": 99}})
                await session.commit()
            return _chat_response(_usage(1000, 100))

        async with db() as session:
            adapter = _make_adapter(session, completion=mutate_during_call)
            response = await adapter.complete(
                agent_model=ModelConfig(provider_id=pid, name="m1"), messages=[]
            )
        # Pre-call rates stand — the mid-flight override is invisible.
        assert float(response.cost) == 0.003
        assert (
            response.cost_receipt["rate_authority"]["pricing_authority"]["source"]
            == "user_override"
        )

    async def test_no_rate_authority_preserves_reported_amount(self, db):
        """Capture-failure → unknown snapshot → a genuine provider amount
        (including explicit 0) still lands on the ledger."""
        # No offering row at all → capture produces the unknown snapshot.
        provider = Provider(
            id=str(uuid.uuid4()),
            name="P",
            type="custom",
            encrypted_key=encrypt("k"),
            base_url=None,
            org_id=None,
            extra_params="{}",
            custom_models="[]",
        )
        async with db() as session:
            session.add(provider)
            await session.commit()
            pid = provider.id
        async with db() as session:
            adapter = _make_adapter(
                session,
                completion=_chat_response(_usage(100, 50), cost=0.0),
            )
            response = await adapter.complete(
                agent_model=ModelConfig(provider_id=pid, name="m1"), messages=[]
            )
        # Explicit provider 0 is preserved — it is not "unknown".
        assert response.cost == 0.0
        assert response.cost_source == "provider"

    async def test_hidden_sdk_hint_never_billing(self, db):
        provider = Provider(
            id=str(uuid.uuid4()),
            name="P",
            type="custom",
            encrypted_key=encrypt("k"),
            base_url=None,
            org_id=None,
            extra_params="{}",
            custom_models="[]",
        )
        async with db() as session:
            session.add(provider)
            await session.commit()
            pid = provider.id
        raw = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(tool_calls=None, content="hi"))],
            usage=_usage(100, 50),
            _hidden_params={"response_cost": 9.9},
        )
        async with db() as session:
            adapter = _make_adapter(session, completion=raw)
            response = await adapter.complete(
                agent_model=ModelConfig(provider_id=pid, name="m1"), messages=[]
            )
        assert response.cost == 0.0
        assert response.cost_source == "unknown"

    async def test_stream_usage_chunk_with_choices_captured(self, db):
        pid = await _seed(db, pricing={"input": 2, "output": 10}, provider_type="anthropic")

        content_chunk = SimpleNamespace(
            choices=[
                SimpleNamespace(
                    delta=SimpleNamespace(
                        reasoning_content=None,
                        reasoning=None,
                        content="hi",
                        tool_calls=None,
                    )
                )
            ],
            usage=None,
        )
        # Usage rides the FINAL choices chunk — not a dedicated usage frame.
        final_chunk = SimpleNamespace(
            choices=[
                SimpleNamespace(
                    delta=SimpleNamespace(
                        reasoning_content=None,
                        reasoning=None,
                        content="!",
                        tool_calls=None,
                    )
                )
            ],
            usage=_usage(500, 50),
        )

        async def stream():
            yield content_chunk
            yield final_chunk

        async with db() as session:
            adapter = _make_adapter(session, completion=stream())
            final = None
            async for kind, payload in adapter.complete_stream(
                agent_model=ModelConfig(provider_id=pid, name="m1"), messages=[]
            ):
                if kind == "done":
                    final = payload
        assert final is not None
        assert final.tokens_in == 500 and final.tokens_out == 50
        assert float(final.cost) == 0.0015
        assert final.cost_receipt["rate_authority"]["provider_id"] == pid


def _responses_response(prompt, completion):
    return SimpleNamespace(
        output=[
            SimpleNamespace(
                type="message",
                content=[SimpleNamespace(type="output_text", text="hi")],
            )
        ],
        usage=SimpleNamespace(
            input_tokens=prompt,
            output_tokens=completion,
            output_tokens_details=None,
        ),
    )


class TestResponsesApiAccounting:
    async def test_responses_complete_real_snapshot(self, db):
        """openai-family → responses path, same real assessor."""
        pid = await _seed(db, pricing={"input": 2, "output": 10})
        async with db() as session:
            adapter = _make_adapter(session, responses=_responses_response(1000, 100))
            response = await adapter.complete(
                agent_model=ModelConfig(provider_id=pid, name="m1"),
                messages=[{"role": "user", "content": "hi"}],
            )
        assert float(response.cost) == 0.003
        assert response.cost_source == "user_rate"
        assert response.tokens_in == 1000 and response.tokens_out == 100
        assert response.cost_receipt["rate_authority"]["provider_id"] == pid

    async def test_responses_stream_receipt_without_completed_event(self, db):
        """No response.completed event → receipt still recorded with null
        usage / unknown amount — never guessed."""
        pid = await _seed(db, pricing={"input": 2, "output": 10})

        async def stream():
            yield SimpleNamespace(type="response.output_text.delta", delta="hi")

        async with db() as session:
            adapter = _make_adapter(session, responses=stream())
            final = None
            async for kind, payload in adapter.complete_stream(
                agent_model=ModelConfig(provider_id=pid, name="m1"), messages=[]
            ):
                if kind == "done":
                    final = payload
        assert final is not None
        assert final.tokens_in == 0 and final.tokens_out == 0
        assert final.cost_receipt is not None
        assert final.cost_receipt["cost_assessment"]["usage"] is None or (
            final.cost_receipt["cost_assessment"]["usage"]["input_tokens"] is None
        )


class TestCompactionBudget:
    async def test_budget_uses_resolved_metadata_not_sdk(self, monkeypatch):
        import litellm

        monkeypatch.setattr(
            litellm,
            "get_model_info",
            lambda *a, **k: (_ for _ in ()).throw(AssertionError("SDK metadata hit")),
            raising=False,
        )
        from agentos.harness.compaction import get_model_max_tokens

        resolved = {"max_context_tokens": 272000, "max_output_tokens": 32000}
        assert get_model_max_tokens("openai/gpt-6", resolved_model=resolved) == 272000
        resolved2 = {"context_window_tokens": 272000, "max_output_tokens": 32000}
        assert get_model_max_tokens("openai/gpt-6", resolved_model=resolved2) == 240000
        assert get_model_max_tokens("openai/mystery", resolved_model=None) == 32768
        assert (
            get_model_max_tokens("openai/gpt-6", override=100000, resolved_model=resolved) == 100000
        )

    async def test_known_context_output_conflict_surfaces(self):
        """A real context/output conflict is a configuration error — the
        helper raises instead of silently allocating the fallback."""
        import pytest

        from agentos.harness.compaction import get_model_max_tokens

        with pytest.raises(ValueError, match="no input capacity"):
            get_model_max_tokens(
                "openai/m",
                resolved_model={
                    "context_window_tokens": 8000,
                    "max_output_tokens": 32000,
                },
                output_tokens=8192,
            )

    async def test_compact_context_threshold_uses_provided_budget(self, monkeypatch):
        """input_budget drives the threshold — small budget triggers a
        summary RPC, large skips it entirely."""
        from agentos.config_schema import AgentConfig, CompactionConfig
        from agentos.harness.compaction import compact_context

        called = []

        async def fake_summary(*_a, **kw):
            called.append(kw)
            return "summary"

        monkeypatch.setattr("agentos.harness.compaction.generate_summary", fake_summary)

        # Constant 800 for the original-sizing calls keeps the historic
        # budget trigger (threshold 500 < 800); the reassembled summary
        # result tokenizes smaller so the ineffective-compaction guard
        # stays honest.
        def _count(msgs, *a, **k):
            msgs = list(msgs)
            if any(
                "[Previous conversation summary]" in str(m.get("content", ""))
                or str(m.get("content", "")) == "summary"
                for m in msgs
            ):
                return 5  # compacted result — much smaller than originals
            if len(msgs) == 30:
                return 800  # the whole original run
            return 300  # per-message sizing — tail keeps ~1 message

        monkeypatch.setattr("agentos.harness.compaction.count_tokens", _count)
        config = AgentConfig(
            id="a1",
            name="A",
            model=ModelConfig(provider_id="p", name="m", max_context_tokens=None),
            compaction=CompactionConfig(threshold=0.5),
        )
        history = [{"role": "user", "content": f"message {i}"} for i in range(30)]

        # budget 1000 → threshold 500 < 800 → compaction attempted.
        result = await compact_context(
            messages=history,
            agent_config=config,
            model_str="openai/m",
            input_budget=1000,
        )
        assert result.compacted is True and called

        called.clear()
        result = await compact_context(
            messages=history,
            agent_config=config,
            model_str="openai/m",
            input_budget=10000,
        )
        assert result.compacted is False and not called


class TestSummaryLedger:
    async def test_success_records_one_row_native_counters(self, db, monkeypatch):
        """No snapshot → unknown snapshot still yields normalized usage +
        native cost only, exactly one ledger row."""
        import litellm
        from sqlalchemy import select

        from agentos.harness.compaction import generate_summary
        from agentos.models.model_call import ModelCall

        monkeypatch.setattr(
            litellm,
            "acompletion",
            AsyncMock(
                return_value=SimpleNamespace(
                    choices=[SimpleNamespace(message=SimpleNamespace(content="sum"))],
                    usage=SimpleNamespace(
                        prompt_tokens=50,
                        completion_tokens=10,
                        prompt_tokens_details=None,
                        completion_tokens_details=None,
                    ),
                )
            ),
        )
        out = await generate_summary(
            [{"role": "user", "content": "x"}],
            None,
            "anthropic/m1",
            provider_id="p1",
            model_name="m1",
            agent_id="a1",
        )
        assert out == "sum"
        async with db() as session:
            rows = (await session.execute(select(ModelCall))).scalars().all()
        assert len(rows) == 1
        row = rows[0]
        assert row.kind == "chat" and row.purpose == "compaction"
        assert row.status == "ok"
        assert row.tokens_in == 50 and row.tokens_out == 10
        assert row.detail["operation"] == "compaction_summary"
        assert row.detail["cost_assessment"]["usage"]["input_tokens"] == 50
        assert row.detail["cost_source"] == "unknown"

    async def test_failure_records_one_error_row(self, db, monkeypatch):
        """Failed RPC → exactly one error row, no cost claim, fallback
        summary still returned."""
        import litellm
        from sqlalchemy import select

        from agentos.harness.compaction import generate_summary
        from agentos.models.model_call import ModelCall

        monkeypatch.setattr(
            litellm,
            "acompletion",
            AsyncMock(side_effect=TimeoutError("slow")),
        )
        with pytest.raises(TimeoutError):
            await generate_summary(
                [{"role": "user", "content": "x"}],
                None,
                "anthropic/m1",
                provider_id="p1",
                model_name="m1",
            )
        async with db() as session:
            rows = (await session.execute(select(ModelCall))).scalars().all()
        assert len(rows) == 1
        row = rows[0]
        assert row.status == "timeout"
        assert row.cost == 0.0
        assert row.tokens_in == 0
        assert "TimeoutError" in (row.error or "")


class TestEmbeddingAccounting:
    async def test_batch_capture_and_receipt_in_detail(self, db, monkeypatch):
        import litellm

        from agentos.knowledge.embeddings import EmbeddingResource, embed_texts

        pid = await _seed(db, pricing={"input": 2, "output": 10}, provider_type="anthropic")
        async with db() as session:
            provider = (
                await session.execute(select(Provider).where(Provider.id == pid))
            ).scalar_one()
        monkeypatch.setattr(
            "agentos.knowledge.embeddings._provider_for",
            AsyncMock(return_value=provider),
        )
        monkeypatch.setattr(
            "agentos.knowledge.embeddings.egress_permitted",
            lambda *a, **k: True,
        )
        monkeypatch.setattr(
            litellm,
            "completion_cost",
            lambda **kw: (_ for _ in ()).throw(AssertionError("SDK cost hit")),
            raising=False,
        )
        resp = SimpleNamespace(
            usage=SimpleNamespace(prompt_tokens=8),
            data=[{"embedding": [0.1]}],
        )
        monkeypatch.setattr(litellm, "aembedding", AsyncMock(return_value=resp))
        resource = EmbeddingResource(id="r1", provider_id=pid, model_name="m1")
        async with db() as session:
            vectors = await embed_texts(session, resource, ["hello"])
            await session.commit()
        assert vectors == [[0.1]]

        async with db() as session:
            row = (await session.execute(select(ModelCall))).scalar_one()
        assert row.tokens_in == 8
        assert row.detail["resource_id"] == "r1"
        assert row.detail["cost_source"] == "user_rate"
        assert "cost_assessment" in row.detail

    async def test_total_tokens_fallback_priced(self, db, monkeypatch):
        """Embedding usage carrying only total_tokens → canonical
        input_tokens 8; 8 tokens @ 2/Mtok = 0.000016 (output 0)."""
        import litellm

        from agentos.knowledge.embeddings import EmbeddingResource, embed_texts

        pid = await _seed(db, pricing={"input": 2, "output": 10}, provider_type="anthropic")
        async with db() as session:
            provider = (
                await session.execute(select(Provider).where(Provider.id == pid))
            ).scalar_one()
        monkeypatch.setattr(
            "agentos.knowledge.embeddings._provider_for",
            AsyncMock(return_value=provider),
        )
        monkeypatch.setattr(
            "agentos.knowledge.embeddings.egress_permitted",
            lambda *a, **k: True,
        )
        resp = SimpleNamespace(
            usage={"total_tokens": 8},
            data=[{"embedding": [0.1]}],
        )
        monkeypatch.setattr(litellm, "aembedding", AsyncMock(return_value=resp))
        resource = EmbeddingResource(id="r2", provider_id=pid, model_name="m1")
        async with db() as session:
            await embed_texts(session, resource, ["hello"])
            await session.commit()
        async with db() as session:
            row = (await session.execute(select(ModelCall))).scalar_one()
        assert row.tokens_in == 8
        assert abs(row.cost - 0.000016) < 1e-9
        assessment = row.detail["cost_assessment"]
        assert assessment["usage"]["input_tokens"] == 8
        assert assessment["amount"] == "0.000016"
        assert row.detail["cost_source"] == "user_rate"
