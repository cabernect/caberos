from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from agentos.capabilities.tools.knowledge import doc_inspect, doc_list, doc_search
from agentos.capabilities.tools.web import web_search
from agentos.config import settings
from agentos.knowledge.ingest import ingest_document, search_documents
from agentos.models.document import Document, DocumentChunk
from agentos.models.source import RunSource
from agentos.models.web_source import WebSource


@pytest.mark.asyncio
async def test_ingest_and_search_is_shared_across_agents(db, tmp_path: Path):
    root = tmp_path / "knowledge"
    root.mkdir()
    (root / "guide.md").write_text(
        "# Auth\n\nBearer tokens survive gateway restarts. LLM as verifier handles fine-grained checks.",
        encoding="utf-8",
    )

    document = await ingest_document(db, root / "guide.md", root)
    await db.commit()

    results = await search_documents(db, "Bearer tokens")
    operator_results = await search_documents(db, "LLM as verifier")

    assert document.status == "indexed"
    chunks = list((await db.execute(select(DocumentChunk))).scalars().all())
    assert len(chunks) == 1
    assert chunks[0].block_type == "paragraph"
    assert len(results) == 1
    assert len(operator_results) == 1
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
async def test_doc_list_returns_bounded_visible_metadata(db, tmp_path: Path):
    shared_root = tmp_path / "shared"
    private_root = tmp_path / "private"
    shared_root.mkdir()
    private_root.mkdir()
    (shared_root / "research.md").write_text("shared paper", encoding="utf-8")
    (private_root / "private.md").write_text("private notes", encoding="utf-8")
    (tmp_path / "other.md").write_text("other agent notes", encoding="utf-8")

    await ingest_document(db, shared_root / "research.md", shared_root)
    await ingest_document(db, private_root / "private.md", private_root, agent_id="agent-1")
    await ingest_document(db, tmp_path / "other.md", tmp_path, agent_id="agent-2")
    await db.commit()

    result = await doc_list({"limit": 10}, db=db, agent_id="agent-1")

    assert result["count"] == 2
    assert [document["display_name"] for document in result["documents"]] == [
        "private.md",
        "research.md",
    ]
    assert all("text" not in document for document in result["documents"])
    assert {document["scope"] for document in result["documents"]} == {"shared", "private"}
    assert result["documents"][1]["structure"]["sections"] == []


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
async def test_doc_search_persists_sources_for_run(db, tmp_path: Path):
    root = tmp_path / "knowledge"
    root.mkdir()
    (root / "guide.md").write_text("Gateway sessions persist across restarts.", encoding="utf-8")
    await ingest_document(db, root / "guide.md", root)
    await db.commit()

    result = await doc_search(
        {"query": "sessions", "limit": 5}, db=db, agent_id="agent-1", run_id="run-1"
    )
    await db.commit()

    assert result["count"] == 1
    sources = list((await db.execute(select(RunSource))).scalars().all())
    assert len(sources) == 1
    assert sources[0].excerpt == "Gateway sessions persist across restarts."


@pytest.mark.asyncio
async def test_web_search_persists_sources_for_run(db, monkeypatch):
    async def fake_to_thread(_func):
        return [
            {
                "title": "CaberOS",
                "href": "https://example.com/caberos",
                "body": "Agent OS documentation.",
            }
        ]

    monkeypatch.setattr("agentos.capabilities.tools.web.asyncio.to_thread", fake_to_thread)

    result = await web_search({"query": "CaberOS"}, db=db, run_id="run-1")
    await db.commit()

    assert result["count"] == 1
    sources = list((await db.execute(select(WebSource))).scalars().all())
    assert len(sources) == 1
    assert sources[0].url == "https://example.com/caberos"
    assert sources[0].title == "CaberOS"
    assert sources[0].excerpt == "Agent OS documentation."


@pytest.mark.asyncio
async def test_doc_inspect_renders_pdf_page_for_vision_model(db, tmp_path: Path, monkeypatch):
    from pypdf import PdfWriter

    root = tmp_path / "knowledge" / "shared"
    root.mkdir(parents=True)
    pdf_path = root / "paper.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=400, height=400)
    with pdf_path.open("wb") as file:
        writer.write(file)

    monkeypatch.setattr(settings, "knowledge_root", tmp_path / "knowledge")
    document = Document(
        id="doc-vision",
        source_path="paper.pdf",
        storage_path="paper.pdf",
        display_name="paper.pdf",
        mime_type="application/pdf",
        content_hash="a" * 64,
        size_bytes=pdf_path.stat().st_size,
        status="indexed",
    )
    db.add(document)
    await db.commit()

    result = await doc_inspect(
        {"document_id": document.id, "page_number": 1},
        db=db,
        agent_id="agent-1",
        supports_vision=True,
    )

    assert result["page_number"] == 1
    assert result["_model_content"][1]["type"] == "image_url"
    assert result["_model_content"][1]["image_url"]["url"].startswith("data:image/png;base64,")


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
