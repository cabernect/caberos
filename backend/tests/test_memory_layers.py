"""Tests for the 4-layer memory system (D34 — revised).

Layers:
1. Episodic — session summaries (FTS5) + raw messages (FTS5)
2. Working — run-scoped memory_entries, deleted at run end
3. Semantic — MEMORY.md (file, auto-extracted at run end)
4. KG — memory_triples (auto-extracted at session close)

Also tests:
- search_history tool (episodic — exact recall)
- search_session_summaries (episodic — topical recall)
- close_session (summary + KG extraction)
- find_idle_sessions (sweeper query)
- clear_run_entries (working memory cleanup)
"""

from datetime import UTC, datetime, timedelta

import pytest

from agentos.capabilities.builtin import register_builtin_capabilities
from agentos.capabilities.registry import registry
from agentos.config_schema import AgentConfig, ModelConfig
from agentos.models.session import Session


@pytest.fixture(autouse=True)
def _setup_caps():
    registry._caps.clear()
    register_builtin_capabilities()
    yield
    registry._caps.clear()


def _make_agent_config() -> AgentConfig:
    return AgentConfig(
        id="test-agent",
        name="Test Agent",
        model=ModelConfig(provider_id="test-provider", name="test-model"),
    )


async def _create_contact(db, contact_id: str, agent_id: str = "test-agent"):
    from agentos.models.contact import Contact

    contact = Contact(
        id=contact_id,
        channel="dashboard_chat",
        bot_id=agent_id,
        external_user_id=contact_id,
        display_name="Test Contact",
    )
    db.add(contact)
    await db.flush()
    return contact


class TestEpisodicIndexing:
    """Episodic layer — raw message FTS5 indexing and search."""

    async def test_index_and_search_message(self, db):
        from agentos.memory.episodic import index_message, search_history

        await index_message(
            db,
            message_id="msg-1",
            run_id="run-1",
            session_id="sess-1",
            agent_id="test-agent",
            content="The connection string was postgres://localhost:5432/mydb",
        )
        await db.commit()

        results = await search_history(db, "test-agent", "connection string")
        assert len(results) == 1
        assert "postgres://localhost:5432" in results[0]["content"]

    async def test_search_history_no_results(self, db):
        from agentos.memory.episodic import search_history

        results = await search_history(db, "test-agent", "nonexistent query xyz")
        assert len(results) == 0

    async def test_search_history_agent_isolation(self, db):
        from agentos.memory.episodic import index_message, search_history

        await index_message(
            db,
            message_id="msg-1",
            run_id="run-1",
            session_id="sess-1",
            agent_id="agent-a",
            content="secret data for agent a",
        )
        await db.commit()

        # Agent B should not see agent A's messages
        results = await search_history(db, "agent-b", "secret data")
        assert len(results) == 0


class TestSessionSummaries:
    """Episodic layer — session summary FTS5 search."""

    async def test_search_session_summaries(self, db):
        from sqlalchemy import text

        from agentos.memory.episodic import search_session_summaries

        await _create_contact(db, "contact-1")

        # Insert a session summary directly into FTS
        await db.execute(
            text(
                "INSERT INTO session_summaries_fts (session_id, agent_id, contact_id, summary) "
                "VALUES (:sid, :aid, :cid, :summary)"
            ),
            {
                "sid": "sess-1",
                "aid": "test-agent",
                "cid": "contact-1",
                "summary": "User uploaded a PDF timesheet and asked for hour extraction.",
            },
        )
        await db.commit()

        results = await search_session_summaries(
            db, "test-agent", "contact-1", "PDF timesheet"
        )
        assert len(results) == 1
        assert "PDF timesheet" in results[0]["summary"]

    async def test_search_summaries_contact_isolation(self, db):
        from sqlalchemy import text

        from agentos.memory.episodic import search_session_summaries

        await _create_contact(db, "contact-1")
        await _create_contact(db, "contact-2")

        await db.execute(
            text(
                "INSERT INTO session_summaries_fts (session_id, agent_id, contact_id, summary) "
                "VALUES (:sid, :aid, :cid, :summary)"
            ),
            {
                "sid": "sess-1",
                "aid": "test-agent",
                "cid": "contact-1",
                "summary": "Contact 1 discussed project alpha.",
            },
        )
        await db.commit()

        # Contact 2 should not see contact 1's summaries
        results = await search_session_summaries(db, "test-agent", "contact-2", "project alpha")
        assert len(results) == 0


