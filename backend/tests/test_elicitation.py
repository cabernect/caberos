"""Tests for the elicitation (clarifying question) HITL mechanism."""

import asyncio
import json

import pytest
from sqlalchemy import select
from sqlalchemy.exc import OperationalError

from agentos.api.approvals import ApproveRequest, approve
from agentos.config_schema import AgentConfig, CapabilityGrant, ModelConfig
from agentos.models.approval import ApprovalRequest
from agentos.models.elicitation import ElicitationRequest
from agentos.syscall.approval_registry import approval_registry
from agentos.syscall.elicitation_registry import elicitation_registry
from agentos.syscall.mediator import SyscallHandler
from agentos.syscall.protocol import ToolCall


@pytest.fixture
def workspace(tmp_path):
    return str(tmp_path / "ws")


@pytest.fixture
async def client(db):
    """HTTP client wired to the test DB with a stub operator."""
    from httpx import ASGITransport, AsyncClient

    from agentos.auth import require_operator
    from agentos.db import get_db
    from agentos.main import app
    from agentos.models.operator import Operator

    async def fake_operator():
        return Operator(id="test-operator", username="test", password_hash="x")

    app.dependency_overrides[require_operator] = fake_operator
    app.dependency_overrides[get_db] = lambda: db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as http:
        yield http
    app.dependency_overrides.clear()


@pytest.fixture
def agent_config():
    return AgentConfig(
        id="elicit-test",
        name="Elicitation Test",
        model=ModelConfig(provider_id="test", name="scripted"),
        soul="Test soul.",
        capabilities=[CapabilityGrant(name="agent_ask_user", require_approval=False)],
    )


class FakeSession:
    """Minimal session stub for the mediator."""

    id = "test-session-1"
    contact_id = "test-contact-1"


@pytest.mark.asyncio
async def test_elicitation_basic_flow(db, workspace, agent_config):
    """Agent calls agent.ask_user → mediator pauses → user responds → agent gets answer."""
    # Create minimal FK rows so the elicitation's run_id FK is valid

    from agentos.models.agent import Agent
    from agentos.models.contact import Contact
    from agentos.models.run import Run
    from agentos.models.session import Session

    agent_id = "elicit-test"
    session_id = "test-session-1"
    contact_id = "test-contact-1"
    run_id = "test-run-1"

    db.add(Agent(id=agent_id, name="Elicit Test"))
    db.add(
        Contact(
            id=contact_id, channel="dashboard_chat", bot_id=agent_id, external_user_id="test-user"
        )
    )
    db.add(Session(id=session_id, agent_id=agent_id, contact_id=contact_id))
    db.add(
        Run(
            id=run_id,
            session_id=session_id,
            contact_id=contact_id,
            agent_id=agent_id,
            status="running",
            trigger="user_message",
        )
    )
    await db.commit()

    handler = SyscallHandler(db=db, workspace_path=workspace)
    call = ToolCall(
        id="call_1",
        name="agent_ask_user",
        args={"question": "Which file?", "options": ["a.txt", "b.txt"]},
    )

    # Start the mediate call in the background — it will block on the event
    task = asyncio.create_task(
        handler.mediate(
            call=call,
            session=FakeSession(),
            agent_config=agent_config,
            run_id="test-run-1",
        )
    )
    # Give it a moment to create the ElicitationRequest and register the event
    # The mediator creates it in a separate session, so we need to poll a bit
    # and query from a fresh session to see the committed data.
    from agentos.db import async_session_factory

    elicitations = []
    for _ in range(10):
        await asyncio.sleep(0.1)
        async with async_session_factory() as fresh:
            result = await fresh.execute(select(ElicitationRequest))
            elicitations = result.scalars().all()
            if elicitations:
                break

    assert len(elicitations) == 1
    assert elicitations[0].status == "pending"
    assert elicitations[0].question == "Which file?"
    assert json.loads(elicitations[0].options) == [
        {"label": "a.txt", "description": ""},
        {"label": "b.txt", "description": ""},
    ]

    # Simulate the user responding via the API
    elicitation_id = elicitations[0].id
    resolved = elicitation_registry.resolve(elicitation_id, "a.txt", "operator-1")
    assert resolved

    # Wait for the mediate call to complete
    syscall_result = await asyncio.wait_for(task, timeout=5.0)

    # Verify the result
    assert syscall_result.allowed is True
    assert syscall_result.output == {"response": "a.txt"}

    # Verify the ElicitationRequest was updated (query from a fresh session
    # since the mediator updates it in a separate session)
    async with async_session_factory() as fresh:
        result = await fresh.execute(
            select(ElicitationRequest).where(ElicitationRequest.id == elicitation_id)
        )
        updated = result.scalar_one()
        assert updated.status == "answered"
        assert updated.response == "a.txt"
        assert updated.responded_by == "operator-1"


