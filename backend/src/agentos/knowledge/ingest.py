"""Document ingestion and shared SQLite full-text retrieval."""

import hashlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.document import Document, DocumentChunk
from .chunker import chunk_extracted_blocks
from .extractors import extract_document


def _content_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


async def ingest_document(
    db: AsyncSession,
    source_file: Path,
    vault_root: Path,
    source_path: str | None = None,
    agent_id: str | None = None,
) -> Document:
    """Extract and index one file in the shared Knowledge Vault."""
    source_file = source_file.resolve()
    vault_root = vault_root.resolve()
    if not source_file.is_file():
        raise ValueError(f"Document does not exist: {source_file.name}")
    logical_path = source_path or source_file.name
    content_hash = _content_hash(source_file)
    result = await db.execute(
        select(Document).where(
            Document.agent_id == agent_id,
            Document.source_path == logical_path,
        )
    )
    document = result.scalar_one_or_none()
    if document is None:
        document = Document(
            agent_id=agent_id,
            source_path=logical_path,
            storage_path=str(source_file.relative_to(vault_root)),
            display_name=source_file.name,
            mime_type="application/octet-stream",
            content_hash=content_hash,
            size_bytes=source_file.stat().st_size,
            status="pending",
        )
        db.add(document)
        await db.flush()
    elif document.content_hash == content_hash and document.status == "indexed":
        return document

    extracted = extract_document(source_file)
    await db.execute(
        text("DELETE FROM document_chunks_fts WHERE document_id = :document_id"),
        {"document_id": document.id},
    )
    await db.execute(delete(DocumentChunk).where(DocumentChunk.document_id == document.id))

    document.display_name = source_file.name
    document.storage_path = str(source_file.relative_to(vault_root))
    document.mime_type = extracted.mime_type
    document.content_hash = content_hash
    document.size_bytes = source_file.stat().st_size
    document.structure_json = json.dumps(extracted.structure, ensure_ascii=False)
    document.status = "indexed"
    document.error = None
    document.indexed_at = datetime.now(UTC)

    chunks = chunk_extracted_blocks(extracted.blocks)
    for sequence, chunk in enumerate(chunks):
        row = DocumentChunk(
            document_id=document.id,
            seq=sequence,
            text=chunk.text,
            heading_path=json.dumps(chunk.heading_path, ensure_ascii=False),
            page_number=chunk.page_number,
            source_location=chunk.source_location,
            block_type=chunk.block_type,
            token_count=chunk.token_count,
        )
        db.add(row)
        await db.flush()
        await db.execute(
            text(
                "INSERT INTO document_chunks_fts "
                "(text, chunk_id, document_id, agent_id, source_path, storage_path, "
                "heading_path, page_number, sheet_name, source_location) "
                "VALUES (:content, :chunk_id, :document_id, :agent_id, :source_path, "
                ":storage_path, :heading_path, :page_number, :sheet_name, :source_location)"
            ),
            {
                "content": chunk.text,
                "chunk_id": row.id,
                "document_id": document.id,
                "agent_id": agent_id,
                "source_path": logical_path,
                "storage_path": document.storage_path,
                "heading_path": row.heading_path,
                "page_number": chunk.page_number,
                "sheet_name": chunk.sheet_name,
                "source_location": chunk.source_location,
            },
        )
    await db.flush()
    return document


async def list_documents(db: AsyncSession, agent_id: str | None = None) -> list[Document]:
    """List documents in the shared or agent-specific Vault scope."""
    statement = select(Document).order_by(Document.display_name)
    if agent_id is None:
        statement = statement.where(Document.agent_id.is_(None))
    else:
        statement = statement.where(Document.agent_id == agent_id)
    result = await db.execute(statement)
    return list(result.scalars().all())


async def delete_document(db: AsyncSession, document_id: str) -> bool:
    """Delete a document and its searchable chunks."""
    result = await db.execute(select(Document).where(Document.id == document_id))
    document = result.scalar_one_or_none()
    if document is None:
        return False
    await db.execute(
        text("DELETE FROM document_chunks_fts WHERE document_id = :document_id"),
        {"document_id": document_id},
    )
    await db.execute(delete(DocumentChunk).where(DocumentChunk.document_id == document_id))
    await db.delete(document)
    await db.flush()
    return True


async def search_documents(
    db: AsyncSession,
    query: str,
    limit: int = 5,
    agent_id: str | None = None,
) -> list[dict[str, Any]]:
    """Search shared and agent-private Knowledge Vault documents."""
    terms = re.findall(r"[\w-]+", query)
    if not terms:
        return []
    limit = max(1, min(limit, 20))
    fts_query = " ".join('"' + term.replace('"', '""') + '"' for term in terms)
    if db.get_bind().dialect.name == "postgresql":
        result = await db.execute(
            text(
                "SELECT c.id AS chunk_id, c.document_id, d.agent_id, c.text, "
                "d.source_path, d.storage_path, c.heading_path, c.page_number, "
                "NULL AS sheet_name, NULL AS source_location, c.block_type, "
                "ts_rank(c.search_vector, plainto_tsquery('simple', :query)) AS rank "
                "FROM document_chunks c JOIN documents d ON d.id = c.document_id "
                "WHERE c.search_vector @@ plainto_tsquery('simple', :query) "
                "AND (:agent_id IS NULL OR d.agent_id IS NULL OR d.agent_id = :agent_id) "
                "ORDER BY rank DESC LIMIT :limit"
            ),
            {"query": " ".join(terms), "agent_id": agent_id, "limit": limit},
        )
    else:
        result = await db.execute(
            text(
                "SELECT fts.chunk_id, fts.document_id, fts.agent_id, fts.text, fts.source_path, "
                "fts.storage_path, fts.heading_path, fts.page_number, fts.sheet_name, "
                "fts.source_location, dc.block_type "
                "FROM document_chunks_fts fts "
                "JOIN document_chunks dc ON dc.id = fts.chunk_id "
                "WHERE document_chunks_fts MATCH :query "
                "AND (:agent_id IS NULL OR fts.agent_id IS NULL OR fts.agent_id = :agent_id) "
                "ORDER BY rank LIMIT :limit"
            ),
            {"query": fts_query, "agent_id": agent_id, "limit": limit},
        )
    return [
        {
            "chunk_id": row[0],
            "document_id": row[1],
            "agent_id": row[2],
            "text": row[3],
            "source_path": row[4],
            "storage_path": row[5],
            "heading_path": json.loads(row[6]) if row[6] else [],
            "page_number": row[7],
            "sheet_name": row[8],
            "source_location": row[9],
            "block_type": row[10],
        }
        for row in result.fetchall()
    ]
