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


@pytest.mark.asyncio
async def test_discovery_capabilities_delegate_to_the_run_catalog():
    from agentos.capabilities.catalog import CapabilityRunCatalog
    from agentos.capabilities.registry import registry

    catalog = CapabilityRunCatalog(_agent_config("read_file"), db=None, run_id="run-1")
    search = registry.get("capabilities_search")
    load = registry.get("capabilities_load")

    assert search is not None
    assert load is not None

    results = await search.execute(
        args={"query": "read file"},
        capability_catalog=catalog,
    )
    assert results["count"] == 1
    assert results["results"][0]["name"] == "read_file"

    loaded = await load.execute(
        args={"names": ["read_file"]},
        capability_catalog=catalog,
    )
    assert loaded["accepted"] == ["read_file"]


@pytest.mark.asyncio
async def test_harness_loads_schemas_for_the_next_model_turn(db, workspace):
    from agentos.harness.loop import Harness
    from agentos.harness.scripted_model import ScriptedResponse
    from agentos.syscall.mediator import StubSyscallHandler

    class CapturingModel:
        def __init__(self):
            self.tool_names: list[list[str]] = []
            self.responses = [
                ScriptedResponse(
                    tool_calls=[
                        {
                            "id": "load-1",
                            "name": "capabilities_load",
                            "args": {"names": ["read_file"]},
                        }
                    ]
                ),
                ScriptedResponse(content="Loaded the file capability."),
            ]

        async def complete(self, *, tools, **_kwargs):
            self.tool_names.append([tool["function"]["name"] for tool in tools or []])
            return self.responses.pop(0)

    config = AgentConfig(
        id="catalog-harness-agent",
        name="Catalog Harness Agent",
        model=ModelConfig(provider_id="test", name="scripted"),
        capabilities=[CapabilityGrant(name="read_file", always_loaded=False)],
    )
    model = CapturingModel()
    events: list[tuple[str, dict]] = []

    async def emit(event_type: str, payload: dict) -> None:
        events.append((event_type, payload))

    result = await Harness(model=model).run(
        agent_config=config,
        session=None,
        message="Load the file capability",
        syscall_handler=StubSyscallHandler(db=db, workspace_path=workspace),
        run_id="catalog-harness-run",
        event_emitter=emit,
    )

    assert result.final_answer == "Loaded the file capability."
    assert "read_file" not in model.tool_names[0]
    assert set(model.tool_names[0]) == {"capabilities_search", "capabilities_load"}
    assert "read_file" in model.tool_names[1]
    turn_events = [payload for event, payload in events if event == "turn_complete"]
    assert turn_events[0]["loaded_capabilities"] == ["read_file"]
    assert (
        turn_events[1]["context_breakdown"]["tools"] > turn_events[0]["context_breakdown"]["tools"]
    )
    assert result.loaded_capabilities == ["read_file"]


@pytest.mark.asyncio
async def test_server_grant_searches_mcp_tools_from_the_database(db):
    import json

    from agentos.capabilities.catalog import CapabilityRunCatalog, mcp_server_grant_name
    from agentos.models.mcp import McpServer, McpTool

    server = McpServer(name="Demo Archive", transport="stdio", command="demo", enabled=True)
    db.add(server)
    await db.flush()
    tool = McpTool(
        mcp_server_id=server.id,
        tool_name="search_documents",
        capability_name="mcp.demo_archive.search_documents",
        description="Search documents in the archive",
        parameters_schema='{"type":"object","properties":{"query":{"type":"string"}}}',
        egress=True,
        require_approval=True,
        subject_scoped=True,
    )
    db.add(tool)
    await db.flush()

    config = AgentConfig(
        id="server-grant-agent",
        name="Server Grant Agent",
        model=ModelConfig(provider_id="test", name="scripted"),
        capabilities=[CapabilityGrant(name=mcp_server_grant_name(server.id))],
    )
    catalog = CapabilityRunCatalog(config, db=db, run_id="run-1")

    results = await catalog.search("documents", kind="mcp_tool")

    assert results == [
        {
            "name": tool.capability_name,
            "kind": "mcp_tool",
            "description": "Search documents in the archive",
            "server_id": server.id,
            "server_name": "Demo Archive",
            "egress": True,
            "require_approval": False,
            "always_loaded": False,
        }
    ]

    loaded = await catalog.load([tool.capability_name])
    assert loaded["accepted"] == [tool.capability_name]
    assert tool.capability_name in catalog.model_capability_names()

    server.tool_filter = json.dumps(["other_tool"])
    await db.commit()
    filtered_catalog = CapabilityRunCatalog(config, db=db, run_id="run-2")
    assert await filtered_catalog.search("documents", kind="mcp_tool") == []


