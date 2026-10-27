"""Tests for provider management API (D39, D40)."""

import json
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

    async def test_validate_model_does_not_expose_provider_exception(
        self, client, auth_headers, monkeypatch, caplog
    ):
        """Provider validation returns guidance while keeping raw errors in logs."""
        create = await client.post(
            "/api/providers",
            json={"name": "Validation Provider", "type": "openai", "api_key": "sk-test"},
            headers=auth_headers,
        )
        provider_id = create.json()["id"]
        raw_error = "provider-internal-detail /srv/private/config"

        async def fail_validation(_adapter, _provider_id, _model_name):
            raise RuntimeError(raw_error)

        monkeypatch.setattr(
            "agentos.harness.litellm_adapter.LiteLLMAdapter.validate_model",
            fail_validation,
        )

        with caplog.at_level("ERROR", logger="agentos.api.providers"):
            response = await client.post(
                f"/api/providers/{provider_id}/validate",
                json={"model_name": "test-model"},
                headers=auth_headers,
            )

        assert response.status_code == 200
        assert response.json() == {
            "valid": False,
            "error": "The provider returned an unexpected error. Check the gateway logs.",
        }
        assert raw_error not in response.text
        assert raw_error in caplog.text

        notifications = await client.get("/api/notifications", headers=auth_headers)
        assert notifications.status_code == 200
        notification = notifications.json()[0]
        assert notification["message"] == response.json()["error"]
        assert raw_error not in notification["message"]

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


class TestProviderCredentials:
    """Per-type extra credentials (azure api_version, bedrock aws_*) —
    encrypted at rest, key names only in API responses, merged into
    LiteLLM kwargs via the adapter's extras path."""

    async def test_create_with_credentials(self, client, auth_headers):
        resp = await client.post(
            "/api/providers",
            json={
                "name": "Bedrock",
                "type": "bedrock",
                "credentials": {
                    "aws_access_key_id": "AKIAEXAMPLE",
                    "aws_secret_access_key": "supersecret",
                    "aws_region_name": "us-east-1",
                },
            },
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert sorted(data["credential_fields"]) == [
            "aws_access_key_id",
            "aws_region_name",
            "aws_secret_access_key",
        ]
        # Values never leave the API — names only.
        assert "AKIAEXAMPLE" not in resp.text
        assert "supersecret" not in resp.text
        assert "credentials" not in data

    async def test_credentials_encrypted_at_rest(self, client, auth_headers, db_engine):
        from sqlalchemy import select
        from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

        from agentos.models.provider import Provider
        from agentos.secret_store import decrypt

        create = await client.post(
            "/api/providers",
            json={
                "name": "Azure",
                "type": "azure",
                "api_key": "azure-key",
                "base_url": "https://res.openai.azure.com/",
                "credentials": {"api_version": "2024-10-21"},
            },
            headers=auth_headers,
        )
        pid = create.json()["id"]
        factory = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)
        async with factory() as db:
            provider = (await db.execute(select(Provider).where(Provider.id == pid))).scalar_one()
            assert provider.encrypted_credentials is not None
            assert "2024-10-21" not in provider.encrypted_credentials
            assert json.loads(decrypt(provider.encrypted_credentials)) == {
                "api_version": "2024-10-21"
            }
            # Plaintext extra_params stays separate and empty.
            assert json.loads(provider.extra_params) == {}

    async def test_update_credentials_merge_semantics(self, client, auth_headers, monkeypatch):
        # The provider-refresh background task shares the single StaticPool
        # connection in tests and its rollback swallows the endpoint's commit.
        # Refresh scheduling isn't the behavior under test here.
        monkeypatch.setattr(
            "agentos.providers.model_catalog.schedule_provider_refresh",
            lambda *a, **k: None,
        )
        create = await client.post(
            "/api/providers",
            json={
                "name": "Bedrock",
                "type": "bedrock",
                "credentials": {
                    "aws_access_key_id": "AKIA1",
                    "aws_secret_access_key": "secret1",
                    "aws_region_name": "us-east-1",
                },
            },
            headers=auth_headers,
        )
        pid = create.json()["id"]
        # Update one key, delete another, leave the third untouched.
        resp = await client.put(
            f"/api/providers/{pid}",
            json={
                "credentials": {
                    "aws_secret_access_key": "secret2",
                    "aws_region_name": "",
                }
            },
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert sorted(resp.json()["credential_fields"]) == [
            "aws_access_key_id",
            "aws_secret_access_key",
        ]

    async def test_credentials_reach_adapter_extras(self, client, auth_headers, db_engine):
        """Decrypted credentials fold into extra_params so every LiteLLM
        call site (chat, responses, probes, aux summaries) receives them."""
        from agentos.harness.litellm_adapter import LiteLLMAdapter

        create = await client.post(
            "/api/providers",
            json={
                "name": "Bedrock",
                "type": "bedrock",
                "credentials": {
                    "aws_access_key_id": "AKIAEXAMPLE",
                    "aws_region_name": "eu-west-1",
                },
                # Explicit extra_params win over same-named credentials.
                "extra_params": {"aws_region_name": "us-west-2"},
            },
            headers=auth_headers,
        )
        pid = create.json()["id"]
        from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

        factory = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)
        async with factory() as db:
            adapter = LiteLLMAdapter(db)
            config = await adapter._load_provider(pid)
            assert config["extra_params"]["aws_access_key_id"] == "AKIAEXAMPLE"
            assert config["extra_params"]["aws_region_name"] == "us-west-2"


