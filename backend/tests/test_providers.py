"""Tests for provider management API (D39, D40)."""

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

pytest_asyncio_fixture = pytest_asyncio.fixture

from agentos.db import get_db
from agentos.main import app


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


class TestProviderCRUD:
    async def test_create_provider(self, client):
        resp = await client.post(
            "/api/providers",
            json={
                "name": "My OpenAI",
                "type": "openai",
                "api_key": "sk-test-key-12345",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "My OpenAI"
        assert data["type"] == "openai"
        assert data["has_key"] is True
        assert "api_key" not in data  # key never returned in plaintext

    async def test_list_providers(self, client):
        await client.post(
            "/api/providers",
            json={"name": "Provider A", "type": "openai", "api_key": "sk-a"},
        )
        await client.post(
            "/api/providers",
            json={"name": "Provider B", "type": "anthropic", "api_key": "sk-b"},
        )
        resp = await client.get("/api/providers")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2
        names = [p["name"] for p in data]
        assert "Provider A" in names
        assert "Provider B" in names

    async def test_get_provider(self, client):
        create = await client.post(
            "/api/providers",
            json={"name": "Test", "type": "openai", "api_key": "sk-test"},
        )
        pid = create.json()["id"]
        resp = await client.get(f"/api/providers/{pid}")
        assert resp.status_code == 200
        assert resp.json()["name"] == "Test"

    async def test_get_provider_not_found(self, client):
        resp = await client.get("/api/providers/nonexistent")
        assert resp.status_code == 404

    async def test_update_provider(self, client):
        create = await client.post(
            "/api/providers",
            json={"name": "Old Name", "type": "openai", "api_key": "sk-old"},
        )
        pid = create.json()["id"]
        resp = await client.put(
            f"/api/providers/{pid}",
            json={"name": "New Name", "api_key": "sk-new"},
        )
        assert resp.status_code == 200
        assert resp.json()["name"] == "New Name"

    async def test_delete_provider(self, client):
        create = await client.post(
            "/api/providers",
            json={"name": "ToDelete", "type": "openai", "api_key": "sk-x"},
        )
        pid = create.json()["id"]
        resp = await client.delete(f"/api/providers/{pid}")
        assert resp.status_code == 200
        # Verify it's gone
        resp = await client.get(f"/api/providers/{pid}")
        assert resp.status_code == 404

    async def test_provider_without_key(self, client):
        """Local providers (Ollama) don't need a key."""
        resp = await client.post(
            "/api/providers",
            json={"name": "Ollama Local", "type": "ollama", "base_url": "http://localhost:11434"},
        )
        assert resp.status_code == 200
        assert resp.json()["has_key"] is False

    async def test_key_encrypted_at_rest(self, client, db_engine):
        """Verify the API key is encrypted in the DB, not stored in plaintext."""
        from sqlalchemy import select
        from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

        create = await client.post(
            "/api/providers",
            json={"name": "Encrypted", "type": "openai", "api_key": "sk-plaintext-secret"},
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
