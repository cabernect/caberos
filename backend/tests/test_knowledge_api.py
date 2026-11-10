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
async def test_overview_search_covers_all_scopes_while_scope_search_isolates(client, db):
    from agentos.models.agent import Agent

    db.add(Agent(id="agent-1", name="Caber", enabled=True))
    await db.commit()

    shared = await client.post(
        "/api/knowledge/documents/upload",
        files={"file": ("guide.md", b"Bearer tokens are persisted.", "text/markdown")},
    )
    private = await client.post(
        "/api/knowledge/scopes/agent-1/documents/upload",
        files={"file": ("notes.md", b"Bearer tokens rotate hourly.", "text/markdown")},
    )
    assert shared.status_code == 200
    assert private.status_code == 200

    overview = await client.post("/api/knowledge/search", json={"query": "Bearer tokens"})
    assert overview.status_code == 200
    by_doc = {r["document_id"]: r for r in overview.json()["results"]}
    assert by_doc[shared.json()["id"]]["agent_id"] is None
    assert by_doc[private.json()["id"]]["agent_id"] == "agent-1"

    scoped = await client.post(
        "/api/knowledge/scopes/shared/search", json={"query": "Bearer tokens"}
    )
    assert [r["document_id"] for r in scoped.json()["results"]] == [shared.json()["id"]]


@pytest.mark.asyncio
async def test_document_chunks_inspection_paging_and_scope(client, db):
    """Chunk inspection returns bounded items, honors parent branches and
    cursors, and never leaks across scopes."""
    from agentos.models.agent import Agent

    db.add(Agent(id="agent-1", name="Caber", enabled=True))
    await db.commit()

    up = await client.post(
        "/api/knowledge/scopes/shared/documents/upload",
        files={
            "file": (
                "guide.md",
                b"# A\n\nFirst section text.\n\n# B\n\nSecond section text.",
                "text/markdown",
            )
        },
    )
    assert up.status_code == 200
    doc = up.json()

    resp = await client.get(f"/api/knowledge/scopes/shared/documents/{doc['id']}/chunks")
    assert resp.status_code == 200
    body = resp.json()
    assert body["document_id"] == doc["id"]
    assert body["status"] == "indexed"
    assert body["chunk_count"] == len(body["items"])
    assert all(len(i["preview"]) <= body["preview_chars"] for i in body["items"])
    # Child rows with no parent legitimately surface at the top level —
    # only children *with* a parent are hidden inside branches.
    assert {i["kind"] for i in body["items"]} <= {"parent", "chunk", "child"}
    assert all(i["parent_id"] is None for i in body["items"])

    # Lazy branch: parents expand to children; foreign parents 404.
    parent = next((i for i in body["items"] if i["has_children"]), None)
    if parent:
        branch = await client.get(
            f"/api/knowledge/scopes/shared/documents/{doc['id']}/chunks",
            params={"parent_id": parent["id"]},
        )
        assert branch.status_code == 200
        children = branch.json()["items"]
        assert children and all(c["parent_id"] == parent["id"] for c in children)

        missing = await client.get(
            f"/api/knowledge/scopes/shared/documents/{doc['id']}/chunks",
            params={"parent_id": "not-a-chunk"},
        )
        assert missing.status_code == 404

    # Paging: limit=1 walks the corpus without gaps or dupes.
    seen, cursor = [], None
    while True:
        params = {"limit": 1}
        if cursor:
            params["cursor"] = cursor
        page = await client.get(
            f"/api/knowledge/scopes/shared/documents/{doc['id']}/chunks",
            params=params,
        )
        assert page.status_code == 200
        data = page.json()
        seen.extend(i["id"] for i in data["items"])
        cursor = data["next_cursor"]
        if not cursor:
            break
    assert len(seen) == len(set(seen)) == body["chunk_count"]

    # Stale cursor after corpus mutation → 409, never mixed corpora.
    await client.post(f"/api/knowledge/scopes/shared/documents/{doc['id']}/reindex")
    stale = await client.get(
        f"/api/knowledge/scopes/shared/documents/{doc['id']}/chunks",
        params={"cursor": "bogus-version:0"},
    )
    assert stale.status_code == 409

    # Private docs are invisible from the shared scope.
    private = await client.post(
        "/api/knowledge/scopes/agent-1/documents/upload",
        files={"file": ("notes.md", b"private corpus text", "text/markdown")},
    )
    cross = await client.get(
        f"/api/knowledge/scopes/shared/documents/{private.json()['id']}/chunks"
    )
    assert cross.status_code == 404


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
