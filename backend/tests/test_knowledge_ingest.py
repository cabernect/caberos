from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from agentos.capabilities.tools.knowledge import doc_search
from agentos.knowledge.ingest import ingest_document, search_documents


@pytest.mark.asyncio
async def test_ingest_and_search_is_shared_across_agents(db, tmp_path: Path):
    root = tmp_path / "knowledge"
    root.mkdir()
    (root / "guide.md").write_text(
        "# Auth\n\nBearer tokens survive gateway restarts.", encoding="utf-8"
    )

    document = await ingest_document(db, root / "guide.md", root)
    await db.commit()

    results = await search_documents(db, "Bearer tokens")

    assert document.status == "indexed"
    assert len(results) == 1
    assert results[0]["document_id"] == document.id
    assert results[0]["heading_path"] == ["Auth"]


@pytest.mark.asyncio
async def test_changed_file_replaces_chunks_and_hash(db, tmp_path: Path):
    root = tmp_path / "knowledge"
    root.mkdir()
    path = root / "notes.txt"
    path.write_text("old phrase", encoding="utf-8")

    first = await ingest_document(db, path, root)
    await db.commit()
    first_hash = first.content_hash
    path.write_text("new phrase", encoding="utf-8")
    second = await ingest_document(db, path, root)
    await db.commit()

    assert first.id == second.id
    assert first_hash != second.content_hash
    assert await search_documents(db, "old phrase") == []
    assert len(await search_documents(db, "new phrase")) == 1


@pytest.mark.asyncio
async def test_doc_search_returns_shared_and_agent_knowledge(db, tmp_path: Path):
    shared_root = tmp_path / "shared"
    private_root = tmp_path / "private"
    shared_root.mkdir()
    private_root.mkdir()
    (shared_root / "shared.md").write_text("shared operating policy", encoding="utf-8")
    (private_root / "private.md").write_text("private project detail", encoding="utf-8")

    await ingest_document(db, shared_root / "shared.md", shared_root)
    await ingest_document(db, private_root / "private.md", private_root, agent_id="agent-1")
    await db.commit()

    result = await doc_search(
        {"query": "project", "limit": 10},
        db=db,
        agent_id="agent-1",
    )

    assert result["query"] == "project"
    assert result["count"] == 1
    assert result["results"][0]["agent_id"] == "agent-1"


@pytest.mark.asyncio
async def test_postgres_search_uses_tsvector_and_agent_scope():
    db = SimpleNamespace(
        get_bind=lambda: SimpleNamespace(dialect=SimpleNamespace(name="postgresql")),
        execute=AsyncMock(
            return_value=SimpleNamespace(
                fetchall=lambda: [
                    (
                        "chunk-1",
                        "doc-1",
                        None,
                        "shared excerpt",
                        "guide.md",
                        "guide.md",
                        '["Auth"]',
                        None,
                        None,
                        None,
                        0.9,
                    )
                ]
            )
        ),
    )

    results = await search_documents(db, "shared policy", agent_id="agent-1")

    assert results[0]["document_id"] == "doc-1"
    query = db.execute.await_args.args[0].text
    assert "search_vector" in query
    assert "d.agent_id IS NULL" in query