class TestWorkingMemory:
    """Working layer — run-scoped entries, cleanup at run end."""

    async def test_store_with_run_id(self, db):
        from agentos.memory.recall import get_run_entries, store_snippet

        await _create_contact(db, "contact-1")

        await store_snippet(
            db,
            contact_id="contact-1",
            agent_id="test-agent",
            key="task_state",
            value="User chose Postgres for the database",
            tags=["important"],
            run_id="run-1",
        )
        await db.commit()

        entries = await get_run_entries(db, "run-1")
        assert len(entries) == 1
        assert entries[0]["key"] == "task_state"
        assert "Postgres" in entries[0]["value"]

    async def test_clear_run_entries(self, db):
        from agentos.memory.recall import clear_run_entries, get_run_entries, store_snippet

        await _create_contact(db, "contact-1")

        await store_snippet(
            db, "contact-1", "test-agent", "note1", "value1", run_id="run-1"
        )
        await store_snippet(
            db, "contact-1", "test-agent", "note2", "value2", run_id="run-1"
        )
        await store_snippet(
            db, "contact-1", "test-agent", "note3", "value3", run_id="run-2"
        )
        await db.commit()

        # Delete run-1 entries
        deleted = await clear_run_entries(db, "run-1")
        assert deleted == 2
        await db.commit()

        # run-1 entries gone, run-2 still there
        assert len(await get_run_entries(db, "run-1")) == 0
        assert len(await get_run_entries(db, "run-2")) == 1

    async def test_store_without_run_id_persists(self, db):
        """Entries without run_id are NOT run-scoped — they persist."""
        from sqlalchemy import select

        from agentos.memory.recall import clear_run_entries, store_snippet
        from agentos.models.memory import MemoryEntry

        await _create_contact(db, "contact-1")

        await store_snippet(
            db, "contact-1", "test-agent", "permanent", "always remember this"
        )
        await db.commit()

        # Clearing any run_id should not affect entries without run_id
        await clear_run_entries(db, "some-run")
        await db.commit()

        result = await db.execute(
            select(MemoryEntry).where(MemoryEntry.key == "permanent")
        )
        assert result.scalar_one_or_none() is not None


class TestFindIdleSessions:
    """Session close — find_idle_sessions query."""

    async def test_find_idle_session(self, db):
        from agentos.memory.episodic import find_idle_sessions

        await _create_contact(db, "contact-1")

        # Create a session that's been idle for 60 minutes
        old_time = datetime.now(UTC).replace(tzinfo=None) - timedelta(minutes=60)
        session = Session(
            id="idle-sess",
            contact_id="contact-1",
            agent_id="test-agent",
            status="active",
            last_activity_at=old_time,
            closed=False,
        )
        db.add(session)
        await db.commit()

        idle = await find_idle_sessions(db, idle_minutes=30)
        assert any(s.id == "idle-sess" for s in idle)

    async def test_does_not_find_closed_session(self, db):
        from agentos.memory.episodic import find_idle_sessions

        await _create_contact(db, "contact-1")

        old_time = datetime.now(UTC).replace(tzinfo=None) - timedelta(minutes=60)
        session = Session(
            id="closed-sess",
            contact_id="contact-1",
            agent_id="test-agent",
            status="closed",
            last_activity_at=old_time,
            closed=True,
        )
        db.add(session)
        await db.commit()

        idle = await find_idle_sessions(db, idle_minutes=30)
        assert not any(s.id == "closed-sess" for s in idle)

    async def test_does_not_find_recent_session(self, db):
        from agentos.memory.episodic import find_idle_sessions

        await _create_contact(db, "contact-1")

        # Session active 5 minutes ago — not idle
        recent_time = datetime.now(UTC).replace(tzinfo=None) - timedelta(minutes=5)
        session = Session(
            id="recent-sess",
            contact_id="contact-1",
            agent_id="test-agent",
            status="active",
            last_activity_at=recent_time,
            closed=False,
        )
        db.add(session)
        await db.commit()

        idle = await find_idle_sessions(db, idle_minutes=30)
        assert not any(s.id == "recent-sess" for s in idle)


