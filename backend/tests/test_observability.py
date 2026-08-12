"""Tests for observability API (Ticket 09).

Covers:
- GET /api/runs — list with filters
- GET /api/runs/{run_id} — run detail with messages + audit
- GET /api/audit — syscall log with filters
- GET /api/spend — spend summary with breakdowns
- GET /api/operator-audit — operator audit log
- GET /api/health — system health
"""

import uuid

import pytest
from fastapi.testclient import TestClient

from agentos.models.agent import Agent
from agentos.models.audit import AuditRecord
from agentos.models.contact import Contact
from agentos.models.operator import Operator, OperatorAuditLog
from agentos.models.run import Message, Run
from agentos.models.session import Session


def _make_run(
    db_session_factory,
    agent_id="agent-1",
    status="completed",
    trigger="user_message",
    cost=0.01,
    tokens_in=100,
    tokens_out=50,
    is_test=False,
    error=None,
):
    """Helper to insert a Run + Session + Contact + Agent."""
    import asyncio

    async def _insert():
        async with db_session_factory() as db:
            # Agent
            ag = Agent(id=agent_id, name=f"Agent {agent_id[-1]}")
            db.add(ag)
            # Contact
            contact = Contact(
                id=f"contact-{agent_id}",
                bot_id=agent_id,
                external_user_id="ext-1",
                channel="dashboard",
            )
            db.add(contact)
            # Session
            sess = Session(id=f"session-{agent_id}", agent_id=agent_id, contact_id=contact.id)
            db.add(sess)
            # Run
            run = Run(
                id=str(uuid.uuid4()),
                session_id=sess.id,
                contact_id=contact.id,
                agent_id=agent_id,
                status=status,
                trigger=trigger,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                cost=cost,
                latency_ms=500,
                is_test=is_test,
                error=error,
            )
            db.add(run)
            # Messages
            db.add(Message(
                id=str(uuid.uuid4()), run_id=run.id,
                role="user", content="Hello", seq=0,
            ))
            db.add(Message(
                id=str(uuid.uuid4()), run_id=run.id,
                role="assistant", content="Hi there!", seq=1,
            ))
            # Audit record
            db.add(AuditRecord(
                id=str(uuid.uuid4()),
                run_id=run.id,
                agent_id=agent_id,
                capability_name="read_file",
                allowed=True,
                cost=0.0,
                latency_ms=10,
                args='{"path": "/tmp/test"}',
                result='{"content": "hello"}',
            ))
            await db.commit()
            return run.id

    return asyncio.get_event_loop().run_until_complete(_insert())


