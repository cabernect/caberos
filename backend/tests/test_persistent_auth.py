"""Tests for persistent authentication sessions (v0.1.3 Trust Bundle).

Covers:
- login remains valid after engine disposal and backend re-initialization
- raw session token is not stored (only the hash)
- expired session is rejected
- logout revokes the session
- expired sessions are cleaned
- cookie and bearer authentication resolve the same persisted session
"""

import uuid
from datetime import UTC, datetime, timedelta

import bcrypt
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agentos.db import get_db
from agentos.main import app
from agentos.models.operator import Operator


async def _seed_operator(db_engine, username: str = "admin", password: str = "admin"):
    factory = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as db:
        result = await db.execute(select(Operator).where(Operator.username == username))
        if result.scalar_one_or_none() is None:
            password_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
            op = Operator(
                id=str(uuid.uuid4()),
                username=username,
                password_hash=password_hash,
                must_change_password=True,
            )
            db.add(op)
            await db.commit()


@pytest_asyncio.fixture
async def client(db_engine):
    """HTTP client with test DB override."""
    factory = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)

    async def override_get_db():
        async with factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    # Also patch the session factory used by auth for separate-session lookups
    import agentos.db as db_module

    original_factory = db_module.async_session_factory
    db_module.async_session_factory = factory
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()
    db_module.async_session_factory = original_factory


