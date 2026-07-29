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
        capabilities=[CapabilityGrant(name="shell.run")],
    )
    assert config.id == "test-agent"
    assert config.limits.max_turns_per_run == 12
    assert config.heartbeat.enabled is False


def test_config_invalid_capability_subject():
    """CapabilityGrant validates subject field."""
    grant = CapabilityGrant(name="email.read", subject="self")
    assert grant.subject == "self"

    grant2 = CapabilityGrant(name="shell.run", subject="none")
    assert grant2.subject == "none"


@pytest.mark.asyncio
async def test_create_and_get_agent(db):
    """Create an agent and retrieve its config."""
    config = AgentConfig(
        id="cfg-test-1",
        name="Config Test",
        model=ModelConfig(provider_id="test", name="scripted"),
        soul="Test soul.",
        capabilities=[CapabilityGrant(name="shell.run", require_approval=False)],
    )
    await create_agent(db, config)

    retrieved = await get_active_config(db, "cfg-test-1")
    assert retrieved is not None
    assert retrieved.name == "Config Test"
    assert retrieved.soul == "Test soul."
    assert len(retrieved.capabilities) == 1
    assert retrieved.capabilities[0].name == "shell.run"


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
        capabilities=[CapabilityGrant(name="shell.run")],
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