@pytest.mark.asyncio
async def test_elicitation_free_text(db, workspace, agent_config):
    """Elicitation without options → user provides free-text response."""
    # Create minimal FK rows
    from agentos.models.contact import Contact
    from agentos.models.run import Run
    from agentos.models.session import Session

    agent_id = "elicit-test"
    session_id = "test-session-2"
    contact_id = "test-contact-2"
    run_id = "test-run-2"

    db.add(
        Contact(
            id=contact_id, channel="dashboard_chat", bot_id=agent_id, external_user_id="test-user-2"
        )
    )
    db.add(Session(id=session_id, agent_id=agent_id, contact_id=contact_id))
    db.add(
        Run(
            id=run_id,
            session_id=session_id,
            contact_id=contact_id,
            agent_id=agent_id,
            status="running",
            trigger="user_message",
        )
    )
    await db.commit()

    handler = SyscallHandler(db=db, workspace_path=workspace)
    call = ToolCall(
        id="call_2",
        name="agent_ask_user",
        args={"question": "What should I name the file?"},
    )

    task = asyncio.create_task(
        handler.mediate(
            call=call,
            session=FakeSession(),
            agent_config=agent_config,
            run_id=run_id,
        )
    )

    # Poll for the ElicitationRequest from a fresh session
    from agentos.db import async_session_factory

    elicitations = []
    for _ in range(10):
        await asyncio.sleep(0.1)
        async with async_session_factory() as fresh:
            result = await fresh.execute(select(ElicitationRequest))
            elicitations = result.scalars().all()
            if elicitations:
                break

    assert len(elicitations) == 1
    assert elicitations[0].options is None

    # User responds with free text
    elicitation_registry.resolve(elicitations[0].id, "my_report.txt", "operator-1")

    syscall_result = await asyncio.wait_for(task, timeout=5.0)
    assert syscall_result.output == {"response": "my_report.txt"}


@pytest.mark.asyncio
async def test_elicitation_not_granted(db, workspace):
    """If agent.ask_user is not in the agent's capabilities, it's denied."""
    from agentos.config_schema import AgentConfig, ModelConfig

    config = AgentConfig(
        id="no-elicit",
        name="No Elicit",
        model=ModelConfig(provider_id="test", name="scripted"),
        soul="Test.",
        capabilities=[],  # no agent.ask_user
    )
    handler = SyscallHandler(db=db, workspace_path=workspace)
    call = ToolCall(
        id="call_3",
        name="agent_ask_user",
        args={"question": "Hello?"},
    )

    result = await handler.mediate(
        call=call,
        session=FakeSession(),
        agent_config=config,
        run_id="test-run-3",
    )

    assert result.allowed is False
    assert "not granted" in (result.denied_reason or "")


@pytest.mark.asyncio
async def test_elicitation_emits_events(db, workspace, agent_config):
    """The mediator emits clarifying_question and tool_call events."""
    handler = SyscallHandler(db=db, workspace_path=workspace)
    call = ToolCall(
        id="call_4",
        name="agent_ask_user",
        args={"question": "Pick one", "options": ["x", "y"]},
    )

    events = []

    async def event_emitter(event_type, payload):
        events.append((event_type, payload))

    task = asyncio.create_task(
        handler.mediate(
            call=call,
            session=FakeSession(),
            agent_config=agent_config,
            run_id="test-run-4",
            event_emitter=event_emitter,
        )
    )
    await asyncio.sleep(0.2)

    # Should have emitted clarifying_question and tool_call (pending_input)
    event_types = [e[0] for e in events]
    assert "clarifying_question" in event_types
    assert "tool_call" in event_types

    # Find the clarifying_question event
    cq = next(p for t, p in events if t == "clarifying_question")
    assert cq["question"] == "Pick one"
    assert cq["options"] == [
        {"label": "x", "description": ""},
        {"label": "y", "description": ""},
    ]
    assert cq["tool_call_id"] == "call_4"

    # Find the pending_input tool_call event
    tc_pending = next(p for t, p in events if t == "tool_call" and p["status"] == "pending_input")
    assert tc_pending["elicitation_id"] is not None

    # Resolve
    elicitation_registry.resolve(cq["id"], "x", "operator-1")
    await asyncio.wait_for(task, timeout=5.0)

    # Should have emitted a complete tool_call event
    tc_complete = next(p for t, p in events if t == "tool_call" and p["status"] == "complete")
    assert tc_complete["result"] == {"response": "x"}


@pytest.mark.asyncio
async def test_elicitation_writes_audit_record(db, workspace, agent_config):
    """An audit record is written for the elicitation call."""
    handler = SyscallHandler(db=db, workspace_path=workspace)
    call = ToolCall(
        id="call_5",
        name="agent_ask_user",
        args={"question": "Test?"},
    )

    task = asyncio.create_task(
        handler.mediate(
            call=call,
            session=FakeSession(),
            agent_config=agent_config,
            run_id="test-run-5",
        )
    )
    await asyncio.sleep(0.1)

    result = await db.execute(select(ElicitationRequest))
    elicitation_registry.resolve(result.scalars().first().id, "yes", "op-1")
    await asyncio.wait_for(task, timeout=5.0)

    from agentos.models.audit import AuditRecord

    result = await db.execute(select(AuditRecord).where(AuditRecord.run_id == "test-run-5"))
    audits = result.scalars().all()
    assert len(audits) == 1
    assert audits[0].capability_name == "agent_ask_user"
    assert audits[0].allowed is True
    assert json.loads(audits[0].result) == {"response": "yes"}


