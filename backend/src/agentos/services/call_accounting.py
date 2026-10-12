"""Capture local rate authority before execution; assess immutable call receipts."""

import json
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ..providers.model_catalog import get_offering
from .cost_assessment import CostAssessment, assess_usage
from .usage_receipts import normalize_usage, reported_amount

_ROUTING_OVERRIDES = {
    "model",
    "api_key",
    "api_base",
    "base_url",
    "custom_llm_provider",
    "deployment_id",
    "api_type",
    "organization",
    "organization_id",
}


@dataclass(frozen=True)
class CallRateSnapshot:
    provider_type: str
    pricing_json: str
    provenance_json: str
    model_metadata_json: str = "{}"
    rate_source: str = "models_dev"
    snapshot_revision: str | None = None
    context_tier_basis: str | None = None

    def assess(self, raw: Any, *, family: str) -> CostAssessment:
        usage = normalize_usage(raw, family=family, provider_type=self.provider_type)
        amount, currency = reported_amount(raw, provider_type=self.provider_type)
        return assess_usage(
            usage,
            json.loads(self.pricing_json),
            reported_cost=amount,
            reported_currency=currency,
            rate_source=self.rate_source,
            snapshot_revision=self.snapshot_revision,
            context_tier_basis=self.context_tier_basis,
        )

    def receipt(self, assessment: CostAssessment) -> dict:
        return {
            "cost_assessment": assessment.to_dict(),
            "rate_authority": json.loads(self.provenance_json),
        }


def unknown_call_rates(provider_id: str, model_id: str, provider_config: dict) -> CallRateSnapshot:
    """Missing rate authority does not invalidate a provider's monetary receipt."""
    return CallRateSnapshot(
        provider_type=provider_config.get("type", ""),
        pricing_json="null",
        provenance_json=json.dumps(
            {
                "provider_id": provider_id,
                "request_model_id": model_id,
                "pricing_authority": {"source": "unknown", "reason": "rate_capture_failed"},
            }
        ),
    )


async def capture_call_rates(
    db: AsyncSession,
    provider_id: str,
    model_id: str,
    provider_config: dict,
) -> CallRateSnapshot:
    """No HTTP and no writes. Pass the exact configuration used by execution.

    The resulting strings cannot change when catalog or overrides change while
    the provider request is in flight. Undeclared routing overrides invalidate
    estimates, not provider-reported monetary amounts.
    """
    offering = await get_offering(db, provider_id, model_id, provider_config=provider_config)
    resolved = json.loads(offering.resolved_json)
    authority = resolved.get("provenance", {}).get("pricing", {})
    source = {
        "models_dev": "models_dev",
        "provider": "provider_rate",
        "user_override": "user_rate",
    }.get(authority.get("source"), "models_dev")
    routing = provider_config.get("extra_params") or {}
    unsafe_routing = bool(_ROUTING_OVERRIDES.intersection(routing))
    pricing = None if unsafe_routing else resolved.get("pricing")
    provenance = {
        "provider_id": provider_id,
        "request_model_id": model_id,
        "config_fingerprint": offering.config_fingerprint,
        "offering_revision": offering.revision,
        "snapshot_revision": offering.snapshot_revision or None,
        "pricing_authority": authority,
        "routing_override_unresolved": unsafe_routing,
    }
    return CallRateSnapshot(
        provider_type=provider_config["type"],
        pricing_json=json.dumps(pricing),
        provenance_json=json.dumps(provenance),
        model_metadata_json=json.dumps(resolved),
        rate_source=source,
        snapshot_revision=offering.snapshot_revision or None,
    )
