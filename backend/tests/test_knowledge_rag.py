"""RAG v2 — parent/child chunking, index lifecycle, fused retrieval, egress."""

import json
from pathlib import Path

import pytest
from sqlalchemy import func, select, text

from agentos.knowledge.chunker import ChunkingConfig, chunk_blocks
from agentos.knowledge.embeddings import (
    EmbeddingUnavailable,
    embed_texts,
    provider_is_local,
)
from agentos.knowledge.extractors import ExtractedBlock
from agentos.knowledge.indexing import (
    RebuildInProgress,
    activate_generation,
    delete_generation,
    get_active_generation,
    rebuild_index,
    repair_index,
)
from agentos.knowledge.ingest import ingest_document
from agentos.knowledge.retrieval import retrieve
from agentos.models.document import DocumentChunk
from agentos.models.knowledge_index import (
    ChunkEmbedding,
    EmbeddingResource,
    IndexGeneration,
    RetrievalProfile,
)
from agentos.models.provider import Provider


def _fake_vectors(texts):
    """Deterministic 4-dim embedding — bag-of-words hash, cosine-friendly."""
    out = []
    for item in texts:
        vec = [0.0] * 4
        for word in item.lower().split():
            vec[hash(word) % 4] += 1.0
        out.append(vec)
    return out


def _patch_embeddings(monkeypatch):
    async def fake(db, resource, texts):
        return _fake_vectors(texts)

    monkeypatch.setattr("agentos.knowledge.indexing.embed_texts", fake)
    monkeypatch.setattr("agentos.knowledge.retrieval.embed_texts", fake)


async def _local_provider(db, provider_type="ollama", base_url="http://localhost:11434"):
    provider = Provider(
        name="local-embed",
        type=provider_type,
        base_url=base_url,
        encrypted_key=None,
    )
    db.add(provider)
    await db.flush()
    return provider


async def _ready_resource(db, provider) -> EmbeddingResource:
    resource = EmbeddingResource(
        provider_id=provider.id,
        model_name="embed-test",
        dimensions=4,
        status="ready",
        egress_allowed=True,
    )
    db.add(resource)
    await db.flush()
    return resource