class TestObservabilityAPI:
    @pytest.fixture
    def client(self):
        """Create a test client with mocked auth."""
        from agentos.main import app

        async def mock_auth():
            return {"id": "op-1", "username": "admin"}

        from agentos.auth import require_operator

        app.dependency_overrides[require_operator] = mock_auth
        client = TestClient(app)
        yield client
        app.dependency_overrides.clear()

    @pytest.fixture
    def db_session(self, db_engine):
        """Create a fresh DB session for API tests."""
        from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

        factory = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)

        async def get_test_db():
            async with factory() as session:
                yield session

        from agentos.db import get_db
        from agentos.main import app

        app.dependency_overrides[get_db] = get_test_db
        yield factory
        app.dependency_overrides.pop(get_db, None)

    def test_list_runs_empty(self, client, db_session):
        resp = client.get("/api/runs")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_list_runs_with_data(self, client, db_session):
        run_id = _make_run(db_session, agent_id="agent-1")
        resp = client.get("/api/runs")
        assert resp.status_code == 200
        runs = resp.json()
        assert len(runs) == 1
        assert runs[0]["id"] == run_id
        assert runs[0]["agent_name"] == "Agent 1"
        assert runs[0]["status"] == "completed"
        assert runs[0]["cost"] == 0.01

    def test_list_runs_filter_by_agent(self, client, db_session):
        _make_run(db_session, agent_id="agent-1")
        _make_run(db_session, agent_id="agent-2")
        resp = client.get("/api/runs?agent_id=agent-1")
        assert resp.status_code == 200
        runs = resp.json()
        assert len(runs) == 1
        assert runs[0]["agent_id"] == "agent-1"

    def test_list_runs_filter_by_status(self, client, db_session):
        _make_run(db_session, agent_id="agent-1", status="completed")
        _make_run(db_session, agent_id="agent-2", status="failed", error="boom")
        resp = client.get("/api/runs?status=failed")
        assert resp.status_code == 200
        runs = resp.json()
        assert len(runs) == 1
        assert runs[0]["status"] == "failed"
        assert runs[0]["error"] == "boom"

    def test_list_runs_filter_by_trigger(self, client, db_session):
        _make_run(db_session, agent_id="agent-1", trigger="user_message")
        _make_run(db_session, agent_id="agent-2", trigger="heartbeat")
        resp = client.get("/api/runs?trigger=heartbeat")
        assert resp.status_code == 200
        runs = resp.json()
        assert len(runs) == 1
        assert runs[0]["trigger"] == "heartbeat"

    def test_list_runs_excludes_test_by_default(self, client, db_session):
        _make_run(db_session, agent_id="agent-1", is_test=False)
        _make_run(db_session, agent_id="agent-2", is_test=True)
        # No is_test filter — returns all
        resp = client.get("/api/runs")
        assert resp.status_code == 200
        assert len(resp.json()) == 2
        # Filter is_test=false
        resp = client.get("/api/runs?is_test=false")
        runs = resp.json()
        assert len(runs) == 1
        assert runs[0]["is_test"] is False

    def test_get_run_detail(self, client, db_session):
        run_id = _make_run(db_session, agent_id="agent-1")
        resp = client.get(f"/api/runs/{run_id}")
        assert resp.status_code == 200
        detail = resp.json()
        assert detail["id"] == run_id
        assert detail["agent_name"] == "Agent 1"
        assert len(detail["messages"]) == 2
        assert detail["messages"][0]["role"] == "user"
        assert detail["messages"][0]["content"] == "Hello"
        assert detail["messages"][1]["role"] == "assistant"
        assert len(detail["audit_records"]) == 1
        assert detail["audit_records"][0]["capability_name"] == "read_file"
        assert detail["audit_records"][0]["allowed"] is True

    def test_get_run_detail_404(self, client, db_session):
        resp = client.get("/api/runs/nonexistent")
        assert resp.status_code == 404

    def test_list_audit_empty(self, client, db_session):
        resp = client.get("/api/audit")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_list_audit_with_data(self, client, db_session):
        _make_run(db_session, agent_id="agent-1")
        resp = client.get("/api/audit")
        assert resp.status_code == 200
        records = resp.json()
        assert len(records) == 1
        assert records[0]["capability_name"] == "read_file"
        assert records[0]["allowed"] is True

    def test_list_audit_filter_by_allowed(self, client, db_session):
        run_id = _make_run(db_session, agent_id="agent-1")
        # Add a denied audit record
        import asyncio


        async def _add_denied():
            async with db_session() as db:
                db.add(AuditRecord(
                    id=str(uuid.uuid4()),
                    run_id=run_id,
                    agent_id="agent-1",
                    capability_name="terminal",
                    allowed=False,
                    denied_reason="Approval denied by operator",
                    cost=0.0,
                    latency_ms=0,
                    args='{"command": "rm -rf /"}',
                ))
                await db.commit()

        asyncio.get_event_loop().run_until_complete(_add_denied())

        # Filter allowed=true
        resp = client.get("/api/audit?allowed=true")
        assert resp.status_code == 200
        records = resp.json()
        assert len(records) == 1
        assert records[0]["allowed"] is True

        # Filter allowed=false
        resp = client.get("/api/audit?allowed=false")
        assert resp.status_code == 200
        records = resp.json()
        assert len(records) == 1
        assert records[0]["allowed"] is False
        assert records[0]["denied_reason"] == "Approval denied by operator"

    def test_list_audit_filter_by_capability(self, client, db_session):
        _make_run(db_session, agent_id="agent-1")
        resp = client.get("/api/audit?capability_name=read_file")
        assert resp.status_code == 200
        assert len(resp.json()) == 1
        resp = client.get("/api/audit?capability_name=nonexistent")
        assert resp.json() == []

    def test_spend_empty(self, client, db_session):
        resp = client.get("/api/spend?days=1")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_cost"] == 0.0
        assert data["total_runs"] == 0
        assert data["by_agent"] == []

    def test_spend_with_data(self, client, db_session):
        _make_run(db_session, agent_id="agent-1", cost=0.05, tokens_in=200, tokens_out=100)
        _make_run(db_session, agent_id="agent-2", cost=0.03, tokens_in=150, tokens_out=80)
        resp = client.get("/api/spend?days=1")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_cost"] == pytest.approx(0.08)
        assert data["total_runs"] == 2
        assert data["total_tokens_in"] == 350
        assert data["total_tokens_out"] == 180
        assert len(data["by_agent"]) == 2
        # Sorted by cost descending — agent-1 should be first
        assert data["by_agent"][0]["agent_id"] == "agent-1"
        assert data["by_agent"][0]["total_cost"] == pytest.approx(0.05)
        assert data["by_agent"][1]["agent_id"] == "agent-2"
        assert data["by_agent"][1]["total_cost"] == pytest.approx(0.03)

    def test_spend_excludes_test_runs(self, client, db_session):
        _make_run(db_session, agent_id="agent-1", cost=0.05, is_test=False)
        _make_run(db_session, agent_id="agent-2", cost=0.99, is_test=True)
        resp = client.get("/api/spend?days=1")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_cost"] == pytest.approx(0.05)
        assert data["total_runs"] == 1

    def test_spend_by_trigger(self, client, db_session):
        _make_run(db_session, agent_id="agent-1", trigger="user_message", cost=0.05)
        _make_run(db_session, agent_id="agent-2", trigger="heartbeat", cost=0.02)
        resp = client.get("/api/spend?days=1")
        assert resp.status_code == 200
        data = resp.json()
        assert data["by_trigger"]["user_message"] == pytest.approx(0.05)
        assert data["by_trigger"]["heartbeat"] == pytest.approx(0.02)

    def test_spend_filter_by_agent(self, client, db_session):
        _make_run(db_session, agent_id="agent-1", cost=0.05)
        _make_run(db_session, agent_id="agent-2", cost=0.03)
        resp = client.get("/api/spend?days=1&agent_id=agent-1")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_cost"] == pytest.approx(0.05)
        assert len(data["by_agent"]) == 1
        assert data["by_agent"][0]["agent_id"] == "agent-1"

    def test_operator_audit_empty(self, client, db_session):
        resp = client.get("/api/operator-audit")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_operator_audit_with_data(self, client, db_session):
        import asyncio

        async def _insert_audit():
            async with db_session() as db:
                # Need an operator first
                op = Operator(
                    id="op-1", username="admin",
                    password_hash="hash", must_change_password=False,
                )
                db.add(op)
                db.add(OperatorAuditLog(
                    id=str(uuid.uuid4()),
                    operator_id="op-1",
                    action="login",
                    target="",
                ))
                db.add(OperatorAuditLog(
                    id=str(uuid.uuid4()),
                    operator_id="op-1",
                    action="change_password",
                    target="op-1",
                ))
                await db.commit()

        asyncio.get_event_loop().run_until_complete(_insert_audit())

        resp = client.get("/api/operator-audit")
        assert resp.status_code == 200
        logs = resp.json()
        assert len(logs) == 2
        # Most recent first
        actions = [log["action"] for log in logs]
        assert "login" in actions
        assert "change_password" in actions

    def test_health(self, client, db_session):
        resp = client.get("/api/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["database"] == "connected"
        assert "agents" in data
        assert "active_runs" in data
        assert "timestamp" in data

    def test_health_with_agents(self, client, db_session):
        _make_run(db_session, agent_id="agent-1")
        resp = client.get("/api/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["agents"] >= 1

    def test_runs_unauthorized(self):
        """Without auth, should return 401."""
        from agentos.main import app

        # Clear any overrides
        app.dependency_overrides.clear()
        client = TestClient(app)
        resp = client.get("/api/runs")
        assert resp.status_code == 401
