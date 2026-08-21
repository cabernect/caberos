"""Tests for operator authentication (D4)."""

import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from agentos.db import get_db
from agentos.main import app

pytest_asyncio_fixture = pytest_asyncio.fixture


@pytest_asyncio.fixture
async def client(db_engine):
    """HTTP client with test DB override."""
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    factory = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)

    async def override_get_db():
        async with factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def seeded_client(client):
    """Client with a default operator seeded."""
    import bcrypt
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    factory = async_sessionmaker(
        client._transport.app.dependency_overrides[get_db].__wrapped__().__self__.__class__,
        class_=AsyncSession,
        expire_on_commit=False,
    )  # noqa: E501
    # Simpler: just seed via the DB directly
    # Actually, let's seed via the API or DB
    import uuid

    from agentos.models.operator import Operator

    async def seed_op():
        async with factory() as db:
            from sqlalchemy import select

            result = await db.execute(select(Operator).where(Operator.username == "admin"))
            if result.scalar_one_or_none() is None:
                password_hash = bcrypt.hashpw(b"admin", bcrypt.gensalt()).decode()
                op = Operator(
                    id=str(uuid.uuid4()),
                    username="admin",
                    password_hash=password_hash,
                    must_change_password=True,
                )
                db.add(op)
                await db.commit()

    # We need the engine from the fixture, but it's not directly accessible.
    # Instead, let's use the test DB directly.
    return client


class TestAuth:
    async def test_login_wrong_password(self, client, db_engine):
        # First seed an operator
        await _seed_operator(db_engine, "admin", "admin")
        resp = await client.post(
            "/api/auth/login",
            json={"username": "admin", "password": "wrong"},
        )
        assert resp.status_code == 401

    async def test_login_correct(self, client, db_engine):
        await _seed_operator(db_engine, "admin", "admin")
        resp = await client.post(
            "/api/auth/login",
            json={"username": "admin", "password": "admin"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["operator"]["username"] == "admin"
        assert data["must_change_password"] is True
        # Session cookie should be set
        cookies = resp.cookies
        assert "agentos_session" in cookies

    async def test_desktop_login_cookie_uses_same_site_attributes(self, client, db_engine):
        await _seed_operator(db_engine, "admin", "admin")
        resp = await client.post(
            "/api/auth/login",
            json={"username": "admin", "password": "admin"},
            headers={"Origin": "http://tauri.localhost"},
        )
        assert resp.status_code == 200
        cookie = resp.headers["set-cookie"].lower()
        assert "samesite=lax" in cookie
        assert "secure" not in cookie

    async def test_me_without_auth(self, client):
        resp = await client.get("/api/auth/me")
        assert resp.status_code == 401

    async def test_me_with_auth(self, client, db_engine):
        await _seed_operator(db_engine, "admin", "admin")
        await client.post(
            "/api/auth/login",
            json={"username": "admin", "password": "admin"},
        )
        resp = await client.get("/api/auth/me")
        assert resp.status_code == 200
        assert resp.json()["username"] == "admin"

    async def test_logout(self, client, db_engine):
        await _seed_operator(db_engine, "admin", "admin")
        await client.post(
            "/api/auth/login",
            json={"username": "admin", "password": "admin"},
        )
        resp = await client.post("/api/auth/logout")
        assert resp.status_code == 200
        # After logout, /me should fail
        resp = await client.get("/api/auth/me")
        assert resp.status_code == 401

    async def test_login_returns_session_token(self, client, db_engine):
        """Login response includes a session_token for bearer-token auth (desktop shell)."""
        await _seed_operator(db_engine, "admin", "admin")
        resp = await client.post(
            "/api/auth/login",
            json={"username": "admin", "password": "admin"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "session_token" in data
        assert data["session_token"]

    async def test_me_with_bearer_token(self, client, db_engine):
        """/api/auth/me works with Authorization: Bearer <token> (no cookie)."""
        await _seed_operator(db_engine, "admin", "admin")
        resp = await client.post(
            "/api/auth/login",
            json={"username": "admin", "password": "admin"},
        )
        token = resp.json()["session_token"]
        # Use a fresh client (no cookies) with only the bearer token
        resp2 = await client.get(
            "/api/auth/me",
            headers={"Authorization": f"Bearer {token}"},
            cookies={},
        )
        assert resp2.status_code == 200
        assert resp2.json()["username"] == "admin"

    async def test_logout_with_bearer_token(self, client, db_engine):
        """Logout works with bearer token and invalidates the session."""
        await _seed_operator(db_engine, "admin", "admin")
        resp = await client.post(
            "/api/auth/login",
            json={"username": "admin", "password": "admin"},
        )
        token = resp.json()["session_token"]
        resp2 = await client.post(
            "/api/auth/logout",
            headers={"Authorization": f"Bearer {token}"},
            cookies={},
        )
        assert resp2.status_code == 200
        # Token should now be invalid
        resp3 = await client.get(
            "/api/auth/me",
            headers={"Authorization": f"Bearer {token}"},
            cookies={},
        )
        assert resp3.status_code == 401

    async def test_change_password(self, client, db_engine):
        await _seed_operator(db_engine, "admin", "admin")
        await client.post(
            "/api/auth/login",
            json={"username": "admin", "password": "admin"},
        )
        resp = await client.post(
            "/api/auth/change-password",
            json={"old_password": "admin", "new_password": "newpass123"},
        )
        assert resp.status_code == 200
        # Old password should no longer work
        resp = await client.post(
            "/api/auth/login",
            json={"username": "admin", "password": "admin"},
        )
        assert resp.status_code == 401
        # New password should work
        resp = await client.post(
            "/api/auth/login",
            json={"username": "admin", "password": "newpass123"},
        )
        assert resp.status_code == 200


async def _seed_operator(db_engine, username: str, password: str):
    """Helper: seed an operator directly into the DB."""
    import uuid

    import bcrypt
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from agentos.models.operator import Operator

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