async def _hybrid_profile(db) -> RetrievalProfile:
    profile = RetrievalProfile(
        name="default",
        active=True,
        revision=1,
        config_json=json.dumps(
            {
                "fusion": "hybrid",
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


# --------------------------------------------------------------------------
# Chunking
# --------------------------------------------------------------------------


def test_prose_parent_child_tree():
    blocks = [
        ExtractedBlock(
            text=" ".join(f"w{i}" for i in range(300)),
            heading_path=["Guide"],
        )
    ]
    nodes = chunk_blocks(
        blocks, ChunkingConfig(parent_tokens=150, child_tokens=60, child_overlap=10)
    )
    parents = [n for n in nodes if n.kind == "parent"]
    assert parents
    assert all(n.token_count <= 160 for n in parents)  # + heading
    for parent in parents:
        assert all(c.kind == "child" for c in parent.children)
        assert all(c.token_count <= 61 for c in parent.children)


def test_short_prose_is_standalone_child():
    nodes = chunk_blocks(
        [ExtractedBlock(text="short note", heading_path=["S"])],
        ChunkingConfig(),
    )
    assert len(nodes) == 1
    assert nodes[0].kind == "child"
    assert nodes[0].children == []


def test_tabular_whichever_first_and_row_atomicity():
    rows = ["name | price | note"] + [f"item{i} | {i} | " + "x" * 40 for i in range(30)]
    block = ExtractedBlock(
        text="\n".join(rows),
        heading_path=[],
        sheet_name="Sheet1",
        source_location="Sheet1!A1:C31",
        block_type="sheet",
    )
    # Token bound (100) fires before the 150-row cap: ~184 tokens of data.
    nodes = chunk_blocks(
        [block], ChunkingConfig(parent_tokens=100, child_tokens=60, table_row_limit=150)
    )
    assert len(nodes) >= 2
    for node in nodes:
        if node.kind == "parent":
            assert "!A" in (node.source_location or "")
            for child in node.children:
                assert child.source_location.startswith("Sheet1!A")
                # Header row is prepended — children are self-contained.
                assert "name | price | note" in child.text
                # Row atomicity: every line after the header is a whole row.
                assert all("| " in line for line in child.text.splitlines()[1:])


def test_figure_is_singleton_child():
    nodes = chunk_blocks(
        [
            ExtractedBlock(
                text="Embedded image: photo.png",
                heading_path=["Doc"],
                source_location="image 1",
                block_type="figure",
            )
        ]
    )
    assert len(nodes) == 1
    assert nodes[0].kind == "child"
    assert nodes[0].source_location == "image 1"


# --------------------------------------------------------------------------
# Ingest → parent/child rows + FTS children only
# --------------------------------------------------------------------------


async def test_ingest_writes_parent_child_and_fts_children_only(db, tmp_path: Path):
    root = tmp_path / "vault"
    root.mkdir()
    (root / "guide.md").write_text(
        "# Guide\n\n" + " ".join(f"word{i}" for i in range(600)), encoding="utf-8"
    )

    document = await ingest_document(db, root / "guide.md", root)

    kinds = {
        row.kind
        for row in (
            await db.execute(select(DocumentChunk).where(DocumentChunk.document_id == document.id))
        ).scalars()
    }
    assert kinds == {"parent", "child"}
    children = (
        (
            await db.execute(
                select(DocumentChunk).where(
                    DocumentChunk.document_id == document.id, DocumentChunk.kind == "child"
                )
            )
        )
        .scalars()
        .all()
    )
    assert all(c.parent_id for c in children)

    # FTS holds children only — parents must not rank.
    fts_ids = {
        row[0]
        for row in (await db.execute(text("SELECT chunk_id FROM document_chunks_fts"))).fetchall()
    }
    assert fts_ids == {c.id for c in children}
    # No embedding resource/generation → semantic coverage not applicable.
    assert document.semantic_state == "na"


async def test_scope_isolation_shared_vs_private(db, tmp_path: Path):
    shared_root = tmp_path / "shared"
    private_root = tmp_path / "private"
    shared_root.mkdir()
    private_root.mkdir()
    (shared_root / "common.md").write_text("shared keyword alpha", encoding="utf-8")
    (private_root / "secret.md").write_text("alpha private secret", encoding="utf-8")

    await ingest_document(db, shared_root / "common.md", shared_root)
    await ingest_document(db, private_root / "secret.md", private_root, agent_id="agent-1")

    other = await retrieve(db, "alpha", agent_id="agent-2")
    assert {r["source_path"] for r in other["results"]} == {"common.md"}
    owner = await retrieve(db, "alpha", agent_id="agent-1")
    assert {r["source_path"] for r in owner["results"]} == {"common.md", "secret.md"}


# --------------------------------------------------------------------------
# Embed-at-ingest / pending
# --------------------------------------------------------------------------


async def test_embed_at_ingest_covers_new_doc(db, tmp_path: Path, monkeypatch):
    _patch_embeddings(monkeypatch)
    provider = await _local_provider(db)
    await _ready_resource(db, provider)
    await _hybrid_profile(db)
    await rebuild_index(db)

    root = tmp_path / "vault"
    root.mkdir()
    (root / "fresh.md").write_text("brand new document text", encoding="utf-8")
    document = await ingest_document(db, root / "fresh.md", root)

    assert document.semantic_state == "embedded"
    generation = await get_active_generation(db)
    embedded = await db.scalar(
        select(func.count(ChunkEmbedding.id)).where(ChunkEmbedding.generation_id == generation.id)
    )
    assert embedded and embedded > 0


async def test_embed_failure_marks_pending_and_keeps_lexical(db, tmp_path: Path, monkeypatch):
    async def boom(db, resource, texts):
        raise EmbeddingUnavailable("provider down")

    monkeypatch.setattr("agentos.knowledge.indexing.embed_texts", boom)
    provider = await _local_provider(db)
    await _ready_resource(db, provider)
    await _hybrid_profile(db)
    await rebuild_index(db)

    root = tmp_path / "vault"
    root.mkdir()
    (root / "doc.md").write_text("pending document vocabulary", encoding="utf-8")
    document = await ingest_document(db, root / "doc.md", root)

    assert document.semantic_state == "pending"
    # Still lexically searchable — semantic pending never blocks FTS.
    result = await retrieve(db, "vocabulary", agent_id=None)
    assert any(r["document_id"] == document.id for r in result["results"])


# --------------------------------------------------------------------------
# Egress
# --------------------------------------------------------------------------


async def test_remote_provider_blocked_without_egress(db):
    provider = Provider(
        name="openai",
        type="openai",
        base_url=None,
        encrypted_key=None,
    )
    db.add(provider)
    await db.flush()
    assert not provider_is_local(provider)

    resource = EmbeddingResource(
        provider_id=provider.id,
        model_name="text-embedding-3-small",
        status="unvalidated",
        egress_allowed=False,
    )
    db.add(resource)
    await db.flush()

    with pytest.raises(EmbeddingUnavailable, match="egress"):
        await embed_texts(db, resource, ["vault text"])

    # Opt-in unblocks it (the call itself is mocked — real call would hit API).
    resource.egress_allowed = True
    await db.flush()
    import litellm

    async def fake_aembedding(**kwargs):
        class R:
            data = [{"embedding": [0.1, 0.2]}]

        return R()

    monkeypatch_litellm = litellm.aembedding
    litellm.aembedding = fake_aembedding
    try:
        vectors = await embed_texts(db, resource, ["vault text"])
        assert vectors == [[0.1, 0.2]]
    finally:
        litellm.aembedding = monkeypatch_litellm


async def test_localhost_base_url_counts_as_local(db):
    provider = Provider(
        name="lmstudio",
        type="openai",  # generic type — locality comes from base_url
        base_url="http://127.0.0.1:1234/v1",
        encrypted_key=None,
    )
    db.add(provider)
    await db.flush()
    assert provider_is_local(provider)


# --------------------------------------------------------------------------
# Lifecycle: rebuild / 409 / repair / rollback / delete
# --------------------------------------------------------------------------


async def test_rebuild_rejects_concurrent_build(db):
    db.add(IndexGeneration(revision=1, profile_revision=1, status="building"))
    await db.flush()
    with pytest.raises(RebuildInProgress):
        await rebuild_index(db)


async def test_rebuild_sweeps_and_activates_atomically(db, tmp_path: Path, monkeypatch):
    _patch_embeddings(monkeypatch)
    provider = await _local_provider(db)
    await _ready_resource(db, provider)
    await _hybrid_profile(db)

    root = tmp_path / "vault"
    root.mkdir()
    (root / "a.md").write_text("alpha content here", encoding="utf-8")
    await ingest_document(db, root / "a.md", root)

    first = await rebuild_index(db)
    assert first.status == "active"
    second = await rebuild_index(db)
    await db.refresh(first)
    assert first.status == "superseded"
    assert second.status == "active"
    # Exactly one active generation.
    active_count = await db.scalar(
        select(func.count(IndexGeneration.id)).where(IndexGeneration.status == "active")
    )
    assert active_count == 1


async def test_repair_fills_semantic_holes(db, tmp_path: Path, monkeypatch):
    provider = await _local_provider(db)
    await _ready_resource(db, provider)
    await _hybrid_profile(db)
    await rebuild_index(db)

    # Ingest with failing embed → pending hole in the active generation.
    async def boom(db, resource, texts):
        raise EmbeddingUnavailable("down")

    monkeypatch.setattr("agentos.knowledge.indexing.embed_texts", boom)
    root = tmp_path / "vault"
    root.mkdir()
    (root / "hole.md").write_text("repair me please", encoding="utf-8")
    document = await ingest_document(db, root / "hole.md", root)
    assert document.semantic_state == "pending"

    # Provider recovers → repair fills just the hole.
    _patch_embeddings(monkeypatch)
    report = await repair_index(db)
    await db.refresh(document)
    assert report["fixed"] > 0
    assert report["still_pending"] == 0
    assert document.semantic_state == "embedded"


async def test_rollback_sweeps_gap_before_activating(db, tmp_path: Path, monkeypatch):
    _patch_embeddings(monkeypatch)
    provider = await _local_provider(db)
    await _ready_resource(db, provider)
    await _hybrid_profile(db)

    root = tmp_path / "vault"
    root.mkdir()
    (root / "one.md").write_text("first document body", encoding="utf-8")
    await ingest_document(db, root / "one.md", root)

    gen_a = await rebuild_index(db)
    gen_b = await rebuild_index(db)
    assert gen_b.status == "active"

    # Doc ingested during B's reign has vectors only in B.
    (root / "two.md").write_text("second document body", encoding="utf-8")
    doc_two = await ingest_document(db, root / "two.md", root)
    assert doc_two.semantic_state == "embedded"
    missing_in_a = await db.scalar(
        select(func.count(ChunkEmbedding.id))
        .join(DocumentChunk, DocumentChunk.id == ChunkEmbedding.chunk_id)
        .where(
            ChunkEmbedding.generation_id == gen_a.id,
            DocumentChunk.document_id == doc_two.id,
        )
    )
    assert missing_in_a == 0

    # Rollback to A sweeps the gap — A activates with full coverage.
    revived = await activate_generation(db, gen_a.id)
    assert revived.status == "active"
    filled = await db.scalar(
        select(func.count(ChunkEmbedding.id))
        .join(DocumentChunk, DocumentChunk.id == ChunkEmbedding.chunk_id)
        .where(
            ChunkEmbedding.generation_id == gen_a.id,
            DocumentChunk.document_id == doc_two.id,
        )
    )
    assert filled and filled > 0


async def test_delete_superseded_keeps_active(db):
    active = IndexGeneration(revision=1, profile_revision=1, status="active")
    old = IndexGeneration(revision=0, profile_revision=1, status="superseded")
    db.add_all([active, old])
    await db.flush()

    assert await delete_generation(db, active.id) is False
    assert await delete_generation(db, old.id) is True


# --------------------------------------------------------------------------
# Retrieval: fusion, trace, citations
# --------------------------------------------------------------------------


async def test_hybrid_retrieval_reports_semantic_hits(db, tmp_path: Path, monkeypatch):
    _patch_embeddings(monkeypatch)
    provider = await _local_provider(db)
    await _ready_resource(db, provider)
    await _hybrid_profile(db)

    root = tmp_path / "vault"
    root.mkdir()
    (root / "semantic.md").write_text("neural embeddings vector space", encoding="utf-8")
    await ingest_document(db, root / "semantic.md", root)
    await rebuild_index(db)

    result = await retrieve(db, "embeddings vector", agent_id=None)
    assert result["trace"]["fusion"] == "hybrid"
    assert result["trace"]["semantic_hits"] > 0
    assert result["trace"]["degraded"] == []


async def test_lexical_profile_never_touches_vectors(db, tmp_path: Path):
    root = tmp_path / "vault"
    root.mkdir()
    (root / "doc.md").write_text("plain lexical document", encoding="utf-8")
    await ingest_document(db, root / "doc.md", root)

    result = await retrieve(db, "lexical", agent_id=None)
    assert result["trace"]["fusion"] == "lexical"
    assert result["trace"]["semantic_hits"] == 0


async def test_full_trace_expands_on_include_trace(db, tmp_path: Path):
    root = tmp_path / "vault"
    root.mkdir()
    (root / "doc.md").write_text("traceable content", encoding="utf-8")
    await ingest_document(db, root / "doc.md", root)

    compact = await retrieve(db, "traceable", agent_id=None)
    assert "normalized_query" not in compact["trace"]
    full = await retrieve(db, "traceable", agent_id=None, include_trace=True)
    assert "normalized_query" in full["trace"]
    assert "adapter" in full["trace"]
    assert "selected" in full["trace"]


async def test_citations_carry_content_hash(db, tmp_path: Path):
    root = tmp_path / "vault"
    root.mkdir()
    path = root / "cite.md"
    path.write_text("citation target text", encoding="utf-8")
    document = await ingest_document(db, path, root)

    result = await retrieve(db, "citation", agent_id=None)
    assert result["results"]
    old_hash = document.content_hash
    assert result["results"][0]["content_hash"] == old_hash

    # Re-ingest changed content → new hash; old citations detectably stale.
    path.write_text("citation target text revised", encoding="utf-8")
    updated = await ingest_document(db, path, root)
    assert updated.content_hash != old_hash


async def test_vietnamese_retrieval(db, tmp_path: Path):
    root = tmp_path / "vault"
    root.mkdir()
    (root / "vn.md").write_text("Kiến thức vault cục bộ lưu trữ tài liệu", encoding="utf-8")
    await ingest_document(db, root / "vn.md", root)
    result = await retrieve(db, "vault", agent_id=None)
    assert result["count"] >= 1


async def test_parent_expansion_returns_parent_text(db, tmp_path: Path):
    root = tmp_path / "vault"
    root.mkdir()
    (root / "big.md").write_text(
        "# Manual\n\n" + " ".join(f"term{i}" for i in range(400)), encoding="utf-8"
    )
    await ingest_document(db, root / "big.md", root)

    result = await retrieve(db, "term200", agent_id=None, limit=3)
    expanded = [r for r in result["results"] if r["expanded"]]
    assert expanded, "expected at least one parent-expanded result"
    top = expanded[0]
    # chunk_id stays the *child* for citation stability; text carries context.
    child = await db.scalar(select(DocumentChunk).where(DocumentChunk.id == top["chunk_id"]))
    assert child.kind == "child"
    assert len(top["text"].split()) >= len(top["matched_text"].split())


async def test_adapter_python_fallback_reports_degradation(db, tmp_path: Path, monkeypatch):
    _patch_embeddings(monkeypatch)
    provider = await _local_provider(db)
    resource = await _ready_resource(db, provider)
    await _hybrid_profile(db)

    generation = IndexGeneration(
        revision=1,
        profile_revision=1,
        embedding_resource_id=resource.id,
        embedding_model="embed-test",
        dimensions=4,
        adapter="python",  # extension couldn't load on this generation
        status="active",
    )
    db.add(generation)
    await db.flush()

    root = tmp_path / "vault"
    root.mkdir()
    (root / "doc.md").write_text("fallback adapter content", encoding="utf-8")
    await ingest_document(db, root / "doc.md", root)

    result = await retrieve(db, "fallback", agent_id=None)
    assert any("adapter=python" in note for note in result["trace"]["degraded"])
    # Python adapter still returns semantic candidates.
    assert result["trace"]["semantic_hits"] > 0


async def test_dimension_mismatch_probe(db, monkeypatch):
    provider = await _local_provider(db)
    resource = EmbeddingResource(
        provider_id=provider.id,
        model_name="embed-test",
        dimensions=8,
        status="ready",
    )
    db.add(resource)
    await db.flush()

    import litellm

    async def fake_aembedding(**kwargs):
        class R:
            data = [{"embedding": [0.1, 0.2, 0.3, 0.4]}]  # 4 dims, expected 8

        return R()

    original = litellm.aembedding
    litellm.aembedding = fake_aembedding
    try:
        from agentos.knowledge.embeddings import probe_dimensions

        with pytest.raises(EmbeddingUnavailable, match="dimension mismatch"):
            await probe_dimensions(db, resource)
    finally:
        litellm.aembedding = original
