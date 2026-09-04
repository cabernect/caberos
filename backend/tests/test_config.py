"""Test agent config validation and versioning."""

import pytest
import yaml

from agentos.agent_service import (
    create_agent,
    export_agent,
    get_active_config,
    import_agent,
    list_versions,
    rollback_to,
    save_agent,
)
from agentos.config_schema import AgentConfig, CapabilityGrant, ModelConfig


def test_config_validation():
    """AgentConfig validates correctly."""
    config = AgentConfig(
        id="test-agent",
        name="Test",
        model=ModelConfig(provider_id="openai", name="gpt-4o"),
        soul="I am a test agent.",
        persona="Direct.",
        task="Help test the system.",
        capabilities=[CapabilityGrant(name="terminal")],
    )
    assert config.id == "test-agent"
    assert config.limits.max_turns_per_run == 15
    assert config.heartbeat.enabled is False


def test_config_invalid_capability_subject():
    """CapabilityGrant validates subject field."""
    grant = CapabilityGrant(name="email.read", subject="self")
    assert grant.subject == "self"

    grant2 = CapabilityGrant(name="terminal", subject="none")
    assert grant2.subject == "none"


def test_capability_grant_preserves_schema_loading_mode():
    """Capability grants distinguish permitted-on-demand from always-loaded schemas."""
    on_demand = CapabilityGrant(name="mcp.notion.search", always_loaded=False)
    always_loaded = CapabilityGrant(name="mcp.notion.create", always_loaded=True)

    assert on_demand.always_loaded is False
    assert always_loaded.always_loaded is True
    assert on_demand.model_dump()["always_loaded"] is False


@pytest.mark.asyncio
async def test_create_and_get_agent(db):
    """Create an agent and retrieve its config."""
    config = AgentConfig(
        id="cfg-test-1",
        name="Config Test",
        model=ModelConfig(provider_id="test", name="scripted"),
        soul="Test soul.",
        capabilities=[CapabilityGrant(name="terminal", require_approval=False)],
    )
    await create_agent(db, config)

    retrieved = await get_active_config(db, "cfg-test-1")
    assert retrieved is not None
    assert retrieved.name == "Config Test"
    assert retrieved.soul == "Test soul."
    assert len(retrieved.capabilities) == 1
    assert retrieved.capabilities[0].name == "terminal"


@pytest.mark.asyncio
async def test_versioning(db):
    """Save creates a new version and advances the active pointer."""
    config = AgentConfig(
        id="cfg-test-2",
        name="V1",
        model=ModelConfig(provider_id="test", name="scripted"),
        soul="Version 1 soul.",
    )
    await create_agent(db, config)

    versions = await list_versions(db, "cfg-test-2")
    assert len(versions) == 1
    assert versions[0].version_number == 1

    # Save a new version
    config.name = "V2"
    config.soul = "Version 2 soul."
    await save_agent(db, config)

    versions = await list_versions(db, "cfg-test-2")
    assert len(versions) == 2
    assert versions[0].is_active is False  # v1 deactivated
    assert versions[1].is_active is True  # v2 active

    # Active config should be v2
    active = await get_active_config(db, "cfg-test-2")
    assert active is not None
    assert active.soul == "Version 2 soul."


@pytest.mark.asyncio
async def test_rollback(db):
    """Rollback creates a new version copying the old config."""
    config = AgentConfig(
        id="cfg-test-3",
        name="Original",
        model=ModelConfig(provider_id="test", name="scripted"),
        soul="Original soul.",
    )
    await create_agent(db, config)

    # Save a new version
    config.soul = "Changed soul."
    await save_agent(db, config)

    # Rollback to v1
    versions = await list_versions(db, "cfg-test-3")
    v1_id = versions[0].id
    await rollback_to(db, "cfg-test-3", v1_id)

    # Should now have 3 versions, active = v3 (copy of v1)
    versions = await list_versions(db, "cfg-test-3")
    assert len(versions) == 3
    active = await get_active_config(db, "cfg-test-3")
    assert active is not None
    assert active.soul == "Original soul."


@pytest.mark.asyncio
async def test_yaml_export_import(db):
    """Export to YAML and import back — round-trip safe."""
    config = AgentConfig(
        id="cfg-test-4",
        name="YAML Test",
        model=ModelConfig(provider_id="test", name="scripted"),
        soul="YAML soul.",
        capabilities=[CapabilityGrant(name="terminal")],
    )
    await create_agent(db, config)

    # Export
    yaml_str = await export_agent(db, "cfg-test-4")
    assert "cfg-test-4" in yaml_str
    assert "YAML soul." in yaml_str

    # Import as a new agent
    yaml_data = yaml.safe_load(yaml_str)
    yaml_data["id"] = "cfg-test-5"
    yaml_data["name"] = "Imported Agent"
    new_yaml = yaml.dump(yaml_data)
    await import_agent(db, new_yaml)

    imported = await get_active_config(db, "cfg-test-5")
    assert imported is not None
    assert imported.name == "Imported Agent"
    assert imported.soul == "YAML soul."


def test_capabilities_none_means_all():
    """capabilities=None means all tools (default when omitted from YAML)."""
    config = AgentConfig(
        id="test",
        name="Test",
        model=ModelConfig(provider_id="test", name="test"),
        capabilities=None,
    )
    assert config.capabilities is None


def test_capabilities_empty_means_none():
    """capabilities=[] means no tools."""
    config = AgentConfig(
        id="test",
        name="Test",
        model=ModelConfig(provider_id="test", name="test"),
        capabilities=[],
    )
    assert config.capabilities == []


def test_capabilities_from_yaml_omitted():
    """YAML without capabilities field should produce None."""
    yaml_str = """
id: yaml-test
name: YAML Test
soul: test
model:
  provider_id: ""
  name: ""
"""
    data = yaml.safe_load(yaml_str)
    config = AgentConfig.from_dict(data)
    assert config.capabilities is None


def test_capabilities_from_yaml_empty():
    """YAML with capabilities: [] should produce empty list."""
    yaml_str = """
id: yaml-test
name: YAML Test
soul: test
model:
  provider_id: ""
  name: ""
capabilities: []
"""
    data = yaml.safe_load(yaml_str)
    config = AgentConfig.from_dict(data)
    assert config.capabilities == []


def test_capabilities_from_yaml_explicit():
    """YAML with explicit capabilities should produce the list."""
    yaml_str = """
id: yaml-test
name: YAML Test
soul: test
model:
  provider_id: ""
  name: ""
capabilities:
  - name: read_file
  - name: terminal
    require_approval: true
"""
    data = yaml.safe_load(yaml_str)
    config = AgentConfig.from_dict(data)
    assert config.capabilities is not None
    assert len(config.capabilities) == 2
    assert config.capabilities[0].name == "read_file"
    assert config.capabilities[1].name == "terminal"
    assert config.capabilities[1].require_approval is True