class TestPersistentAuth:
    """Tests for persistent (DB-backed) authentication sessions."""

    async def test_login_creates_persisted_session(self, client, db_engine):
        """Login creates a session row in the database."""
        from agentos.models.operator_session import OperatorSession

        await _seed_operator(db_engine)
        resp = await client.post(
            "/api/auth/login",
            json={"username": "admin", "password": "admin"},
        )
        assert resp.status_code == 200
        token = resp.json()["session_token"]

        # The session should be in the DB (by token hash)
        factory = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)
        async with factory() as db:
            import hashlib

            token_hash = hashlib.sha256(token.encode()).hexdigest()
            result = await db.execute(
                select(OperatorSession).where(OperatorSession.token_hash == token_hash)
            )
            session = result.scalar_one_or_none()
            assert session is not None
            assert session.operator_id is not None

    async def test_raw_token_not_stored(self, client, db_engine):
        """The raw session token is not stored in the DB — only its hash."""
        from agentos.models.operator_session import OperatorSession

        await _seed_operator(db_engine)
        resp = await client.post(
            "/api/auth/login",
            json={"username": "admin", "password": "admin"},
        )
        token = resp.json()["session_token"]

        factory = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)
        async with factory() as db:
            result = await db.execute(select(OperatorSession))
            sessions = result.scalars().all()
            assert len(sessions) >= 1
            for s in sessions:
                # The raw token must not appear in any column
                assert token not in (s.token_hash or "")
                assert token != s.token_hash

    async def test_session_survives_engine_disposal(self, tmp_path):
        """Login remains valid after engine disposal and re-initialization.

        Uses a file-based SQLite DB because in-memory DBs are lost on disposal.
        """
        from sqlalchemy.ext.asyncio import create_async_engine

        from agentos.models import (  # noqa: F401
            agent,
            approval,
            audit,
            capability,
            channel_config,
            contact,
            mcp,
            memory,
            operator,
            operator_session,
            provider,
            run,
            session,
            sub_agent,
        )
        from agentos.models.base import Base

        db_file = tmp_path / "test_auth.db"
        engine = create_async_engine(f"sqlite+aiosqlite:///{db_file}")
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

        # Seed operator
        async with factory() as db:
            op = Operator(
                id=str(uuid.uuid4()),
                username="admin",
                password_hash=bcrypt.hashpw(b"admin", bcrypt.gensalt()).decode(),
                must_change_password=True,
            )
            db.add(op)
            await db.commit()

        # Patch the DB dependency and factory
        import agentos.db as db_module

        original_factory = db_module.async_session_factory
        db_module.async_session_factory = factory

        async def override_get_db():
            async with factory() as db_session:
                yield db_session

        app.dependency_overrides[get_db] = override_get_db

        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as c:
                resp = await c.post(
                    "/api/auth/login",
                    json={"username": "admin", "password": "admin"},
                )
                assert resp.status_code == 200
                token = resp.json()["session_token"]

                # Simulate restart: dispose and recreate the engine
                await engine.dispose()
                engine = create_async_engine(f"sqlite+aiosqlite:///{db_file}")
                new_factory = async_sessionmaker(
                    engine, class_=AsyncSession, expire_on_commit=False
                )
                db_module.async_session_factory = new_factory

                async def override_get_db2():
                    async with new_factory() as db_session:
                        yield db_session

                app.dependency_overrides[get_db] = override_get_db2

                # The token should still work (it's in the DB, not memory)
                resp2 = await c.get(
                    "/api/auth/me",
                    headers={"Authorization": f"Bearer {token}"},
                    cookies={},
                )
                assert resp2.status_code == 200
                assert resp2.json()["username"] == "admin"
        finally:
            app.dependency_overrides.clear()
            db_module.async_session_factory = original_factory
            await engine.dispose()

    async def test_expired_session_rejected(self, client, db_engine):
        """An expired session is rejected."""
        from agentos.models.operator_session import OperatorSession

        await _seed_operator(db_engine)
        resp = await client.post(
            "/api/auth/login",
            json={"username": "admin", "password": "admin"},
        )
        token = resp.json()["session_token"]

        # Manually expire the session in the DB
        import hashlib

        token_hash = hashlib.sha256(token.encode()).hexdigest()
        factory = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)
        async with factory() as db:
            result = await db.execute(
                select(OperatorSession).where(OperatorSession.token_hash == token_hash)
            )
            session = result.scalar_one_or_none()
            session.expires_at = datetime.now(UTC) - timedelta(hours=1)
            await db.commit()

        # The expired token should be rejected
        resp2 = await client.get(
            "/api/auth/me",
            headers={"Authorization": f"Bearer {token}"},
            cookies={},
        )
        assert resp2.status_code == 401

    async def test_logout_revokes_session(self, client, db_engine):
        """Logout revokes the session from the DB."""
        from agentos.models.operator_session import OperatorSession

        await _seed_operator(db_engine)
        resp = await client.post(
            "/api/auth/login",
            json={"username": "admin", "password": "admin"},
        )
        token = resp.json()["session_token"]

        # Logout
        resp2 = await client.post(
            "/api/auth/logout",
            headers={"Authorization": f"Bearer {token}"},
            cookies={},
        )
        assert resp2.status_code == 200

        # Token should no longer work
        resp3 = await client.get(
            "/api/auth/me",
            headers={"Authorization": f"Bearer {token}"},
            cookies={},
        )
        assert resp3.status_code == 401

        # Session row should be deleted
        import hashlib

        token_hash = hashlib.sha256(token.encode()).hexdigest()
        factory = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)
        async with factory() as db:
            result = await db.execute(
                select(OperatorSession).where(OperatorSession.token_hash == token_hash)
            )
            assert result.scalar_one_or_none() is None

    async def test_cookie_and_bearer_resolve_same_session(self, client, db_engine):
        """Cookie and bearer authentication resolve the same persisted session."""
        await _seed_operator(db_engine)
        resp = await client.post(
            "/api/auth/login",
            json={"username": "admin", "password": "admin"},
        )
        token = resp.json()["session_token"]

        # With cookie
        resp_cookie = await client.get("/api/auth/me")
        assert resp_cookie.status_code == 200

        # With bearer (no cookie)
        resp_bearer = await client.get(
            "/api/auth/me",
            headers={"Authorization": f"Bearer {token}"},
            cookies={},
        )
        assert resp_bearer.status_code == 200
        assert resp_cookie.json()["username"] == resp_bearer.json()["username"]

    async def test_expired_sessions_cleaned(self, client, db_engine):
        """Expired sessions are cleaned up."""
        from agentos.models.operator_session import OperatorSession

        await _seed_operator(db_engine)

        # Create a session and manually expire it
        factory = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)
        async with factory() as db:
            expired_session = OperatorSession(
                id=str(uuid.uuid4()),
                token_hash="expired-hash-" + str(uuid.uuid4()),
                operator_id=(await db.execute(select(Operator))).scalar_one().id,
                expires_at=datetime.now(UTC) - timedelta(hours=1),
            )
            db.add(expired_session)
            await db.commit()

        # Run cleanup
        from agentos.auth import cleanup_expired_sessions

        await cleanup_expired_sessions(db_engine)

        # Expired session should be gone
        async with factory() as db:
            result = await db.execute(
                select(OperatorSession).where(
                    OperatorSession.token_hash == expired_session.token_hash
                )
            )
            assert result.scalar_one_or_none() is None
