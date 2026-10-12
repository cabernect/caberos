"""Call accounting keeps the authority selected before execution."""

import uuid
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agentos.models.provider import Provider
from agentos.providers.model_catalog import update_override
from agentos.services.call_accounting import capture_call_rates


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