class TestCatalogModels:
    async def test_catalog_models_default_section(self, client, auth_headers):
        """Alias providers get a default catalog section for the picker."""
        create = await client.post(
            "/api/providers",
            json={"name": "Azure", "type": "azure"},
            headers=auth_headers,
        )
        pid = create.json()["id"]
        resp = await client.get(f"/api/providers/{pid}/catalog-models", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["catalog_provider_id"] == "azure"
        assert any(p["id"] == "azure" for p in data["providers"])
        ids = {m["id"] for m in data["models"]}
        assert "gpt-4o-mini" in ids
        mini = next(m for m in data["models"] if m["id"] == "gpt-4o-mini")
        assert mini["context_window_tokens"] == 128000

    async def test_catalog_models_explicit_section(self, client, auth_headers):
        create = await client.post(
            "/api/providers",
            json={"name": "Bedrock", "type": "bedrock"},
            headers=auth_headers,
        )
        pid = create.json()["id"]
        resp = await client.get(
            f"/api/providers/{pid}/catalog-models",
            params={"catalog_provider": "azure"},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["catalog_provider_id"] == "azure"

    async def test_declared_mapping_resolves_metadata(self, client, auth_headers, monkeypatch):
        """User-declared catalog mapping resolves context for alias models."""
        # The refresh task is not under test — keep it out of this session's
        # shared StaticPool connection. Patched at the source module since the
        # API imports it lazily per call.
        from agentos.providers import model_catalog

        monkeypatch.setattr(model_catalog, "schedule_provider_refresh", lambda pid: None)

        create = await client.post(
            "/api/providers",
            json={"name": "Azure", "type": "azure"},
            headers=auth_headers,
        )
        pid = create.json()["id"]
        add = await client.post(
            f"/api/providers/{pid}/models",
            json={"model_name": "gpt-4o-mini"},
            headers=auth_headers,
        )
        assert add.status_code == 200

        models = await client.get(f"/api/providers/{pid}/models", headers=auth_headers)
        offering = next(m for m in models.json()["models"] if m["name"] == "gpt-4o-mini")
        assert offering["context_window_tokens"] is None
        assert offering["catalog_mapping_explicit"] is False

        put = await client.put(
            f"/api/providers/{pid}/models/gpt-4o-mini/metadata",
            json={
                "fields": {},
                "catalog_provider_id": "azure",
                "catalog_model_id": "gpt-4o-mini",
            },
            headers=auth_headers,
        )
        assert put.status_code == 200

        models = await client.get(f"/api/providers/{pid}/models", headers=auth_headers)
        offering = next(m for m in models.json()["models"] if m["name"] == "gpt-4o-mini")
        assert offering["context_window_tokens"] == 128000
        assert offering["catalog_mapping_explicit"] is True
        assert offering["catalog_provider_id"] == "azure"
        assert offering["catalog_model_id"] == "gpt-4o-mini"
        prov = offering.get("provenance") or {}
        ctx_prov = prov.get("context_window_tokens") or {}
        assert ctx_prov.get("value") == 128000
        assert ctx_prov.get("source") == "models_dev"

        clear = await client.put(
            f"/api/providers/{pid}/models/gpt-4o-mini/metadata",
            json={"fields": {}, "clear_catalog_mapping": True},
            headers=auth_headers,
        )
        assert clear.status_code == 200
        models = await client.get(f"/api/providers/{pid}/models", headers=auth_headers)
        offering = next(m for m in models.json()["models"] if m["name"] == "gpt-4o-mini")
        assert offering["context_window_tokens"] is None
        assert offering["catalog_mapping_explicit"] is False
