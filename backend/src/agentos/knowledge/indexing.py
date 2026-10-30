"""Index generation lifecycle — build / sweep / validate / activate / repair.

One sweep machine serves all three callers:

- rebuild end: sweep chunks created or changed after the build started
- rollback: sweep chunks missing from the superseded generation being revived
- repair: sweep chunks missing vectors in the *active* generation

A generation is never activated while it can still honestly cover the current
chunk set — whatever couldn't embed stays ``semantic_state='pending'`` on the
document so the operator can see the gap.
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.document import Document, DocumentChunk
from ..models.knowledge_index import (
    ChunkEmbedding,
    EmbeddingResource,
    IndexGeneration,
    RetrievalProfile,
)
from .embeddings import EmbeddingUnavailable, embed_texts
from .vectors import pack_f32, select_adapter

_RETRIEVABLE = "kind != 'parent'"
_EMBED_BATCH = 32
# Commit after this many embed batches (~256 vectors). A single uncommitted
# transaction holds the SQLite write lock for the entire build — every other
# write 503s and the 'building' row is invisible to /index. Committing per
# segment releases the lock between batches so concurrent work proceeds.
_COMMIT_EVERY_BATCHES = 8
# Same-process guard: the DB check alone races (two rebuilds can both pass
# before either commits its 'building' row). The lock closes that window;
# the DB check stays for cross-process honesty.
_REBUILD_LOCK = asyncio.Lock()


class RebuildInProgress(RuntimeError):
    """Raised when a second build is attempted while one is `building`."""


async def get_active_profile(db: AsyncSession) -> RetrievalProfile:
    """The single operator-facing profile; seeded lexical on first use."""
    profile = await db.scalar(
        select(RetrievalProfile).where(RetrievalProfile.active.is_(True)).limit(1)
    )
    if profile is not None:
        return profile
    profile = RetrievalProfile(
        name="default",
        revision=1,
        active=True,
        config_json=json.dumps(
            {
                "fusion": "lexical",
                "parent_tokens": 450,
                "child_tokens": 120,
                "child_overlap": 20,
                "rrf_k": 60,
                "max_parents": 4,
                "table_row_limit": 150,
            }
        ),
    )
    db.add(profile)
    await db.flush()
    return profile


async def get_active_generation(db: AsyncSession) -> IndexGeneration | None:
    return await db.scalar(
        select(IndexGeneration).where(IndexGeneration.status == "active").limit(1)
    )


async def _current_resource(db: AsyncSession) -> EmbeddingResource | None:
    return await db.scalar(
        select(EmbeddingResource).order_by(EmbeddingResource.created_at).limit(1)
    )


async def _missing_chunk_ids(db: AsyncSession, generation_id: str) -> list[str]:
    """Retrievable chunks with no vector row in this generation."""
    result = await db.execute(
        text(
            f"""
            SELECT dc.id FROM document_chunks dc
            WHERE dc.{_RETRIEVABLE}
              AND NOT EXISTS (
                SELECT 1 FROM chunk_embeddings ce
                WHERE ce.chunk_id = dc.id AND ce.generation_id = :generation_id
              )
            ORDER BY dc.document_id, dc.seq
            """
        ),
        {"generation_id": generation_id},
    )
    return [row[0] for row in result.fetchall()]


async def _embed_into_generation(
    db: AsyncSession,
    generation: IndexGeneration,
    resource: EmbeddingResource,
    chunk_ids: list[str],
    *,
    operation: str = "index",
) -> dict[str, int]:
    """Embed the given chunks into a generation; returns a fixed/failed count.

    ``stats_json`` accumulates onto the generation's existing totals — this
    function is also called for single-document ingest batches, which must
    not clobber a completed build's stats.
    """
    done = failed = 0
    stats = json.loads(generation.stats_json or "{}")
    base_embedded = int(stats.get("embedded", 0))
    base_failed = int(stats.get("failed", 0))
    base_total = int(stats.get("total", 0))
    for index, start in enumerate(range(0, len(chunk_ids), _EMBED_BATCH)):
        batch_ids = chunk_ids[start : start + _EMBED_BATCH]
        rows = (
            (await db.execute(select(DocumentChunk).where(DocumentChunk.id.in_(batch_ids))))
            .scalars()
            .all()
        )
        try:
            vectors = await embed_texts(
                db,
                resource,
                [row.text for row in rows],
                operation=operation,
                generation_id=generation.id,
            )
        except EmbeddingUnavailable:
            failed += len(rows)
        else:
            for row, vector in zip(rows, vectors, strict=False):
                db.add(
                    ChunkEmbedding(
                        chunk_id=row.id,
                        generation_id=generation.id,
                        vector=pack_f32(vector),
                        dims=len(vector),
                    )
                )
                done += 1
        generation.stats_json = json.dumps(
            {
                **stats,
                "embedded": base_embedded + done,
                "failed": base_failed + failed,
                "total": base_total + len(chunk_ids),
            }
        )
        await db.flush()
        if (index + 1) % _COMMIT_EVERY_BATCHES == 0:
            await db.commit()
    return {"fixed": done, "failed": failed}


async def _refresh_semantic_states(db: AsyncSession, generation_id: str) -> None:
    """Recompute documents.semantic_state against the active generation."""
    await db.execute(
        text(
            """
            UPDATE documents SET semantic_state = CASE
                WHEN NOT EXISTS (
                    SELECT 1 FROM document_chunks dc
                    WHERE dc.document_id = documents.id AND dc.kind != 'parent'
                ) THEN 'na'
                WHEN EXISTS (
                    SELECT 1 FROM document_chunks dc
                    WHERE dc.document_id = documents.id AND dc.kind != 'parent'
                      AND NOT EXISTS (
                        SELECT 1 FROM chunk_embeddings ce
                        WHERE ce.chunk_id = dc.id AND ce.generation_id = :generation_id
                      )
                ) THEN 'pending'
                ELSE 'embedded'
            END
            """
        ),
        {"generation_id": generation_id},
    )


async def embed_chunks_at_ingest(
    db: AsyncSession, document: Document, chunks: list[DocumentChunk]
) -> str:
    """Embed-at-ingest: cover new chunks in the active generation when the
    resource is healthy. Returns the document's semantic_state."""
    if not chunks:
        return "na"
    generation = await get_active_generation(db)
    if generation is None:
        return "na"
    # Lexical mode is embeddings-off: no provider call, no egress, no spend.
    # Chunks stay 'pending' so a later hybrid flip + repair fills the hole.
    profile = await get_active_profile(db)
    fusion = json.loads(profile.config_json or "{}").get("fusion", "lexical")
    if fusion != "hybrid":
        return "pending"
    resource = None
    if generation.embedding_resource_id:
        resource = await db.scalar(
            select(EmbeddingResource).where(
                EmbeddingResource.id == generation.embedding_resource_id
            )
        )
    if resource is None or resource.status != "ready":
        return "pending"
    result = await _embed_into_generation(
        db, generation, resource, [chunk.id for chunk in chunks], operation="ingest"
    )
    if result["failed"]:
        return "pending"
    return "embedded"