@pytest.mark.asyncio
async def test_approval_persists_before_unblocking_mediator(db, monkeypatch):
    """Operator approval commits before waking a waiting run on SQLite."""
    from types import SimpleNamespace

    from agentos.models.agent import Agent
    from agentos.models.contact import Contact
    from agentos.models.run import Run
    from agentos.models.session import Session

    agent_id = "approval-test-agent"
    contact_id = "approval-test-contact"
    session_id = "approval-test-session"
    run_id = "approval-test-run"
    approval_id = "approval-test-request"

    db.add(Agent(id=agent_id, name="Approval Test"))
    db.add(
        Contact(
            id=contact_id,
            channel="dashboard_chat",
            bot_id=agent_id,
            external_user_id="approval-user",
        )
    )
    db.add(Session(id=session_id, agent_id=agent_id, contact_id=contact_id))
    db.add(
        Run(
            id=run_id,
            session_id=session_id,
            contact_id=contact_id,
            agent_id=agent_id,
            status="running",
            trigger="user_message",
        )
    )
    db.add(
        ApprovalRequest(
            id=approval_id,
            run_id=run_id,
            capability_name="terminal",
            args='{"command":"echo attached"}',
            status="pending",
        )
    )
    await db.commit()
    monkeypatch.setattr("agentos.db.settings.db_lock_retry_delay", 0)
    original_commit = db.commit
    attempts = 0

    async def flaky_commit():
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise OperationalError(
                "UPDATE approval_requests", {}, RuntimeError("database is locked")
            )
        await original_commit()

    monkeypatch.setattr(db, "commit", flaky_commit)
    pending = approval_registry.register(approval_id)
    try:
        result = await approve(
            approval_id,
            ApproveRequest(),
            operator=SimpleNamespace(id="approval-operator"),
            db=db,
        )

        assert result == {"status": "approved"}
        assert attempts == 2
        assert pending.decision == "approved"
        refreshed = await db.get(ApprovalRequest, approval_id)
        assert refreshed is not None
        assert refreshed.status == "approved"
        assert refreshed.decided_by == "approval-operator"
    finally:
        approval_registry.cleanup(approval_id)


async def _seed_pending_elicitation(db, *, options: list | None) -> str:
    """Seed the FK chain plus a pending ElicitationRequest row directly.

    Returns the elicitation id. `options` is stored as JSON verbatim —
    object-form matches what the mediator persists; string-form covers
    rows written outside the normalization path.
    """
    from agentos.models.agent import Agent
    from agentos.models.contact import Contact
    from agentos.models.run import Run
    from agentos.models.session import Session

    elicitation_id = "elicit-api-row"

    db.add(Agent(id="elicit-api-agent", name="Elicit API"))
    db.add(
        Contact(
            id="elicit-api-contact",
            channel="dashboard_chat",
            bot_id="elicit-api-agent",
            external_user_id="elicit-api-user",
        )
    )
    db.add(
        Session(
            id="elicit-api-session",
            agent_id="elicit-api-agent",
            contact_id="elicit-api-contact",
        )
    )
    db.add(
        Run(
            id="elicit-api-run",
            session_id="elicit-api-session",
            contact_id="elicit-api-contact",
            agent_id="elicit-api-agent",
            status="running",
            trigger="user_message",
        )
    )
    db.add(
        ElicitationRequest(
            id=elicitation_id,
            run_id="elicit-api-run",
            question="Pick one",
            options=json.dumps(options) if options else None,
            status="pending",
        )
    )
    await db.commit()
    return elicitation_id


@pytest.mark.asyncio
async def test_list_pending_elicitation_preserves_structured_options(client, db):
    """B17 regression — the mediator stores options as {label, description}
    objects; GET /api/elicitation must serialize them, not 500."""
    elicitation_id = await _seed_pending_elicitation(
        db,
        options=[
            {"label": "Retry", "description": "Try the call again"},
            {"label": "Skip", "description": "Continue without it"},
        ],
    )

    resp = await client.get("/api/elicitation")
    assert resp.status_code == 200
    rows = resp.json()
    assert len(rows) == 1
    assert rows[0]["id"] == elicitation_id
    assert rows[0]["options"] == [
        {"label": "Retry", "description": "Try the call again"},
        {"label": "Skip", "description": "Continue without it"},
    ]


@pytest.mark.asyncio
async def test_list_pending_elicitation_plain_string_options(client, db):
    """B17 — rows storing raw string options still serialize as strings."""
    await _seed_pending_elicitation(db, options=["a.txt", "b.txt"])

    resp = await client.get("/api/elicitation")
    assert resp.status_code == 200
    rows = resp.json()
    assert len(rows) == 1
    assert rows[0]["options"] == ["a.txt", "b.txt"]
