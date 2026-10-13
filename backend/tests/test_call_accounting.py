"""Call accounting keeps the authority selected before execution."""

import json
import uuid
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agentos.models.provider import Provider
from agentos.providers import catalog as catalog_module
from agentos.providers.catalog import CatalogSnapshot
from agentos.providers.model_catalog import update_override
from agentos.services.call_accounting import capture_call_rates


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "base_url", [None, "https://api.openai.com/v1", "https://proxy.example/v1"]
)
async def test_native_openai_catalog_context_tiers_reach_call_assessment(
    db, tmp_path, monkeypatch, base_url
):
    pricing = {
        "input": 0.2,
        "output": 1.2,
        "cache_read": 0.02,
        "cache_write": 0.25,
        "tiers": [
            {
                "input": 0.4,
                "output": 1.8,
                "cache_read": 0.04,
                "cache_write": 0.5,
                "tier": {"type": "context", "size": 272000},
            }
        ],
        "context_over_200k": {
            "input": 0.4,
            "output": 1.8,
            "cache_read": 0.04,
            "cache_write": 0.5,
        },
    }
    bundled = tmp_path / "catalog.json"
    bundled.write_text(
        json.dumps(
            {"openai": {"models": {"tiered-model": {"name": "Tiered model", "cost": pricing}}}}
        )
    )
    snapshot = CatalogSnapshot(store_dir=tmp_path / "store", bundled_path=bundled)
    monkeypatch.setattr(catalog_module, "_snapshot", snapshot)
    provider = Provider(name="OpenAI transport", type="openai", base_url=base_url)
    db.add(provider)
    await db.flush()
    config = {"type": "openai", "base_url": base_url, "org_id": None, "extra_params": {}}
    proxy = base_url == "https://proxy.example/v1"
    if proxy:
        await update_override(
            db,
            provider.id,
            "tiered-model",
            {},
            catalog_provider_id="openai",
            catalog_model_id="tiered-model",
        )
    captured = await capture_call_rates(db, provider.id, "tiered-model", config)

    # Recorded Caber usage: cached input replaces ordinary input charges;
    # reasoning is already included in output. Expectations are independent.
    for inputs, outputs, cached, reasoning, expected in (
        (14335, 143, 0, 86, "0.0030386"),
        (15669, 88, 14332, 47, "0.00065964"),
        (2010, 67, 0, 56, "0.0004824"),
        (272001, 88, 271000, 47, "0.0113988"),
    ):
        assessment = captured.assess(
            {
                "usage": {
                    "input_tokens": inputs,
                    "output_tokens": outputs,
                    "input_tokens_details": {"cached_tokens": cached},
                    "output_tokens_details": {"reasoning_tokens": reasoning},
                }
            },
            family="responses",
        )
        if proxy:
            assert assessment.amount is None
            assert assessment.reason == "unsupported_context_tier_basis"
        else:
            assert assessment.amount == Decimal(expected)
            assert assessment.source == "models_dev"
            assert assessment.reason is None
            assert captured.receipt(assessment)["rate_authority"]["context_tier_basis"] == (
                "aggregate_input"
            )


@pytest.mark.asyncio
async def test_rate_change_during_execution_does_not_reprice_captured_call(db_engine):
    factory = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)
    provider_id = str(uuid.uuid4())
    config = {
        "type": "openai",
        "api_key": "",
        "base_url": None,
        "org_id": None,
        "extra_params": {},
    }
    async with factory() as db:
        db.add(Provider(id=provider_id, name="Accounting fixture", type="openai"))
        await db.commit()
        await update_override(
            db, provider_id, "fixture-model", {"pricing": {"input": "2", "output": "10"}}
        )
        await db.commit()
        captured = await capture_call_rates(db, provider_id, "fixture-model", config)
        await update_override(
            db, provider_id, "fixture-model", {"pricing": {"input": "4", "output": "20"}}
        )
        await db.commit()
        updated = await capture_call_rates(db, provider_id, "fixture-model", config)
    response = {"usage": {"prompt_tokens": 1000, "completion_tokens": 100}}
    original = captured.assess(response, family="chat")
    assert original.amount == Decimal("0.003")
    assert original.source == "user_rate"
    assert updated.assess(response, family="chat").amount == Decimal("0.006")
    assert captured.receipt(original)["rate_authority"]["request_model_id"] == "fixture-model"


@pytest.mark.asyncio
async def test_unresolved_routing_does_not_override_genuine_reported_zero(db_engine):
    factory = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)
    provider_id = str(uuid.uuid4())
    config = {
        "type": "openrouter",
        "api_key": "",
        "base_url": None,
        "org_id": None,
        "extra_params": {"model": "other-model"},
    }
    async with factory() as db:
        db.add(Provider(id=provider_id, name="Accounting fixture", type="openrouter"))
        await db.commit()
        await update_override(
            db, provider_id, "fixture-model", {"pricing": {"input": "2", "output": "10"}}
        )
        await db.commit()
        captured = await capture_call_rates(db, provider_id, "fixture-model", config)
    missing = captured.assess(
        {"usage": {"prompt_tokens": 1000, "completion_tokens": 100}}, family="chat"
    )
    assert missing.amount is None
    reported = captured.assess({"usage": {"cost": "0"}}, family="chat")
    assert reported.amount == Decimal(0)
    assert reported.source == "provider"
    assert captured.receipt(reported)["rate_authority"]["routing_override_unresolved"] is True
