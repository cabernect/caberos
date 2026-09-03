"""Tests for progressive capability discovery."""

import pytest

from agentos.capabilities.registry import CapabilityDef, registry
from agentos.config_schema import AgentConfig, CapabilityGrant, ModelConfig


def _agent_config(*capability_names: str) -> AgentConfig:
    return AgentConfig(
        id="catalog-agent",
        name="Catalog Agent",
        model=ModelConfig(provider_id="test", name="scripted"),
        capabilities=[CapabilityGrant(name=name) for name in capability_names],
    )


@pytest.mark.asyncio
async def test_search_returns_only_bounded_metadata(monkeypatch):
    from agentos.capabilities.catalog import CapabilityRunCatalog

    capability_name = "mcp.demo.search_documents"
    registry.register(
        CapabilityDef(
            name=capability_name,
            kind="mcp_tool",
            description="Search documents in the connected archive",
            parameters_schema={
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
            egress=True,
            require_approval=True,
            subject_scoped=True,
        )
    )

    from agentos.mcp import registry as mcp_registry

    monkeypatch.setitem(mcp_registry._tool_map, capability_name, ("server-1", "search_documents"))
    catalog = CapabilityRunCatalog(_agent_config(capability_name), db=None, run_id="run-1")

    results = await catalog.search("documents")

    assert results == [
        {
            "name": capability_name,
            "kind": "mcp_tool",
            "description": "Search documents in the connected archive",
            "server_id": "server-1",
            "server_name": None,
            "egress": True,
            "require_approval": False,
            "always_loaded": False,
        }
    ]
    assert "parameters_schema" not in results[0]


@pytest.mark.asyncio
async def test_load_makes_an_exact_capability_visible(monkeypatch):
    from agentos.capabilities.catalog import CapabilityRunCatalog

    capability_name = "mcp.demo.create_document"
    registry.register(
        CapabilityDef(
            name=capability_name,
            kind="mcp_tool",
            description="Create a document in the connected archive",
            parameters_schema={"type": "object", "properties": {"title": {"type": "string"}}},
            egress=True,
            require_approval=True,
            subject_scoped=True,
        )
    )

    from agentos.mcp import registry as mcp_registry

    monkeypatch.setitem(mcp_registry._tool_map, capability_name, ("server-1", "create_document"))
    catalog = CapabilityRunCatalog(_agent_config(capability_name), db=None, run_id="run-1")

    result = await catalog.load([capability_name])

    assert result == {
        "accepted": [capability_name],
        "rejected": [],
        "loaded": [capability_name],
    }
    assert catalog.loaded == {capability_name}
    assert capability_name in catalog.model_capability_names()
    assert "parameters_schema" not in result
