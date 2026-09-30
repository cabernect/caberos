"""Retrieval pipeline — lexical + semantic candidates, RRF fusion, bounded
parent expansion, citations, and an inspectable trace.

Sole seam used by ``doc_search`` (compact trace) and the operator search API
(full trace). Degradation notes always ride along so the model never
overstates semantic coverage.
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ..fts import fts5_match_query
from ..models.document import Document, DocumentChunk
from ..models.knowledge_index import EmbeddingResource
from .embeddings import EmbeddingUnavailable, embed_texts
from .indexing import get_active_generation, get_active_profile
from .vectors import adapter_for, pack_f32

_SEMANTIC_K = 50  # top semantic candidates entering fusion
_LEXICAL_K = 50


async def _lexical_candidates(
    db: AsyncSession, query: str, agent_id: str | None, k: int
) -> list[tuple[str, float]]:
    """FTS5 rank over retrievable units (children + legacy flat chunks)."""
    fts_query = fts5_match_query(query, operator="AND")
    if not fts_query:
        return []
    if db.get_bind().dialect.name == "postgresql":
        result = await db.execute(
            text(
                "SELECT c.id, ts_rank(c.search_vector, plainto_tsquery('simple', :query)) "
                "FROM document_chunks c JOIN documents d ON d.id = c.document_id "
                "WHERE c.search_vector @@ plainto_tsquery('simple', :query) "
                "AND c.kind != 'parent' "
                "AND (:agent_id IS NULL OR d.agent_id IS NULL OR d.agent_id = :agent_id) "
                "ORDER BY 2 DESC LIMIT :k"
            ),
            {"query": " ".join(query.split()), "agent_id": agent_id, "k": k},
        )
    else:
        result = await db.execute(
            text(
                "SELECT fts.chunk_id, rank "
                "FROM document_chunks_fts fts "
                "JOIN document_chunks dc ON dc.id = fts.chunk_id "
                "WHERE document_chunks_fts MATCH :query "
                "AND dc.kind != 'parent' "
                "AND (:agent_id IS NULL OR fts.agent_id IS NULL OR fts.agent_id = :agent_id) "
                "ORDER BY rank LIMIT :k"
            ),
            {"query": fts_query, "agent_id": agent_id, "k": k},
        )
    return [(row[0], float(row[1])) for row in result.fetchall()]


def _rrf_fuse(
    lexical: list[tuple[str, float]],
    semantic: list[tuple[str, float]],
    rrf_k: int,
) -> list[str]:
    """Reciprocal-rank fusion — order-only, no score calibration."""
    scores: dict[str, float] = {}
    for rank, (chunk_id, _score) in enumerate(lexical, start=1):
        scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (rrf_k + rank)
    for rank, (chunk_id, _score) in enumerate(semantic, start=1):
        scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (rrf_k + rank)
    return [
        chunk_id for chunk_id, _ in sorted(scores.items(), key=lambda item: item[1], reverse=True)
    ]


async def retrieve(
    db: AsyncSession,
    query: str,
    limit: int = 5,
    agent_id: str | None = None,
    include_trace: bool = False,
) -> dict[str, Any]:
    """Run the full retrieval pipeline; always returns a trace."""
    profile = await get_active_profile(db)
    config = json.loads(profile.config_json or "{}")
    fusion = config.get("fusion", "lexical")
    rrf_k = int(config.get("rrf_k", 60))
    max_parents = int(config.get("max_parents", 4))
    parent_tokens = int(config.get("parent_tokens", 450))
    limit = max(1, min(limit, 20))

    degraded: list[str] = []
    lexical = await _lexical_candidates(db, query, agent_id, _LEXICAL_K)

    semantic: list[tuple[str, float]] = []
    semantic_scanned = 0
    adapter_name = "none"
    if fusion == "hybrid":
        generation = await get_active_generation(db)
        if generation is None:
            degraded.append("no active index generation; lexical only")
        elif not generation.embedding_resource_id:
            degraded.append("index generation has no embedding resource; lexical only")
        else:
            resource = await db.scalar(
                select(EmbeddingResource).where(
                    EmbeddingResource.id == generation.embedding_resource_id
                )
            )
            adapter_name = generation.adapter
            if generation.adapter == "python":
                degraded.append("adapter=python (sqlite-vec unavailable); slower scan")
            if db.get_bind().dialect.name != "sqlite":
                degraded.append("vector adapter unavailable on this backend; lexical only")
            elif resource is None or resource.status != "ready":
                degraded.append("embedding resource not ready; lexical only")
            else:
                try:
                    vectors = await embed_texts(db, resource, [query])
                    if vectors:
                        semantic = await adapter_for(generation.adapter).search(
                            db, generation.id, pack_f32(vectors[0]), agent_id, _SEMANTIC_K
                        )
                        semantic_scanned = len(semantic)
                except EmbeddingUnavailable as error:
                    degraded.append(f"semantic search failed ({error}); lexical only")
                except Exception as error:  # adapter/driver failure — never lose the answer
                    degraded.append(f"vector search failed ({error}); lexical only")

    fused = _rrf_fuse(lexical, semantic, rrf_k)
    selected_ids = fused[:limit]

    results: list[dict[str, Any]] = []
    if selected_ids:
        chunk_rows = {
            row.id: row
            for row in (
                await db.execute(select(DocumentChunk).where(DocumentChunk.id.in_(selected_ids)))
            )
            .scalars()
            .all()
        }
        doc_ids = {row.document_id for row in chunk_rows.values()}
        documents = {
            doc.id: doc
            for doc in (await db.execute(select(Document).where(Document.id.in_(doc_ids))))
            .scalars()
            .all()
        }
        parent_ids = {row.parent_id for row in chunk_rows.values() if row.parent_id}
        parents = (
            {
                row.id: row
                for row in (
                    await db.execute(select(DocumentChunk).where(DocumentChunk.id.in_(parent_ids)))
                )
                .scalars()
                .all()
            }
            if parent_ids
            else {}
        )

        expanded_parents: set[str] = set()
        for chunk_id in selected_ids:
            child = chunk_rows.get(chunk_id)
            document = documents.get(child.document_id) if child else None
            if child is None or document is None:
                continue
            parent = parents.get(child.parent_id) if child.parent_id else None
            expanded = False
            text_out = child.text
            if (
                parent is not None
                and len(expanded_parents) < max_parents
                and parent.id not in expanded_parents
            ):
                expanded_parents.add(parent.id)
                text_out = parent.text  # chunker already bounds to parent_tokens
                expanded = True
            elif parent is not None and parent.id in expanded_parents:
                expanded = True
                text_out = parent.text
            results.append(
                {
                    "chunk_id": child.id,
                    "document_id": document.id,
                    "agent_id": document.agent_id,
                    "content_hash": document.content_hash,
                    "text": text_out,
                    "matched_text": child.text,
                    "expanded": expanded,
                    "source_path": document.source_path,
                    "storage_path": document.storage_path,
                    "heading_path": json.loads(child.heading_path or "[]"),
                    "page_number": child.page_number,
                    "source_location": child.source_location,
                    "sheet_name": (
                        child.source_location.split("!")[0]
                        if child.block_type == "sheet" and "!" in (child.source_location or "")
                        else None
                    ),
                    "block_type": child.block_type,
                    "kind": child.kind,
                }
            )

    trace: dict[str, Any] = {
        "fusion": fusion,
        "lexical_hits": len(lexical),
        "semantic_hits": len(semantic),
        "expanded": sum(1 for r in results if r["expanded"]),
        "degraded": degraded,
    }
    if include_trace:
        trace.update(
            {
                "normalized_query": fts5_match_query(query, operator="AND"),
                "adapter": adapter_name,
                "semantic_scanned": semantic_scanned,
                "rrf_k": rrf_k,
                "max_parents": max_parents,
                "parent_tokens": parent_tokens,
                "profile_revision": profile.revision,
                "selected": [r["chunk_id"] for r in results],
            }
        )
    return {"query": query, "results": results, "count": len(results), "trace": trace}
