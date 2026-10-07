"""Tests for dashboard chat recovery metadata."""

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from sqlalchemy import select, text

from agentos.api.chat import delete_session, get_session_messages, list_sessions
from agentos.models.agent import Agent
from agentos.models.contact import Contact
from agentos.models.execution_manifest import ExecutionManifest
from agentos.models.model_call import ModelCall
from agentos.models.run import Message, Run
from agentos.models.session import Session
from agentos.models.source import RunSource
from agentos.models.web_source import WebSource


@pytest.mark.asyncio
async def test_list_sessions_exposes_active_run_for_reconnect(db):
    agent_id = "chat-recovery-agent"
    session_id = "chat-recovery-session"
    run_id = "chat-recovery-run"
    now = datetime.now(UTC)

    db.add(Agent(id=agent_id, name="Recovery Agent"))
    db.add(
        Contact(
            id="chat-recovery-contact",
            channel="dashboard_chat",
            bot_id=agent_id,
            external_user_id="operator-1",
        )
    )
    db.add(
        Session(
            id=session_id,
            agent_id=agent_id,
            contact_id="chat-recovery-contact",
            status="active",
            last_activity_at=now,
        )
    )
    db.add(
        Run(
            id=run_id,
            session_id=session_id,
            contact_id="chat-recovery-contact",
            agent_id=agent_id,
            status="running",
            trigger="user_message",
            started_at=now,
        )
    )
    await db.commit()

    sessions = await list_sessions(
        agent_id,
        operator=SimpleNamespace(id="operator-1"),
        db=db,
    )

    assert sessions == [
        {
            "id": session_id,
            "title": "New conversation",
            "status": "active",
            "started_at": sessions[0]["started_at"],
            "last_activity_at": sessions[0]["last_activity_at"],
            "message_count": 0,
            "channel": None,
            "external_user_id": None,
            "active_run_id": run_id,
            "active_run_status": "running",
        }
    ]


@pytest.mark.asyncio
async def test_delete_session_removes_full_run_cascade(db):
    """B4: session delete must clear every run child — manifests, model
    calls, run/web sources — plus the standalone messages_fts rows."""
    agent_id = "delete-cascade-agent"
    session_id = "delete-cascade-session"
    run_id = "delete-cascade-run"

    db.add(Agent(id=agent_id, name="Cascade Agent"))
    db.add(
        Contact(
            id="delete-cascade-contact",
            channel="dashboard_chat",
            bot_id=agent_id,
            external_user_id="operator-1",
        )
    )
    db.add(
        Session(
            id=session_id,
            agent_id=agent_id,
            contact_id="delete-cascade-contact",
            status="active",
        )
    )
    db.add(
        Run(
            id=run_id,
            session_id=session_id,
            contact_id="delete-cascade-contact",
            agent_id=agent_id,
            status="completed",
            trigger="user_message",
        )
    )
    db.add(Message(id="delete-cascade-msg", run_id=run_id, role="user", content="hi"))
    db.add(ExecutionManifest(id="delete-cascade-man", run_id=run_id))
    db.add(ModelCall(id="delete-cascade-call", run_id=run_id, agent_id=agent_id))
    db.add(
        RunSource(
            id="delete-cascade-src",
            run_id=run_id,
            message_id="delete-cascade-msg",
            chunk_id="c1",
            document_id="d1",
            source_path="p",
            storage_path="s",
            excerpt="e",
        )
    )
    db.add(
        WebSource(
            id="delete-cascade-web",
            run_id=run_id,
            message_id="delete-cascade-msg",
            url="https://example.com",
        )
    )
    await db.flush()
    await db.execute(
        text(
            "INSERT INTO messages_fts (message_id, run_id, session_id, agent_id, content) "
            "VALUES ('delete-cascade-msg', :rid, :sid, :aid, 'hi')"
        ),
        {"rid": run_id, "sid": session_id, "aid": agent_id},
    )
    await db.commit()

    result = await delete_session(
        agent_id,
        session_id,
        operator=SimpleNamespace(id="operator-1"),
        db=db,
    )
    assert result == {"deleted": True}

    remaining_runs = await db.execute(select(Run).where(Run.id == run_id))
    assert remaining_runs.scalars().all() == []
    for model in (Message, ExecutionManifest, ModelCall, RunSource, WebSource):
        remaining = await db.execute(select(model).where(model.run_id == run_id))
        assert remaining.scalars().all() == [], model.__name__
    remaining_fts = await db.execute(
        text("SELECT COUNT(*) FROM messages_fts WHERE run_id = :rid"), {"rid": run_id}
    )
    assert remaining_fts.scalar() == 0
    remaining_sessions = await db.execute(select(Session).where(Session.id == session_id))
    assert remaining_sessions.scalar_one_or_none() is None


@pytest.mark.asyncio
async def test_session_messages_limit_returns_newest(db):
    """ASC + LIMIT pinned the list to the session's first `limit` rows — once
    a session outgrew it, every new reply vanished from the chatview (B44)."""
    agent_id = "limit-agent"
    session_id = "limit-session"
    db.add(Agent(id=agent_id, name="Limit Agent"))
    db.add(
        Contact(
            id="limit-contact",
            channel="dashboard_chat",
            bot_id=agent_id,
            external_user_id="operator-1",
        )
    )
    db.add(
        Session(
            id=session_id,
            agent_id=agent_id,
            contact_id="limit-contact",
            status="active",
        )
    )
    # Five runs × two messages each — seq resets per run. started_at is
    # explicit because same-commit rows can share a timestamp.
    base = datetime.now(UTC)
    for i in range(5):
        run_id = f"limit-run-{i}"
        db.add(
            Run(
                id=run_id,
                session_id=session_id,
                contact_id="limit-contact",
                agent_id=agent_id,
                status="completed",
                trigger="user_message",
                started_at=base.replace(second=i),
            )
        )
        db.add(Message(id=f"{run_id}-u", run_id=run_id, role="user", content=f"q{i}", seq=0))
        db.add(Message(id=f"{run_id}-a", run_id=run_id, role="assistant", content=f"a{i}", seq=1))
    await db.commit()

    page = await get_session_messages(
        agent_id, session_id, operator=SimpleNamespace(id="operator-1"), db=db, limit=4
    )
    # The newest four messages, still chronological — and older rows remain.
    assert page["has_more"] is True
    assert [m["content"] for m in page["messages"]] == ["q3", "a3", "q4", "a4"]

    # Page upward: everything strictly before the oldest loaded message.
    older = await get_session_messages(
        agent_id,
        session_id,
        operator=SimpleNamespace(id="operator-1"),
        db=db,
        limit=4,
        before_id=page["messages"][0]["id"],
    )
    assert [m["content"] for m in older["messages"]] == ["q1", "a1", "q2", "a2"]
    assert older["has_more"] is True

    oldest = await get_session_messages(
        agent_id,
        session_id,
        operator=SimpleNamespace(id="operator-1"),
        db=db,
        limit=4,
        before_id=older["messages"][0]["id"],
    )
    assert [m["content"] for m in oldest["messages"]] == ["q0", "a0"]
    assert oldest["has_more"] is False
