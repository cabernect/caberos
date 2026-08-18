"""Tests for the heartbeat scheduler service."""

import pytest
import pytest_asyncio

from agentos.agent_service import save_agent
from agentos.config_schema import AgentConfig, HeartbeatConfig
from agentos.models.agent import Agent


@pytest_asyncio.fixture
async def test_agent(db):
    """Create a test agent with heartbeat enabled."""
    config = AgentConfig(
        id="hb-test",
        name="Heartbeat Test Agent",
        model={"provider_id": "test", "name": "test-model"},  # type: ignore[arg-type]
        soul="test soul",
        heartbeat=HeartbeatConfig(
            enabled=True,
            interval_minutes=1,
            task_prompt="Check status",
            max_cost_per_heartbeat=0.50,
            consecutive_failure_threshold=3,
        ),
    )
    agent = Agent(id="hb-test", name="Heartbeat Test Agent", enabled=True)
    db.add(agent)
    await db.commit()
    await save_agent(db, config)
    return agent


@pytest.mark.asyncio
async def test_heartbeat_config_fields():
    """HeartbeatConfig has all required fields with defaults."""
    hb = HeartbeatConfig()
    assert hb.enabled is False
    assert hb.interval_minutes == 60
    assert hb.task_prompt == ""
    assert hb.max_cost_per_heartbeat == 0.50
    assert hb.consecutive_failure_threshold == 3


@pytest.mark.asyncio
async def test_heartbeat_config_custom():
    """HeartbeatConfig accepts custom values."""
    hb = HeartbeatConfig(
        enabled=True,
        interval_minutes=30,
        task_prompt="Check inbox",
        max_cost_per_heartbeat=0.25,
        consecutive_failure_threshold=5,
    )
    assert hb.enabled is True
    assert hb.interval_minutes == 30
    assert hb.task_prompt == "Check inbox"
    assert hb.max_cost_per_heartbeat == 0.25
    assert hb.consecutive_failure_threshold == 5


@pytest.mark.asyncio
async def test_heartbeat_config_in_agent_config():
    """AgentConfig includes heartbeat config."""
    config = AgentConfig(
        id="test",
        name="Test",
        model={"provider_id": "p", "name": "m"},  # type: ignore[arg-type]
    )
    assert config.heartbeat.enabled is False
    assert config.heartbeat.interval_minutes == 60


@pytest.mark.asyncio
async def test_heartbeat_persisted_via_save_agent(db, test_agent):
    """Heartbeat config is persisted when saving an agent."""
    from agentos.agent_service import get_active_config

    config = await get_active_config(db, "hb-test")
    assert config is not None
    assert config.heartbeat.enabled is True
    assert config.heartbeat.interval_minutes == 1
    assert config.heartbeat.task_prompt == "Check status"
    assert config.heartbeat.max_cost_per_heartbeat == 0.50
    assert config.heartbeat.consecutive_failure_threshold == 3


@pytest.mark.asyncio
async def test_heartbeat_update_via_save_agent(db, test_agent):
    """Heartbeat config can be updated via save_agent."""
    from agentos.agent_service import get_active_config

    config = await get_active_config(db, "hb-test")
    config.heartbeat.enabled = False
    config.heartbeat.interval_minutes = 120
    await save_agent(db, config)

    # Re-read
    config2 = await get_active_config(db, "hb-test")
    assert config2.heartbeat.enabled is False
    assert config2.heartbeat.interval_minutes == 120


@pytest.mark.asyncio
async def test_scheduler_state_initialization():
    """Scheduler states dict starts empty."""
    from agentos import scheduler

    # Clear any existing state from previous tests
    scheduler._states.clear()
    assert len(scheduler._states) == 0
    assert len(scheduler._alerts) == 0


@pytest.mark.asyncio
async def test_scheduler_alert_creation():
    """SchedulerAlert can be created and stored."""
    from agentos.scheduler import SchedulerAlert, _alerts

    _alerts.clear()
    alert = SchedulerAlert(
        agent_id="test-agent",
        agent_name="Test Agent",
        consecutive_failures=3,
        threshold=3,
        last_error="Connection refused",
    )
    _alerts["test-agent"] = alert

    alerts = list(_alerts.values())
    assert len(alerts) == 1
    assert alerts[0].agent_id == "test-agent"
    assert alerts[0].consecutive_failures == 3
    assert alerts[0].last_error == "Connection refused"

    # Clear it
    scheduler_module = __import__("agentos.scheduler", fromlist=["clear_alert"])
    scheduler_module.clear_alert("test-agent")
    assert len(_alerts) == 0


@pytest.mark.asyncio
async def test_heartbeat_state_dataclass():
    """HeartbeatState dataclass has correct defaults."""
    from agentos.scheduler import HeartbeatState

    state = HeartbeatState(agent_id="test")
    assert state.agent_id == "test"
    assert state.task is None
    assert state.last_fired is None
    assert state.last_status is None
    assert state.last_error is None
    assert state.consecutive_failures == 0
    assert state.next_fire is None
