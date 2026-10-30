"""Document ingestion and shared SQLite full-text retrieval."""

import asyncio
import hashlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ..fts import fts5_match_query
from ..models.document import Document, DocumentChunk
from .chunker import ChunkingConfig, ChunkNode, chunk_blocks
from .extractors import extract_document


async def _chunking_config(db: AsyncSession) -> ChunkingConfig:
    """Chunk parameters from the active retrieval profile (corpus state)."""
    from ..models.knowledge_index import RetrievalProfile

    profile = await db.scalar(
        select(RetrievalProfile).where(RetrievalProfile.active.is_(True)).limit(1)
    )
    if profile is None:
        return ChunkingConfig()
    config = json.loads(profile.config_json or "{}")
    return ChunkingConfig(
        parent_tokens=int(config.get("parent_tokens", 450)),
        child_tokens=int(config.get("child_tokens", 120)),
        child_overlap=int(config.get("child_overlap", 20)),
        table_row_limit=int(config.get("table_row_limit", 150)),
    )


async def _write_chunk_nodes(
    db: AsyncSession,
    nodes: list[ChunkNode],
    document: Document,
    agent_id: str | None,
) -> list[DocumentChunk]:
    """Persist a ChunkNode tree in three batched phases — parents (one flush,
    ids needed for children), children (one bulk add), FTS rows (one
    executemany). A big document is ~3 round-trips, not ~4.5k.

    Returns the retrievable rows — children and standalone leaves — for the
    embed-at-ingest seam.
    """
    sequence = 0

    def _row(node: ChunkNode, parent_id: str | None) -> DocumentChunk:
        nonlocal sequence
        row = DocumentChunk(
            document_id=document.id,
            kind=node.kind,
            parent_id=parent_id,
            seq=sequence,
            text=node.text,
            heading_path=json.dumps(node.heading_path, ensure_ascii=False),
            page_number=node.page_number,
            source_location=node.source_location,
            block_type=node.block_type,
            token_count=node.token_count,
        )
        sequence += 1
        return row

    # Phase 1: parent rows need ids before children can reference them.
    tree: list[tuple[ChunkNode, DocumentChunk, list[tuple[ChunkNode, DocumentChunk]]]] = []
    for node in nodes:
        if node.kind == "parent":
            parent_row = _row(node, None)
            tree.append((node, parent_row, [(child, _row(child, None)) for child in node.children]))
        else:
            tree.append((node, _row(node, None), []))
    db.add_all([parent_row for _node, parent_row, _children in tree])
    await db.flush()

    # Phase 2: children (parent_id now resolvable) + standalone leaves.
    retrievable: list[tuple[DocumentChunk, ChunkNode]] = []
    child_rows: list[DocumentChunk] = []
    for node, parent_row, children in tree:
        for child, child_row in children:
            child_row.parent_id = parent_row.id
            child_rows.append(child_row)
            retrievable.append((child_row, child))
        if parent_row.kind != "parent":
            retrievable.append((parent_row, node))
    db.add_all(child_rows)
    await db.flush()

    # Phase 3: one executemany for every FTS row (children only). An empty
    # retrievable set (e.g. a scanned PDF) must skip the insert entirely —
    # executemany with no params raises a bind-parameter error.
    if not retrievable:
        return []
    await db.execute(
        text(
            "INSERT INTO document_chunks_fts "
            "(text, chunk_id, document_id, agent_id, source_path, storage_path, "
            "heading_path, page_number, sheet_name, source_location) "
            "VALUES (:content, :chunk_id, :document_id, :agent_id, :source_path, "
            ":storage_path, :heading_path, :page_number, :sheet_name, :source_location)"
        ),
        [
            {
                "content": row.text,
                "chunk_id": row.id,
                "document_id": document.id,
                "agent_id": agent_id,
                "source_path": document.source_path,
                "storage_path": document.storage_path,
                "heading_path": row.heading_path,
                "page_number": row.page_number,
                "sheet_name": node.sheet_name,
                "source_location": row.source_location,
            }
            for row, node in retrievable
        ],
    )
    return [row for row, _node in retrievable]


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
    from ..sandbox.workspace import resolve_within

    vault_root = vault_root.resolve()
    # Verify containment before touching the filesystem — source_file is a
    # caller-supplied path and must stay inside the vault.
    source_file = resolve_within(vault_root, source_file)
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

    # Extraction is CPU-bound (pypdf/openpyxl/docx) — never block the event
    # loop on a large document.
    extracted = await asyncio.to_thread(extract_document, source_file)
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

    config = await _chunking_config(db)
    nodes = chunk_blocks(extracted.blocks, config)
    retrievable = await _write_chunk_nodes(db, nodes, document, agent_id)

    # Commit the corpus write before embedding: a large document's embed
    # phase runs hundreds of batches, and holding this transaction through
    # it starves every other writer. The document is honest here — indexed
    # and lexically searchable, 'pending' when a generation expects vectors.
    from .indexing import embed_chunks_at_ingest, get_active_generation

    document.semantic_state = "pending" if await get_active_generation(db) else "na"
    await db.commit()

    document.semantic_state = await embed_chunks_at_ingest(db, document, retrievable)
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
    # AND-joined quoted terms — a document search should match all terms.
    fts_query = fts5_match_query(query, operator="AND")
    if db.get_bind().dialect.name == "postgresql":
        result = await db.execute(
            text(
                "SELECT c.id AS chunk_id, c.document_id, d.agent_id, c.text, "
                "d.source_path, d.storage_path, c.heading_path, c.page_number, "
                "NULL AS sheet_name, NULL AS source_location, c.block_type, "
                "ts_rank(c.search_vector, plainto_tsquery('simple', :query)) AS rank "
                "FROM document_chunks c JOIN documents d ON d.id = c.document_id "
                "WHERE c.search_vector @@ plainto_tsquery('simple', :query) "
                "AND (d.agent_id IS NULL OR d.agent_id = :agent_id) "
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
                "AND (fts.agent_id IS NULL OR fts.agent_id = :agent_id) "
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
