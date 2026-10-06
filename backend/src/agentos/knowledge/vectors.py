"""Vector storage adapters — float32 BLOB packing + pluggable cosine search.

Two adapters behind one ``search()`` seam:

- ``sqlite-vec`` (default): ``vec_distance_cosine`` runs the exact scan in C
  over the ``chunk_embeddings`` BLOBs — scales to ~100k+ chunks.
- ``python`` (fallback): pure-Python cosine when the extension cannot load.
  Retrieval reports ``adapter=python`` as a degradation note.

The float32 little-endian BLOB layout is shared: sqlite-vec's float32 blob
format is identical to ``struct.pack("<{n}f", ...)``.
"""

from __future__ import annotations

import heapq
import math
import struct
from array import array
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

# NULL agent_id means the shared scope — *not* unscoped. Private documents
# must never leak into a shared-scope (operator) query.
_SCOPE_SQL = """
    (d.agent_id IS NULL OR d.agent_id = :agent_id)
"""

_CANDIDATE_SQL = f"""
    SELECT ce.chunk_id, ce.vector
    FROM chunk_embeddings ce
    JOIN document_chunks dc ON dc.id = ce.chunk_id
    JOIN documents d ON d.id = dc.document_id
    WHERE ce.generation_id = :generation_id
      AND dc.kind != 'parent'
      AND {_SCOPE_SQL}
"""


def pack_f32(vector: list[float]) -> bytes:
    return struct.pack(f"<{len(vector)}f", *vector)


def unpack_f32(blob: bytes) -> array:
    out = array("f")
    out.frombytes(blob)
    return out


def cosine_score(query: array, candidate: array) -> float:
    dot = sum(a * b for a, b in zip(query, candidate, strict=False))
    norm_q = math.sqrt(sum(a * a for a in query))
    norm_c = math.sqrt(sum(b * b for b in candidate))
    if norm_q == 0.0 or norm_c == 0.0:
        return 0.0
    return dot / (norm_q * norm_c)


async def sqlite_vec_available(db: AsyncSession) -> bool:
    """Load the sqlite-vec extension on this session's connection, if present."""
    try:
        import sqlite_vec
    except ImportError:
        return False
    try:
        connection = await db.connection()
        raw = await connection.get_raw_connection()
        driver = raw.driver_connection  # aiosqlite.Connection
        await driver.enable_load_extension(True)
        await driver.load_extension(sqlite_vec.loadable_path())
        await driver.enable_load_extension(False)
        await db.execute(text("SELECT vec_version()"))
    except Exception:
        return False
    return True


async def select_adapter(db: AsyncSession) -> str:
    """The adapter a new generation builds with — 'sqlite-vec' or 'python'."""
    if db.get_bind().dialect.name != "sqlite":
        return "none"
    return "sqlite-vec" if await sqlite_vec_available(db) else "python"


class PythonVectorAdapter:
    """Exact cosine scan in Python — bounded memory via a top-k heap."""

    name = "python"

    async def search(
        self,
        db: AsyncSession,
        generation_id: str,
        query_vector: bytes,
        agent_id: str | None,
        k: int,
    ) -> list[tuple[str, float]]:
        query = unpack_f32(query_vector)
        top: list[tuple[float, str]] = []
        scanned = 0
        stream = await db.stream(
            text(_CANDIDATE_SQL),
            {"generation_id": generation_id, "agent_id": agent_id},
        )
        async for row in stream:
            scanned += 1
            score = cosine_score(query, unpack_f32(row.vector))
            if len(top) < k:
                heapq.heappush(top, (score, row.chunk_id))
            elif score > top[0][0]:
                heapq.heapreplace(top, (score, row.chunk_id))
        return [(chunk_id, score) for score, chunk_id in sorted(top, reverse=True)]


class SqliteVecAdapter:
    """Exact cosine via sqlite-vec's vec_distance_cosine (C-speed scan)."""

    name = "sqlite-vec"

    async def search(
        self,
        db: AsyncSession,
        generation_id: str,
        query_vector: bytes,
        agent_id: str | None,
        k: int,
    ) -> list[tuple[str, float]]:
        # vec_* functions exist only where the extension was loaded — it is
        # per-connection, so ensure it on this session's connection. Loading is
        # idempotent; if it fails the caller degrades via EmbeddingUnavailable.
        if not await sqlite_vec_available(db):
            raise RuntimeError("sqlite-vec extension unavailable")
        result = await db.execute(
            text(
                f"""
                SELECT ce.chunk_id, 1.0 - vec_distance_cosine(ce.vector, :query) AS score
                FROM chunk_embeddings ce
                JOIN document_chunks dc ON dc.id = ce.chunk_id
                JOIN documents d ON d.id = dc.document_id
                WHERE ce.generation_id = :generation_id
                  AND dc.kind != 'parent'
                  AND {_SCOPE_SQL}
                ORDER BY vec_distance_cosine(ce.vector, :query) ASC
                LIMIT :k
                """
            ),
            {
                "generation_id": generation_id,
                "agent_id": agent_id,
                "query": query_vector,
                "k": k,
            },
        )
        return [(row[0], float(row[1])) for row in result.fetchall()]


def adapter_for(name: str) -> Any:
    """Instantiate the adapter stored on a generation row."""
    if name == "sqlite-vec":
        return SqliteVecAdapter()
    return PythonVectorAdapter()
