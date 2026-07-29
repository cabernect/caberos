"""Test database CRUD operations."""

import pytest
from sqlalchemy import select

from agentos.models.agent import Agent, AgentVersion
from agentos.models.capability import Capability
from agentos.models.contact import Contact
from agentos.models.operator import Operator
from agentos.models.run import Message, Run
from agentos.models.session import Session


@pytest.mark.asyncio
async def test_create_agent(db):
    """Create an agent and verify it's in the DB."""
    agent = Agent(id="test-1", name="Test Agent", enabled=True)
    db.add(agent)
    await db.commit()

    result = await db.execute(select(Agent).where(Agent.id == "test-1"))
    found = result.scalar_one()
    assert found.name == "Test Agent"
    assert found.enabled is True


@pytest.mark.asyncio
async def test_agent_versioning(db):
    """Create an agent with a version."""
    agent = Agent(id="test-2", name="Versioned Agent", enabled=True)
    db.add(agent)
    await db.flush()

    v1 = AgentVersion(
        agent_id="test-2",
        version_number=1,
        config='{"id": "test-2", "name": "Versioned Agent"}',
        is_active=True,
    )
    db.add(v1)
    await db.flush()
    agent.active_version_id = v1.id
    await db.commit()

    result = await db.execute(select(AgentVersion).where(AgentVersion.agent_id == "test-2"))
    versions = result.scalars().all()
    assert len(versions) == 1
    assert versions[0].version_number == 1
    assert versions[0].is_active is True


@pytest.mark.asyncio
async def test_create_capability(db):
    """Create a capability."""
    cap = Capability(
        id="cap-1",
        name="shell.run",
        kind="tool",
        description="Execute a shell command",
        egress=True,
        require_approval=True,
    )
    db.add(cap)
    await db.commit()

    result = await db.execute(select(Capability).where(Capability.name == "shell.run"))
    found = result.scalar_one()
    assert found.kind == "tool"
    assert found.egress is True


@pytest.mark.asyncio
async def test_create_contact_and_session(db):
    """Create a contact and session."""
    contact = Contact(
        id="c-1",
        channel="dashboard_chat",
        bot_id="agent-1",
        external_user_id="user-1",
        display_name="Test User",
    )
    db.add(contact)
    await db.flush()

    session = Session(
        id="s-1",
        contact_id=contact.id,
        agent_id="agent-1",
        status="active",
    )
    db.add(session)
    await db.commit()

    result = await db.execute(select(Session).where(Session.id == "s-1"))
    found = result.scalar_one()
    assert found.contact_id == "c-1"
    assert found.status == "active"


@pytest.mark.asyncio
async def test_create_run_and_message(db):
    """Create a run with messages."""
    # Need a contact and session first
    contact = Contact(id="c-2", channel="dashboard_chat", bot_id="a-1", external_user_id="u-1")
    db.add(contact)
    await db.flush()

    session = Session(id="s-2", contact_id="c-2", agent_id="a-1", status="active")
    db.add(session)
    await db.flush()

    run = Run(
        id="r-1",
        session_id="s-2",
        contact_id="c-2",
        agent_id="a-1",
        status="completed",
        trigger="user_message",
        tokens_in=100,
        tokens_out=50,
        cost=0.001,
    )
    db.add(run)
    await db.flush()

    msg1 = Message(id="m-1", run_id="r-1", role="user", content="Hello")
    msg2 = Message(id="m-2", run_id="r-1", role="assistant", content="Hi there!")
    db.add(msg1)
    db.add(msg2)
    await db.commit()

    result = await db.execute(
        select(Message).where(Message.run_id == "r-1").order_by(Message.created_at)
    )
    msgs = result.scalars().all()
    assert len(msgs) == 2
    assert msgs[0].role == "user"
    assert msgs[1].role == "assistant"


@pytest.mark.asyncio
async def test_create_operator(db):
    """Create an operator."""
    op = Operator(id="op-1", username="admin", password_hash="fakehash", must_change_password=True)
    db.add(op)
    await db.commit()

    result = await db.execute(select(Operator).where(Operator.username == "admin"))
    found = result.scalar_one()
    assert found.must_change_password is True
