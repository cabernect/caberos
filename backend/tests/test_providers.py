"""Tests for provider management API (D39, D40)."""

import uuid

import bcrypt
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from agentos.db import get_db
from agentos.main import app

pytest_asyncio_fixture = pytest_asyncio.fixture


def test_classify_provider_errors():
    from agentos.api.providers import classify_provider_error

    assert classify_provider_error("429 rate limit exceeded")[0] == "rate_limit"
    assert classify_provider_error("401 invalid api key")[0] == "authentication"
    assert classify_provider_error("request timeout")[0] == "network"
    assert classify_provider_error("unexpected response")[0] == "internal"


async def _seed_operator(db_engine, username="admin", password="admin"):
    """Seed a test operator directly into the DB."""
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from agentos.models.operator import Operator

    factory = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as db:
        result = await db.execute(select(Operator).where(Operator.username == username))
        if result.scalar_one_or_none() is None:
            password_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
            db.add(Operator(id=str(uuid.uuid4()), username=username, password_hash=password_hash))
            await db.commit()


@pytest_asyncio_fixture
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


@pytest_asyncio_fixture
async def auth_headers(client, db_engine):
    """Login as the default operator and return Authorization headers."""
    await _seed_operator(db_engine)
    resp = await client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "admin"},
    )
    assert resp.status_code == 200
    token = resp.json()["session_token"]
    return {"Authorization": f"Bearer {token}"}


class TestProviderCRUD:
    async def test_create_provider(self, client, auth_headers):
        resp = await client.post(
            "/api/providers",
            json={
                "name": "My OpenAI",
                "type": "openai",
                "api_key": "sk-test-key-12345",
            },
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "My OpenAI"
        assert data["type"] == "openai"
        assert data["has_key"] is True
        assert "api_key" not in data  # key never returned in plaintext

    async def test_list_providers(self, client, auth_headers):
        await client.post(
            "/api/providers",
            json={"name": "Provider A", "type": "openai", "api_key": "sk-a"},
            headers=auth_headers,
        )
        await client.post(
            "/api/providers",
            json={"name": "Provider B", "type": "anthropic", "api_key": "sk-b"},
            headers=auth_headers,
        )
        resp = await client.get("/api/providers", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2
        names = [p["name"] for p in data]
        assert "Provider A" in names
        assert "Provider B" in names

    async def test_get_provider(self, client, auth_headers):
        create = await client.post(
            "/api/providers",
            json={"name": "Test", "type": "openai", "api_key": "sk-test"},
            headers=auth_headers,
        )
        pid = create.json()["id"]
        resp = await client.get(f"/api/providers/{pid}", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["name"] == "Test"

    async def test_get_provider_not_found(self, client, auth_headers):
        resp = await client.get("/api/providers/nonexistent", headers=auth_headers)
        assert resp.status_code == 404

    async def test_update_provider(self, client, auth_headers):
        create = await client.post(
            "/api/providers",
            json={"name": "Old Name", "type": "openai", "api_key": "sk-old"},
            headers=auth_headers,
        )
        pid = create.json()["id"]
        resp = await client.put(
            f"/api/providers/{pid}",
            json={"name": "New Name", "api_key": "sk-new"},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["name"] == "New Name"

    async def test_delete_provider(self, client, auth_headers):
        create = await client.post(
            "/api/providers",
            json={"name": "ToDelete", "type": "openai", "api_key": "sk-x"},
            headers=auth_headers,
        )
        pid = create.json()["id"]
        resp = await client.delete(f"/api/providers/{pid}", headers=auth_headers)
        assert resp.status_code == 200
        # Verify it's gone
        resp = await client.get(f"/api/providers/{pid}", headers=auth_headers)
        assert resp.status_code == 404

    async def test_provider_without_key(self, client, auth_headers):
        """Local providers (Ollama) don't need a key."""
        resp = await client.post(
            "/api/providers",
            json={"name": "Ollama Local", "type": "ollama", "base_url": "http://localhost:11434"},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["has_key"] is False

    async def test_key_encrypted_at_rest(self, client, auth_headers, db_engine):
        """Verify the API key is encrypted in the DB, not stored in plaintext."""
        from sqlalchemy import select
        from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

        create = await client.post(
            "/api/providers",
            json={"name": "Encrypted", "type": "openai", "api_key": "sk-plaintext-secret"},
            headers=auth_headers,
        )
        pid = create.json()["id"]

        # Read directly from the DB
        factory = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)
        async with factory() as db:
            from agentos.models.provider import Provider

            result = await db.execute(select(Provider).where(Provider.id == pid))
            provider = result.scalar_one()
            assert provider.encrypted_key is not None
            assert "sk-plaintext-secret" not in provider.encrypted_key  # not in plaintext
            # Decrypt to verify
            from agentos.secret_store import decrypt

            assert decrypt(provider.encrypted_key) == "sk-plaintext-secret"