class TestCloseSession:
    """Session close — close_session() with idempotency guard."""

    async def test_close_session_no_messages(self, db):
        """Closing a session with no messages just marks it closed."""
        from agentos.memory.episodic import close_session

        await _create_contact(db, "contact-1")

        session = Session(
            id="empty-sess",
            contact_id="contact-1",
            agent_id="test-agent",
            status="active",
            closed=False,
        )
        db.add(session)
        await db.flush()

        agent_config = _make_agent_config()
        await close_session(db, agent_config, session, "contact-1")
        await db.commit()

        assert session.closed is True
        assert session.status == "closed"

    async def test_close_session_idempotent(self, db):
        """Closing an already-closed session is a no-op."""
        from agentos.memory.episodic import close_session

        await _create_contact(db, "contact-1")

        session = Session(
            id="already-closed",
            contact_id="contact-1",
            agent_id="test-agent",
            status="closed",
            closed=True,
            summary="Existing summary",
        )
        db.add(session)
        await db.flush()

        agent_config = _make_agent_config()
        # Should not re-extract or overwrite the summary
        await close_session(db, agent_config, session, "contact-1")
        await db.commit()

        assert session.summary == "Existing summary"


class TestSearchHistoryTool:
    """search_history capability — the agent-facing tool."""

    async def test_search_history_tool_registered(self):
        """search_history should be in the registry."""
        cap = registry.get("search_history")
        assert cap is not None
        assert cap.kind == "memory"
        assert cap.egress is False
        assert cap.require_approval is False

    async def test_search_history_tool_executes(self, db):
        from agentos.capabilities.tools.memory import search_history
        from agentos.memory.episodic import index_message

        await index_message(
            db,
            message_id="msg-1",
            run_id="run-1",
            session_id="sess-1",
            agent_id="test-agent",
            content="Error: connection refused on port 5432",
        )
        await db.commit()

        result = await search_history(
            {"query": "connection refused"},
            db=db,
            agent_id="test-agent",
            contact_id="contact-1",
        )
        assert result["count"] == 1
        assert "connection refused" in result["results"][0]["content"]


class TestContextAssembly:
    """System prompt assembly — past sessions injection."""

    def test_past_sessions_injected(self):
        from agentos.harness.context import assemble_system_prompt

        agent_config = _make_agent_config()
        prompt = assemble_system_prompt(
            agent_config,
            user_message="test",
            past_sessions=[
                {"session_id": "s1", "summary": "User worked on PDF timesheet extraction."},
                {"session_id": "s2", "summary": "User asked about Postgres config."},
            ],
        )
        assert "Past Context" in prompt
        assert "PDF timesheet" in prompt
        assert "Postgres" in prompt

    def test_no_past_sessions_section_when_empty(self):
        from agentos.harness.context import assemble_system_prompt

        agent_config = _make_agent_config()
        prompt = assemble_system_prompt(agent_config, user_message="test")
        assert "Past Context" not in prompt

    def test_past_sessions_char_budget(self):
        from agentos.harness.context import assemble_system_prompt

        agent_config = _make_agent_config()
        # Very long summaries should be truncated
        long_summary = "A" * 600
        prompt = assemble_system_prompt(
            agent_config,
            user_message="test",
            past_sessions=[{"session_id": "s1", "summary": long_summary}],
        )
        # Should be truncated (budget is 500 chars)
        assert "Past Context" in prompt
        assert "..." in prompt
