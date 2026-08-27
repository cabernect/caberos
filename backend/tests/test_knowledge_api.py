from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from agentos.auth import require_operator
from agentos.config import settings
from agentos.db import get_db
from agentos.main import app
from agentos.models.operator import Operator


@pytest.fixture
async def client(db, monkeypatch, tmp_path: Path):
    async def fake_operator():
        return Operator(id="test-operator", username="test", password_hash="x")

    app.dependency_overrides[require_operator] = fake_operator
    app.dependency_overrides[get_db] = lambda: db
    monkeypatch.setattr(settings, "knowledge_root", tmp_path / "knowledge")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as http:
        yield http
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_knowledge_api_uploads_lists_searches_and_deletes(client):
    response = await client.post(
        "/api/knowledge/documents/upload",
        files={"file": ("guide.md", b"# Auth\n\nBearer tokens are persisted.", "text/markdown")},
    )

    assert response.status_code == 200
    document = response.json()
    assert document["status"] == "indexed"
    assert document["storage_path"].endswith(".md")
    assert document["storage_path"] != "guide.md"
    stored_file = settings.knowledge_root / "shared" / document["storage_path"]
    assert stored_file.is_file()

    listed = await client.get("/api/knowledge/documents")
    assert [item["id"] for item in listed.json()["documents"]] == [document["id"]]

    searched = await client.post("/api/knowledge/search", json={"query": "Bearer tokens"})
    assert searched.status_code == 200
    assert searched.json()["results"][0]["document_id"] == document["id"]

    deleted = await client.delete(f"/api/knowledge/documents/{document['id']}")
    assert deleted.status_code == 204
    assert not stored_file.exists()
    assert (await client.get("/api/knowledge/documents")).json()["documents"] == []


@pytest.mark.asyncio
async def test_knowledge_api_rejects_unknown_scope(client):
    response = await client.get("/api/knowledge/scopes/not-an-agent/documents")

    assert response.status_code == 404
    assert response.json()["detail"] == "Knowledge scope not found"


@pytest.mark.asyncio
async def test_knowledge_api_rejects_unsafe_upload_name(client):
    response = await client.post(
        "/api/knowledge/documents/upload",
        files={"file": ("../secrets.txt", b"secret", "text/plain")},
    )

    assert response.status_code == 400