async def rebuild_index(db: AsyncSession) -> IndexGeneration:
    """Re-embed the canonical chunk set into a new generation, then atomically
    activate it. Rejects with RebuildInProgress when a build is running."""
    if _REBUILD_LOCK.locked():
        raise RebuildInProgress("an index rebuild is already running")
    async with _REBUILD_LOCK:
        building = await db.scalar(
            select(func.count(IndexGeneration.id)).where(IndexGeneration.status == "building")
        )
        if building:
            raise RebuildInProgress("an index rebuild is already running")

        profile = await get_active_profile(db)
        resource = await _current_resource(db)
        last = await db.scalar(select(func.max(IndexGeneration.revision)))
        generation = IndexGeneration(
            revision=(last or 0) + 1,
            profile_revision=profile.revision,
            profile_id=profile.id,
            embedding_resource_id=resource.id if resource else None,
            embedding_model=resource.model_name if resource else None,
            dimensions=resource.dimensions if resource else None,
            adapter=await select_adapter(db),
            status="building",
            stats_json="{}",
        )
        db.add(generation)
        # Commit the 'building' row immediately — it must be visible to
        # /index progress and to the concurrent-rebuild check, not hidden
        # inside a transaction that stays open for the whole build.
        await db.commit()

        try:
            # Sweep covers the entire current chunk set — including anything
            # ingested while an earlier scan was running (chunks are
            # canonical; the sweep always re-reads them, so mid-build
            # ingests are caught for free).
            chunk_ids = await _missing_chunk_ids(db, generation.id)
            if resource is not None and resource.status == "ready":
                await _embed_into_generation(db, generation, resource, chunk_ids)
            elif chunk_ids:
                generation.stats_json = json.dumps(
                    {
                        "embedded": 0,
                        "failed": len(chunk_ids),
                        "total": len(chunk_ids),
                        "reason": "embedding resource not ready",
                    }
                )

            await _activate(db, generation)
            await db.commit()
            # An "active" generation can still be degraded — resource down
            # or embed batches failed mid-build leaves unembedded chunks
            # that silently drop to lexical. Surface it (B34).
            stats = json.loads(generation.stats_json or "{}")
            failed = int(stats.get("failed", 0))
            total = int(stats.get("total", 0))
            if failed:
                reason = stats.get("reason") or "embedding calls failed"
                await _notify_index_degraded(
                    generation,
                    f"activated degraded — {total - failed}/{total} chunks embedded ({reason})",
                    title="Knowledge index degraded",
                )
        except Exception as error:
            # A failed build is a committed record, not a silent rollback —
            # partial vectors stay queryable for diagnosis and the row can
            # be deleted explicitly.
            await db.rollback()
            await db.refresh(generation)
            generation.status = "failed"
            generation.error = str(error)[:500]
            await db.commit()
            await _notify_index_degraded(generation, str(error))
            raise
        return generation


