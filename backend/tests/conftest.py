"""Test fixtures shared across all tests."""

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# Use in-memory SQLite for tests
TEST_DB_URL = "sqlite+aiosqlite:///:memory:"


@pytest_asyncio.fixture
async def db_engine():
    """Create an in-memory SQLite engine for tests."""
    from agentos.models import (  # noqa: F401
        agent,
        approval,
        audit,
        capability,
        connector,
        contact,
        memory,
        operator,
        provider,
        run,
        session,
        sub_agent,
    )
    from agentos.models.base import Base

    engine = create_async_engine(TEST_DB_URL, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # Create FTS5 virtual tables for memory tests (D34)
        from sqlalchemy import text

        # 1. Working memory FTS (for memory_recall tool)
        result = await conn.execute(
            text("SELECT name FROM sqlite_master WHERE type='table' AND name='memory_fts'")
        )
        if result.fetchone() is None:
            await conn.execute(
                text(
                    "CREATE VIRTUAL TABLE memory_fts USING fts5("
                    "content, entry_id UNINDEXED, contact_id UNINDEXED, agent_id UNINDEXED, "
                    "tokenize='porter unicode61')"
                )
            )

        # 2. Raw messages FTS (episodic — exact recall via search_history)
        result = await conn.execute(
            text("SELECT name FROM sqlite_master WHERE type='table' AND name='messages_fts'")
        )
        if result.fetchone() is None:
            await conn.execute(
                text(
                    "CREATE VIRTUAL TABLE messages_fts USING fts5("
                    "content, message_id UNINDEXED, run_id UNINDEXED, "
                    "session_id UNINDEXED, agent_id UNINDEXED, "
                    "tokenize='porter unicode61')"
                )
            )

        # 3. Session summaries FTS (episodic — topical recall at run start)
        result = await conn.execute(
            text(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='session_summaries_fts'"
            )
        )
        if result.fetchone() is None:
            await conn.execute(
                text(
                    "CREATE VIRTUAL TABLE session_summaries_fts USING fts5("
                    "summary, session_id UNINDEXED, agent_id UNINDEXED, "
                    "contact_id UNINDEXED, tokenize='porter unicode61')"
                )
            )
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def db(db_engine):
    """Yield an async DB session for tests."""
    factory = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session


@pytest.fixture
def workspace(tmp_path):
    """Create a temporary workspace directory."""
    ws = tmp_path / "workspace"
    ws.mkdir()
    return str(ws)


@pytest.fixture(autouse=True)
def _register_capabilities():
    """Register built-in capabilities before each test."""
    from agentos.capabilities.builtin import register_builtin_capabilities
    from agentos.capabilities.registry import registry

    # Clear and re-register
    registry._caps.clear()
    register_builtin_capabilities()
    yield
    registry._caps.clear()