@pytest.mark.asyncio
async def test_server_grant_allows_mcp_execution(db, workspace, monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from agentos.capabilities.catalog import mcp_server_grant_name
    from agentos.capabilities.registry import CapabilityDef, registry
    from agentos.mcp import registry as mcp_registry
    from agentos.models.mcp import McpServer
    from agentos.syscall.mediator import SyscallHandler
    from agentos.syscall.protocol import ToolCall

    server = McpServer(name="Execution Archive", transport="stdio", command="demo", enabled=True)
    db.add(server)
    await db.flush()
    capability_name = "mcp.execution_archive.search"
    registry.register(
        CapabilityDef(
            name=capability_name,
            kind="mcp_tool",
            description="Search the execution archive",
            parameters_schema={"type": "object", "properties": {}},
            egress=True,
            subject_scoped=False,
            execute=None,
        )
    )
    monkeypatch.setitem(mcp_registry._tool_map, capability_name, (server.id, "search"))
    execute = AsyncMock(
        return_value={"content": [{"type": "text", "text": "found"}], "isError": False}
    )
    monkeypatch.setattr(mcp_registry, "execute_mcp_tool", execute)

    config = AgentConfig(
        id="server-execution-agent",
        name="Server Execution Agent",
        model=ModelConfig(provider_id="test", name="scripted"),
        capabilities=[CapabilityGrant(name=mcp_server_grant_name(server.id))],
    )
    handler = SyscallHandler(db=db, workspace_path=workspace)
    result = await handler.mediate(
        call=ToolCall(id="call-1", name=capability_name, args={}),
        session=SimpleNamespace(id="session-1", contact_id="contact-1", channel=None),
        agent_config=config,
        run_id="run-1",
    )

    assert result.allowed is True
    execute.assert_awaited_once_with(capability_name, {}, env={}, headers={})


@pytest.mark.asyncio
async def test_explicit_mcp_grants_are_on_demand_unless_marked_always_loaded(monkeypatch):
    from agentos.capabilities.catalog import CapabilityRunCatalog
    from agentos.capabilities.registry import CapabilityDef, registry
    from agentos.mcp import registry as mcp_registry

    capability_name = "mcp.demo_archive.search"
    registry.register(
        CapabilityDef(
            name=capability_name,
            kind="mcp_tool",
            description="Search the archive",
            parameters_schema={"type": "object", "properties": {}},
        )
    )
    monkeypatch.setitem(mcp_registry._tool_map, capability_name, ("server-1", "search"))

    on_demand = CapabilityRunCatalog(_agent_config(capability_name), db=None)
    assert capability_name not in on_demand.model_capability_names()
    assert "capabilities_search" in on_demand.model_capability_names()

    always_loaded = CapabilityRunCatalog(
        AgentConfig(
            id="always-agent",
            name="Always Agent",
            model=ModelConfig(provider_id="test", name="scripted"),
            capabilities=[CapabilityGrant(name=capability_name, always_loaded=True)],
        ),
        db=None,
    )
    assert capability_name in always_loaded.model_capability_names()


@pytest.mark.asyncio
async def test_subagent_catalog_is_limited_by_parent_ceiling(monkeypatch):
    from agentos.capabilities.catalog import CapabilityRunCatalog
    from agentos.capabilities.registry import CapabilityDef, registry
    from agentos.mcp import registry as mcp_registry

    allowed_name = "mcp.parent.allowed"
    blocked_name = "mcp.parent.blocked"
    for name in (allowed_name, blocked_name):
        registry.register(
            CapabilityDef(
                name=name,
                kind="mcp_tool",
                description=name.rsplit(".", 1)[-1],
                parameters_schema={"type": "object", "properties": {}},
            )
        )
        monkeypatch.setitem(mcp_registry._tool_map, name, ("server-1", name.rsplit(".", 1)[-1]))

    parent = _agent_config(allowed_name)
    child = _agent_config(allowed_name, blocked_name)
    catalog = CapabilityRunCatalog(child, db=None, parent_config=parent)

    results = await catalog.search()
    assert [result["name"] for result in results] == [allowed_name]
    rejected = await catalog.load([blocked_name])
    assert rejected["accepted"] == []
    assert rejected["rejected"] == [{"name": blocked_name, "reason": "Capability is not permitted"}]


@pytest.mark.asyncio
async def test_mcp_discovery_does_not_modify_agent_grants(db, monkeypatch):
    from sqlalchemy import select

    from agentos.agent_service import create_agent, get_active_config
    from agentos.mcp import registry as mcp_registry
    from agentos.mcp.client import MockMcpClient
    from agentos.models.mcp import McpServer, McpTool

    config = AgentConfig(
        id="discovery-agent",
        name="Discovery Agent",
        model=ModelConfig(provider_id="test", name="scripted"),
        capabilities=[CapabilityGrant(name="read_file")],
    )
    await create_agent(db, config)
    server = McpServer(name="Demo", transport="stdio", command="demo", enabled=True)
    db.add(server)
    await db.flush()

    class TestSessionFactory:
        def __call__(self):
            class TestSession:
                async def __aenter__(self):
                    return db

                async def __aexit__(self, *args):
                    pass

            return TestSession()

    monkeypatch.setattr(mcp_registry, "async_session_factory", TestSessionFactory())
    client = MockMcpClient(
        tools=[
            {
                "name": "search",
                "description": "Search",
                "inputSchema": {"type": "object", "properties": {}},
            }
        ]
    )
    await client.connect()
    await mcp_registry._discover_tools(server, client)

    updated = await get_active_config(db, config.id)
    assert updated is not None
    assert [grant.name for grant in updated.capabilities] == ["read_file"]
    result = await db.execute(select(McpTool).where(McpTool.mcp_server_id == server.id))
    assert result.scalar_one().capability_name == "mcp.demo.search"


@pytest.mark.asyncio
async def test_capability_listing_exposes_mcp_server_identity(db):
    from agentos.api.agents import list_capabilities
    from agentos.capabilities.registry import CapabilityDef, registry
    from agentos.models.mcp import McpServer, McpTool

    server = McpServer(name="Listing Archive", transport="stdio", command="demo", enabled=True)
    db.add(server)
    await db.flush()
    tool = McpTool(
        mcp_server_id=server.id,
        tool_name="search",
        capability_name="mcp.listing_archive.search",
        description="Search the listing archive",
        parameters_schema='{"type":"object","properties":{}}',
    )
    db.add(tool)
    registry.register(
        CapabilityDef(
            name=tool.capability_name,
            kind="mcp_tool",
            description=tool.description,
            parameters_schema={"type": "object", "properties": {}},
        )
    )
    await db.commit()

    capabilities = await list_capabilities(None, db)

    listed = next(
        capability for capability in capabilities if capability["name"] == tool.capability_name
    )
    assert listed["server_id"] == server.id
    assert listed["server_name"] == server.name
    assert listed["kind"] == "mcp_tool"
