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
        channel_config,
        contact,
        document,
        knowledge_index,
        mcp,
        memory,
        operator,
        operator_session,
        provider,
        run,
        session,
        skill,
        source,
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

        await conn.execute(
            text(
                "CREATE VIRTUAL TABLE document_chunks_fts USING fts5("
                "text, chunk_id UNINDEXED, document_id UNINDEXED, agent_id UNINDEXED, "
                "source_path UNINDEXED, storage_path UNINDEXED, heading_path UNINDEXED, page_number UNINDEXED, "
                "sheet_name UNINDEXED, source_location UNINDEXED, tokenize='porter unicode61')"
            )
        )
    yield engine
    try:
        await engine.dispose()
    except Exception:
        # aiosqlite's worker thread can exit before StaticPool finalizes the
        # shared connection on slow/CI hosts, leaving dispose() to fail on a
        # missing 'connection' key — teardown is best-effort for a disposable
        # in-memory engine.
        pass


@pytest_asyncio.fixture
async def db(db_engine, monkeypatch):
    """Yield an async DB session for tests.

    Also patches agentos.db.async_session_factory so that code which
    creates its own session (e.g. the mediator for approval/elicitation)
    uses the same in-memory test engine.
    """
    factory = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)
    import agentos.db as db_module

    monkeypatch.setattr(db_module, "async_session_factory", factory)
    async with factory() as session:
        yield session


@pytest.fixture(autouse=True)
def isolated_fs_roots(tmp_path, monkeypatch):
    """Route all writable runtime roots into tmp_path — tests must never
    touch the real agent home, workspace, knowledge, or data dirs."""
    from agentos.config import settings

    monkeypatch.setattr(settings, "agent_home_root", tmp_path / "agents")
    monkeypatch.setattr(settings, "workspace_root", tmp_path / "workspaces")
    monkeypatch.setattr(settings, "knowledge_root", tmp_path / "knowledge")
    monkeypatch.setattr(settings, "skills_store_root", tmp_path / "skills-store")
    monkeypatch.setattr(settings, "skills_drafts_root", tmp_path / "skills-drafts")
    monkeypatch.setattr(settings, "db_path", tmp_path / "data" / "agentos.db")
    monkeypatch.setattr(settings, "secret_key_path", tmp_path / "data" / "secret.key")
    return tmp_path


@pytest_asyncio.fixture(autouse=True)
async def isolated_db_runtime(db_engine, monkeypatch):
    """Bind agentos.db's module-level engine/factory to the disposable
    per-test engine — ledger, capture, init_db, and background sessions can
    never reach the real database during tests. The explicit `db` fixture
    still yields a session on the same engine; tests that override their
    own factory/engine are unaffected."""
    import agentos.db as db_module

    factory = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(db_module, "engine", db_engine)
    monkeypatch.setattr(db_module, "async_session_factory", factory)
    yield


@pytest.fixture
def workspace(tmp_path):
    """Create a temporary workspace directory."""
    ws = tmp_path / "workspace"
    ws.mkdir()
    return str(ws)


@pytest.fixture
def skills_env(tmp_path, monkeypatch):
    """Patch all four skill roots into tmp_path."""
    import agentos.config as cfg

    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    store = tmp_path / "skills-store"
    drafts = tmp_path / "skills-drafts"
    ws = tmp_path / "workspaces"
    ws.mkdir()
    monkeypatch.setattr(cfg.settings, "skills_dir", skills_dir)
    monkeypatch.setattr(cfg.settings, "skills_store_root", store)
    monkeypatch.setattr(cfg.settings, "skills_drafts_root", drafts)
    monkeypatch.setattr(cfg.settings, "workspace_root", ws)
    return tmp_path


@pytest_asyncio.fixture
async def skills_agent(db):
    from agentos.models.agent import Agent

    a = Agent(id="agent-1", name="Caber", enabled=True)
    db.add(a)
    await db.flush()
    return a


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