async def _activate(db: AsyncSession, generation: IndexGeneration) -> None:
    """Atomic flip: current active → superseded, this generation → active."""
    await db.execute(
        update(IndexGeneration)
        .where(IndexGeneration.status == "active")
        .values(status="superseded")
    )
    generation.status = "active"
    generation.activated_at = datetime.now(UTC)
    await db.flush()
    await _refresh_semantic_states(db, generation.id)
    await db.flush()


async def activate_generation(db: AsyncSession, generation_id: str) -> IndexGeneration:
    """Rollback: sweep + activate a superseded generation. If the resource is
    gone, the flip still happens and the pending gap is reported."""
    generation = await db.scalar(select(IndexGeneration).where(IndexGeneration.id == generation_id))
    if generation is None:
        raise ValueError("generation not found")
    if generation.status == "active":
        return generation
    if generation.status == "building":
        raise RebuildInProgress("a build is still running")

    missing = await _missing_chunk_ids(db, generation.id)
    resource = None
    if generation.embedding_resource_id:
        resource = await db.scalar(
            select(EmbeddingResource).where(
                EmbeddingResource.id == generation.embedding_resource_id
            )
        )
    if missing and resource is not None and resource.status == "ready":
        await _embed_into_generation(db, generation, resource, missing)
    await _activate(db, generation)
    if missing and (resource is None or resource.status != "ready"):
        await _notify_index_degraded(
            generation,
            f"activated with {len(missing)} chunks still unembedded (embedding resource not ready)",
            title="Knowledge index degraded",
        )
    return generation


async def repair_index(db: AsyncSession) -> dict[str, Any]:
    """Targeted sweep on the active generation — fill only the holes."""
    generation = await get_active_generation(db)
    if generation is None:
        return {"fixed": 0, "still_pending": 0, "reasons": ["no active generation"]}
    resource = None
    if generation.embedding_resource_id:
        resource = await db.scalar(
            select(EmbeddingResource).where(
                EmbeddingResource.id == generation.embedding_resource_id
            )
        )
    missing = await _missing_chunk_ids(db, generation.id)
    if not missing:
        return {"fixed": 0, "still_pending": 0, "reasons": []}
    if resource is None or resource.status != "ready":
        await _refresh_semantic_states(db, generation.id)
        return {
            "fixed": 0,
            "still_pending": len(missing),
            "reasons": ["embedding resource not ready"],
        }
    result = await _embed_into_generation(db, generation, resource, missing, operation="repair")
    await _refresh_semantic_states(db, generation.id)
    remaining = await _missing_chunk_ids(db, generation.id)
    return {
        "fixed": result["fixed"],
        "still_pending": len(remaining),
        "reasons": [] if not remaining else ["embedding calls failed"],
    }


async def _notify_index_degraded(
    generation: IndexGeneration, detail: str, *, title: str = "Knowledge index build failed"
) -> None:
    """Emit vault_index_degraded — a failed/degraded index build is async
    background work the operator can't otherwise see (W9)."""
    try:
        from ..db import async_session_factory
        from ..notifications import create_notification

        async with async_session_factory() as ndb:
            await create_notification(
                ndb,
                notification_type="vault_index_degraded",
                severity="warning",
                title=title,
                message=(
                    f"Index generation {generation.id[:8]}: {detail[:200]}. "
                    "Retrieval falls back to lexical search until a rebuild succeeds."
                ),
                action_path="/knowledge",
                entity_id=generation.id,
                entity_type="index_generation",
                event_id=f"vault_index_degraded:{generation.id}",
            )
            await ndb.commit()
    except Exception:
        import logging

        logging.getLogger(__name__).debug("vault_index_degraded emit failed", exc_info=True)


async def reconcile_stale_builds(db: AsyncSession) -> int:
    """Mark generations 'failed' that were 'building' when the process died.

    Called at startup — an in-flight build cannot outlive the process, so a
    committed 'building' row is stale by definition. Without this it would
    block every future rebuild with 409.
    """
    stale = (
        await db.scalars(select(IndexGeneration).where(IndexGeneration.status == "building"))
    ).all()
    for generation in stale:
        generation.status = "failed"
        generation.error = "Gateway restarted during build"
    await db.flush()
    for generation in stale:
        await _notify_index_degraded(generation, "Gateway restarted during build")
    return len(stale)


async def delete_generation(db: AsyncSession, generation_id: str) -> bool:
    """Drop a superseded/failed generation and its vectors (keep-all until
    the operator deletes — rollback never silently dies)."""
    generation = await db.scalar(select(IndexGeneration).where(IndexGeneration.id == generation_id))
    if generation is None or generation.status == "active":
        return False
    await db.execute(delete(ChunkEmbedding).where(ChunkEmbedding.generation_id == generation_id))
    await db.delete(generation)
    await db.flush()
    return True
