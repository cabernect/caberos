"""Tests for dashboard chat recovery metadata."""

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from agentos.api.chat import list_sessions
from agentos.models.agent import Agent
from agentos.models.contact import Contact
from agentos.models.run import Run
from agentos.models.session import Session


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
