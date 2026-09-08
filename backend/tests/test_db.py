"""Test database CRUD operations."""

import json

import pytest
from sqlalchemy import select
from sqlalchemy.exc import OperationalError

from agentos.db import is_database_locked, retry_locked_transaction
from agentos.main import handle_database_operational_error
from agentos.models.agent import Agent, AgentVersion
from agentos.models.capability import Capability
from agentos.models.contact import Contact
from agentos.models.operator import Operator
from agentos.models.run import Message, Run
from agentos.models.session import Session


def _locked_error() -> OperationalError:
    return OperationalError("UPDATE agents", {}, RuntimeError("database is locked"))


def test_is_database_locked_detects_wrapped_sqlite_error():
    assert is_database_locked(_locked_error()) is True
    assert (
        is_database_locked(OperationalError("UPDATE agents", {}, RuntimeError("syntax error")))
        is False
    )


@pytest.mark.asyncio
async def test_database_lock_handler_returns_retryable_error():
    response = await handle_database_operational_error(None, _locked_error())

    assert response.status_code == 503
    assert response.headers["retry-after"] == "1"
    assert response.headers["x-error-code"] == "database_busy"
    assert json.loads(response.body) == {
        "detail": {
            "code": "database_busy",
            "message": "The database is busy. Nothing was saved; please retry.",
        }
    }


@pytest.mark.asyncio
async def test_retry_locked_transaction_replays_operation_after_rollback(db, monkeypatch):
    monkeypatch.setattr("agentos.db.settings.db_lock_retries", 2)
    monkeypatch.setattr("agentos.db.settings.db_lock_retry_delay", 0)
    attempts = 0

    async def operation():
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise _locked_error()
        return "saved"

    assert await retry_locked_transaction(operation, db, "test_write") == "saved"
    assert attempts == 3


@pytest.mark.asyncio
async def test_retry_locked_transaction_raises_after_retry_budget(db, monkeypatch):
    monkeypatch.setattr("agentos.db.settings.db_lock_retries", 2)
    monkeypatch.setattr("agentos.db.settings.db_lock_retry_delay", 0)
    attempts = 0

    async def operation():
        nonlocal attempts
        attempts += 1
        raise _locked_error()

    with pytest.raises(OperationalError):
        await retry_locked_transaction(operation, db, "test_write")
    assert attempts == 3


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
        name="terminal",
        kind="tool",
        description="Execute a shell command",
        egress=True,
        require_approval=True,
    )
    db.add(cap)
    await db.commit()

    result = await db.execute(select(Capability).where(Capability.name == "terminal"))
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
