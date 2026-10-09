"""Shared Knowledge Vault API — ingest, list, search, and delete documents,
plus the RAG index-management surface (embedding resource, generations,
retrieval profile, repair)."""

import asyncio
import json
import shutil
import uuid
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..auth import require_operator
from ..config import settings
from ..db import get_db
from ..knowledge.embeddings import EmbeddingUnavailable, probe_dimensions, provider_is_local
from ..knowledge.indexing import (
    RebuildInProgress,
    activate_generation,
    delete_generation,
    get_active_generation,
    get_active_profile,
    rebuild_index,
    repair_index,
)
from ..knowledge.ingest import delete_document, ingest_document, list_documents
from ..knowledge.retrieval import retrieve
from ..models.agent import Agent
from ..models.document import Document, DocumentChunk
from ..models.knowledge_index import EmbeddingResource, IndexGeneration
from ..models.model_call import ModelCall
from ..models.operator import Operator, OperatorAuditLog
from ..models.provider import Provider
from ..sandbox.workspace import WorkspaceManager

router = APIRouter(prefix="/api/knowledge", tags=["knowledge"])
# Large-PDF friendly while still bounding disk usage; uploads stream to disk
# so the cap doesn't sit in memory.
_MAX_UPLOAD_BYTES = 250 * 1024 * 1024
_SUPPORTED_SUFFIXES = {".md", ".markdown", ".txt", ".pdf", ".docx"}
# Tabular files are refused, not chunked: flattening rows to text destroys
# queryability (no COUNT/filter/column semantics) and doc_search's top-K
# sample masquerades as coverage. A row-record ingest layer is deferred
# post-v0.2 (see v0.2-release-plan.md → "Structured sources get a row layer").
_TABULAR_SUFFIXES = {".xlsx", ".xls", ".csv"}


def _check_supported(file_name: str) -> None:
    suffix = Path(file_name).suffix.lower()
    if suffix in _TABULAR_SUFFIXES:
        raise HTTPException(
            status_code=400,
            detail=(
                "Tabular files are not indexed yet — rows need a queryable "
                "layer, not text chunks (deferred)"
            ),
        )
    if suffix not in _SUPPORTED_SUFFIXES:
        raise HTTPException(status_code=400, detail="Unsupported document format")


async def _stream_upload(file: UploadFile, target: Path) -> int:
    """Write an upload to disk in bounded chunks; 413 if it exceeds the cap."""
    total = 0
    try:
        with target.open("wb") as out:
            while chunk := await file.read(1024 * 1024):
                total += len(chunk)
                if total > _MAX_UPLOAD_BYTES:
                    raise HTTPException(
                        status_code=413,
                        detail="File exceeds the 250 MB upload limit",
                    )
                out.write(chunk)
    except HTTPException:
        target.unlink(missing_ok=True)
        raise
    return total


class IngestRequest(BaseModel):
    path: str = Field(min_length=1, max_length=4096)


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=1000)
    limit: int = Field(default=5, ge=1, le=20)
    include_trace: bool = False


class EmbeddingResourceRequest(BaseModel):
    provider_id: str = Field(min_length=1)
    model_name: str = Field(min_length=1, max_length=255)
    egress_allowed: bool = False


class RetrievalProfileRequest(BaseModel):
    fusion: str = Field(default="lexical", pattern="^(lexical|hybrid)$")
    parent_tokens: int = Field(default=450, ge=50, le=4000)
    child_tokens: int = Field(default=120, ge=20, le=1000)
    child_overlap: int = Field(default=20, ge=0)
    rrf_k: int = Field(default=60, ge=1, le=1000)
    max_parents: int = Field(default=4, ge=0, le=20)
    table_row_limit: int = Field(default=150, ge=1, le=10000)


def _audit(db: AsyncSession, operator: Operator, action: str, target: str) -> None:
    db.add(
        OperatorAuditLog(
            id=str(uuid.uuid4()),
            operator_id=operator.id,
            action=action,
            target=target,
        )
    )


async def _resolve_scope(scope: str, db: AsyncSession) -> str | None:
    """Resolve a public scope to a stored agent ID."""
    if scope == "shared":
        return None
    agent = await db.scalar(select(Agent).where(Agent.id == scope))
    if agent is None:
        raise HTTPException(status_code=404, detail="Knowledge scope not found")
    return agent.id


async def _unlink_unless_owned(db: AsyncSession, target: Path, agent_id: str | None) -> None:
    """Delete a failed upload's file unless a document row already owns it.

    ``ingest_document`` commits the corpus write before the embed phase, so
    a failure after that commit leaves a persisted document whose
    ``storage_path`` is this file — deleting it would orphan the row.
    """
    persisted = await db.scalar(
        select(Document.id).where(
            Document.agent_id == agent_id,
            Document.storage_path == target.name,
        )
    )
    if not persisted:
        target.unlink(missing_ok=True)


async def _document_chunk_count(db: AsyncSession, document_id: str) -> int:
    count = await db.scalar(
        select(func.count(DocumentChunk.id)).where(DocumentChunk.document_id == document_id)
    )
    return int(count or 0)


def _remove_document_file(document) -> None:
    """Remove a Vault file without allowing storage paths to escape the Vault."""
    root = Path(settings.knowledge_root).resolve()
    scope_root = root / (
        "shared" if document.agent_id is None else Path("agents") / document.agent_id
    )
    for candidate_root in (scope_root, root):
        candidate_root = candidate_root.resolve()
        candidate = (candidate_root / document.storage_path).resolve()
        try:
            candidate.relative_to(candidate_root)
        except ValueError:
            continue
        if candidate.is_file():
            candidate.unlink()
            return


def _document_response(document, chunk_count: int | None = None) -> dict:
    response = {
        "id": document.id,
        "agent_id": document.agent_id,
        "source_path": document.source_path,
        "storage_path": document.storage_path,
        "display_name": document.display_name,
        "mime_type": document.mime_type,
        "content_hash": document.content_hash,
        "size_bytes": document.size_bytes,
        "status": document.status,
        "error": document.error,
        "indexed_at": document.indexed_at.isoformat() if document.indexed_at else None,
        "structure": json.loads(document.structure_json or "{}"),
    }
    if chunk_count is not None:
        response["chunk_count"] = chunk_count
    return response


@router.get("/documents")
async def get_documents(
    operator: Operator = Depends(require_operator),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """List all documents in the shared Vault."""
    documents = await list_documents(db)
    return {"documents": [_document_response(document) for document in documents]}


@router.post("/documents/upload")
async def upload(
    file: UploadFile = File(...),
    operator: Operator = Depends(require_operator),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Save and index one dropped or selected file in the shared Vault."""
    filename = file.filename or ""
    file_path = Path(filename)
    if not filename or file_path.is_absolute() or file_path.name != filename:
        raise HTTPException(status_code=400, detail="File name must be a simple file name")
    _check_supported(filename)

    vault_root = (Path(settings.knowledge_root) / "shared").resolve()
    vault_root.mkdir(parents=True, exist_ok=True)
    target = vault_root / f"{uuid.uuid4().hex}{file_path.suffix.lower()}"
    await _stream_upload(file, target)
    try:
        document = await ingest_document(db, target, vault_root, filename)
        document.display_name = filename
        await db.commit()
    except (ValueError, UnicodeError) as error:
        await db.rollback()
        target.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail="Document could not be indexed") from error
    except Exception:
        await db.rollback()
        await _unlink_unless_owned(db, target, agent_id=None)
        raise
    return _document_response(document, await _document_chunk_count(db, document.id))


@router.get("/overview")
async def overview(
    operator: Operator = Depends(require_operator),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Return document and chunk totals for Shared and every agent."""
    agents = (await db.execute(select(Agent).order_by(Agent.name))).scalars().all()
    rows = []
    for scope_id, name, agent_id in [
        ("shared", "Shared Knowledge", None),
        *[(a.id, a.name, a.id) for a in agents],
    ]:
        document_count = await db.scalar(
            select(func.count(Document.id)).where(Document.agent_id == agent_id)
        )
        chunk_count = await db.scalar(
            select(func.count(DocumentChunk.id)).join(Document).where(Document.agent_id == agent_id)
        )
        rows.append(
            {
                "id": scope_id,
                "name": name,
                "document_count": document_count or 0,
                "chunk_count": chunk_count or 0,
            }
        )
    return {"scopes": rows}


@router.get("/scopes/{scope}/documents")
async def get_scope_documents(
    scope: str,
    operator: Operator = Depends(require_operator),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """List documents in Shared or one agent's private scope."""
    agent_id = await _resolve_scope(scope, db)
    documents = list(
        (
            await db.execute(
                select(Document)
                .where(Document.agent_id == agent_id)
                .options(selectinload(Document.chunks))
                .order_by(Document.display_name)
            )
        )
        .scalars()
        .all()
    )
    return {
        "documents": [_document_response(document, len(document.chunks)) for document in documents]
    }


@router.post("/scopes/{scope}/documents/{document_id}/reindex")
async def reindex_scope_document(
    scope: str,
    document_id: str,
    operator: Operator = Depends(require_operator),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Re-extract and index an existing document without replacing its file."""
    agent_id = await _resolve_scope(scope, db)
    document = await db.scalar(
        select(Document).where(Document.id == document_id, Document.agent_id == agent_id)
    )
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found")
    knowledge_root = Path(settings.knowledge_root).resolve()
    scope_root = (
        knowledge_root / ("shared" if agent_id is None else Path("agents") / agent_id)
    ).resolve()
    source = (scope_root / document.storage_path).resolve()
    try:
        source.relative_to(scope_root)
    except ValueError as error:
        raise HTTPException(status_code=400, detail="Document storage path is invalid") from error
    if not source.is_file():
        raise HTTPException(status_code=404, detail="Document file is missing")
    try:
        document = await ingest_document(db, source, scope_root, document.source_path, agent_id)
        await db.commit()
    except (ValueError, UnicodeError) as error:
        await db.rollback()
        raise HTTPException(status_code=400, detail="Document could not be indexed") from error
    return _document_response(document, await _document_chunk_count(db, document.id))


@router.post("/scopes/{scope}/search")
async def search_scope(
    scope: str,
    request: SearchRequest,
    operator: Operator = Depends(require_operator),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Preview documents in one scope — full retrieval trace for operators."""
    agent_id = await _resolve_scope(scope, db)
    return await retrieve(
        db, request.query, request.limit, agent_id, include_trace=request.include_trace
    )


@router.post("/scopes/{scope}/documents/upload")
async def upload_scope(
    scope: str,
    file: UploadFile = File(...),
    operator: Operator = Depends(require_operator),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Upload a document into Shared or one agent's private scope."""
    agent_id = await _resolve_scope(scope, db)
    filename = file.filename or ""
    file_path = Path(filename)
    if not filename or file_path.is_absolute() or file_path.name != filename:
        raise HTTPException(status_code=400, detail="File name must be a simple file name")
    _check_supported(filename)
    knowledge_root = Path(settings.knowledge_root).resolve()
    vault_root = knowledge_root / ("shared" if agent_id is None else Path("agents") / agent_id)
    vault_root = vault_root.resolve()
    try:
        vault_root.relative_to(knowledge_root)
    except ValueError as error:
        raise HTTPException(status_code=400, detail="Invalid knowledge scope path") from error
    vault_root.mkdir(parents=True, exist_ok=True)
    vault_root_resolved = vault_root.resolve()
    storage_name = f"{uuid.uuid4().hex}{file_path.suffix.lower()}"
    target = vault_root_resolved / storage_name
    await _stream_upload(file, target)
    try:
        document = await ingest_document(db, target, vault_root_resolved, filename, agent_id)
        if document.storage_path == storage_name:
            document.display_name = filename
        else:
            target.unlink(missing_ok=True)
        await db.commit()
    except (ValueError, UnicodeError) as error:
        await db.rollback()
        target.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail="Document could not be indexed") from error
    except Exception:
        await db.rollback()
        await _unlink_unless_owned(db, target, agent_id)
        raise
    return _document_response(document, await _document_chunk_count(db, document.id))


@router.delete("/scopes/{scope}/documents/{document_id}", status_code=204)
async def remove_scope(
    scope: str,
    document_id: str,
    operator: Operator = Depends(require_operator),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Delete a document from one scope."""
    agent_id = await _resolve_scope(scope, db)
    document = await db.scalar(
        select(Document).where(Document.id == document_id, Document.agent_id == agent_id)
    )
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found")
    _remove_document_file(document)
    await delete_document(db, document_id)
    await db.commit()


@router.post("/from-workspace/{agent_id}")
async def ingest_workspace_file(
    agent_id: str,
    request: IngestRequest,
    operator: Operator = Depends(require_operator),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Copy and index an existing agent workspace file into the shared Vault."""
    workspace = Path(WorkspaceManager().get_workspace_path(agent_id)).resolve()
    source = Path(WorkspaceManager().validate_path(str(workspace), request.path))
    if not source.is_file():
        raise HTTPException(status_code=400, detail="Document does not exist")
    _check_supported(source.name)
    vault_root = Path(settings.knowledge_root).resolve()
    vault_root.mkdir(parents=True, exist_ok=True)
    target = vault_root / f"{uuid.uuid4().hex}{source.suffix.lower()}"
    await asyncio.to_thread(shutil.copyfile, source, target)
    try:
        document = await ingest_document(db, target, vault_root, request.path)
        document.display_name = source.name
        await db.commit()
    except (ValueError, UnicodeError) as error:
        await db.rollback()
        target.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail="Document could not be indexed") from error
    except Exception:
        await db.rollback()
        await _unlink_unless_owned(db, target, agent_id=None)
        raise
    return _document_response(document, await _document_chunk_count(db, document.id))


@router.post("/search")
async def search(
    request: SearchRequest,
    operator: Operator = Depends(require_operator),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Search the shared Vault — full retrieval trace for operators."""
    return await retrieve(
        db, request.query, request.limit, None, include_trace=request.include_trace
    )


@router.delete("/documents/{document_id}", status_code=204)
async def remove(
    document_id: str,
    operator: Operator = Depends(require_operator),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Delete a document, its indexed chunks, and its stored Vault file."""
    document = await db.scalar(select(Document).where(Document.id == document_id))
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found")
    _remove_document_file(document)
    await delete_document(db, document_id)
    await db.commit()


# ---------------------------------------------------------------------------
# Index management (RAG v2)
# ---------------------------------------------------------------------------


def _resource_response(resource: EmbeddingResource | None, provider: Provider | None) -> dict:
    if resource is None:
        return {"configured": False}
    return {
        "configured": True,
        "id": resource.id,
        "provider_id": resource.provider_id,
        "provider_name": provider.name if provider else None,
        "provider_type": provider.type if provider else None,
        "model_name": resource.model_name,
        "dimensions": resource.dimensions,
        "status": resource.status,
        "last_error": resource.last_error,
        "last_validated_at": (
            resource.last_validated_at.isoformat() if resource.last_validated_at else None
        ),
        "egress_allowed": resource.egress_allowed,
        "provider_local": provider_is_local(provider) if provider else None,
    }


_GENERATION_OPS = ("index", "ingest", "repair")


async def _generation_spend_map(db: AsyncSession) -> dict[str, dict]:
    """Cost/tokens attributed to each generation's vector set — index,
    ingest, and repair calls only; query embeds are per-search spend."""
    gen = ModelCall.detail["generation_id"].as_string()
    op = ModelCall.detail["operation"].as_string()
    rows = (
        await db.execute(
            select(
                gen,
                func.coalesce(func.sum(ModelCall.cost), 0.0),
                func.coalesce(func.sum(ModelCall.tokens_in), 0),
            )
            .where(
                ModelCall.kind == "embedding",
                gen.is_not(None),
                op.in_(_GENERATION_OPS),
            )
            .group_by(gen)
        )
    ).all()
    return {
        generation_id: {"cost": float(cost), "tokens_in": int(tokens)}
        for generation_id, cost, tokens in rows
    }


def _generation_response(generation: IndexGeneration, spend: dict | None = None) -> dict:
    response = {
        "id": generation.id,
        "revision": generation.revision,
        "status": generation.status,
        "profile_revision": generation.profile_revision,
        "embedding_model": generation.embedding_model,
        "dimensions": generation.dimensions,
        "adapter": generation.adapter,
        "stats": json.loads(generation.stats_json or "{}"),
        "error": generation.error,
        "activated_at": (generation.activated_at.isoformat() if generation.activated_at else None),
        "created_at": generation.created_at.isoformat() if generation.created_at else None,
    }
    if spend is not None:
        response["cost"] = spend["cost"]
        response["tokens_in"] = spend["tokens_in"]
    return response


@router.get("/index")
async def index_overview(
    operator: Operator = Depends(require_operator),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Index overview: active generation, embedding resource, profile, counts."""
    profile = await get_active_profile(db)
    active = await get_active_generation(db)
    resource = await db.scalar(
        select(EmbeddingResource).order_by(EmbeddingResource.created_at).limit(1)
    )
    provider = (
        await db.scalar(select(Provider).where(Provider.id == resource.provider_id))
        if resource
        else None
    )
    pending = await db.scalar(
        select(func.count(Document.id)).where(Document.semantic_state == "pending")
    )
    building = await db.scalar(
        select(IndexGeneration).where(IndexGeneration.status == "building").limit(1)
    )
    spend_map = await _generation_spend_map(db)
    spend_totals = (
        await db.execute(
            select(
                func.count(ModelCall.id),
                func.coalesce(func.sum(ModelCall.tokens_in), 0),
                func.coalesce(func.sum(ModelCall.cost), 0.0),
            ).where(ModelCall.kind == "embedding")
        )
    ).one()
    return {
        "profile": {
            "id": profile.id,
            "revision": profile.revision,
            "config": json.loads(profile.config_json or "{}"),
        },
        "embedding_resource": _resource_response(resource, provider),
        "active_generation": (
            _generation_response(active, spend_map.get(active.id)) if active else None
        ),
        "building_generation": (
            _generation_response(building, spend_map.get(building.id)) if building else None
        ),
        "documents": {
            "pending": pending or 0,
        },
        "embedding_spend": {
            "calls": spend_totals[0],
            "tokens_in": int(spend_totals[1]),
            "cost": float(spend_totals[2]),
        },
    }


@router.put("/embedding-resource")
async def put_embedding_resource(
    request: EmbeddingResourceRequest,
    operator: Operator = Depends(require_operator),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Configure the embedding resource. Remote providers stay `unvalidated`
    until the operator explicitly enables egress — vault text leaving the
    machine is an audited, opt-in decision."""
    provider = await db.scalar(select(Provider).where(Provider.id == request.provider_id))
    if provider is None:
        raise HTTPException(status_code=404, detail="Provider not found")

    resource = await db.scalar(
        select(EmbeddingResource).order_by(EmbeddingResource.created_at).limit(1)
    )
    if resource is None:
        resource = EmbeddingResource(provider_id=request.provider_id, model_name="")
        db.add(resource)
    resource.provider_id = request.provider_id
    resource.model_name = request.model_name
    resource.status = "unvalidated"
    resource.dimensions = None
    resource.last_error = None

    remote = not provider_is_local(provider)
    if remote and request.egress_allowed and not resource.egress_allowed:
        _audit(db, operator, "knowledge.embedding_egress_enabled", resource.provider_id)
    resource.egress_allowed = request.egress_allowed or not remote
    await db.commit()
    return _resource_response(resource, provider)


@router.post("/embedding-resource/validate")
async def validate_embedding_resource(
    operator: Operator = Depends(require_operator),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Bounded probe embedding — learns dimensions, refuses remote egress
    without explicit opt-in."""
    resource = await db.scalar(
        select(EmbeddingResource).order_by(EmbeddingResource.created_at).limit(1)
    )
    if resource is None:
        raise HTTPException(status_code=404, detail="No embedding resource configured")
    provider = await db.scalar(select(Provider).where(Provider.id == resource.provider_id))
    if provider is None:
        raise HTTPException(status_code=404, detail="Provider not found")
    if not provider_is_local(provider) and not resource.egress_allowed:
        raise HTTPException(
            status_code=403,
            detail="Remote embedding requires egress_allowed — vault text would leave this machine",
        )
    try:
        resource.dimensions = await probe_dimensions(db, resource)
        resource.status = "ready"
        resource.last_error = None
        resource.last_validated_at = datetime.now(UTC)
    except EmbeddingUnavailable as error:
        resource.status = "error"
        resource.last_error = str(error)
    await db.commit()
    response = _resource_response(resource, provider)
    if resource.status == "ready":
        profile = await get_active_profile(db)
        if json.loads(profile.config_json or "{}").get("fusion") == "lexical":
            response["hint"] = (
                "embedding resource ready — set retrieval profile fusion='hybrid' "
                "and rebuild the index to enable semantic retrieval"
            )
    return response


@router.post("/index/rebuild")
async def rebuild(
    operator: Operator = Depends(require_operator),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Synchronous re-embed of the canonical chunk set into a new generation,
    then atomic activation."""
    try:
        generation = await rebuild_index(db)
    except RebuildInProgress:
        raise HTTPException(status_code=409, detail="An index rebuild is already running")
    _audit(db, operator, "knowledge.index_rebuild", generation.id)
    await db.commit()
    spend_map = await _generation_spend_map(db)
    return _generation_response(generation, spend_map.get(generation.id))


@router.post("/index/repair")
async def repair(
    operator: Operator = Depends(require_operator),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Targeted sweep: embed only the chunks missing vectors in the active
    generation. Rebuild is for wrong indexes; repair is for incomplete ones."""
    report = await repair_index(db)
    _audit(db, operator, "knowledge.index_repair", "active")
    await db.commit()
    return report


@router.get("/index/generations")
async def list_generations(
    operator: Operator = Depends(require_operator),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """All generations, newest first — superseded ones persist for rollback."""
    rows = (
        (await db.execute(select(IndexGeneration).order_by(IndexGeneration.revision.desc())))
        .scalars()
        .all()
    )
    spend_map = await _generation_spend_map(db)
    return {"generations": [_generation_response(row, spend_map.get(row.id)) for row in rows]}


@router.post("/index/generations/{generation_id}/activate")
async def activate(
    generation_id: str,
    operator: Operator = Depends(require_operator),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Rollback: sweep the revived generation's gaps, then atomically activate."""
    try:
        generation = await activate_generation(db, generation_id)
    except RebuildInProgress:
        raise HTTPException(status_code=409, detail="An index rebuild is still running")
    except ValueError:
        raise HTTPException(status_code=404, detail="Generation not found")
    _audit(db, operator, "knowledge.generation_activated", generation.id)
    await db.commit()
    spend_map = await _generation_spend_map(db)
    response = _generation_response(generation, spend_map.get(generation.id))
    pending = await db.scalar(
        select(func.count(Document.id)).where(Document.semantic_state == "pending")
    )
    if pending:
        response["degraded"] = f"{pending} documents pending semantic coverage"
    return response


@router.delete("/index/generations/{generation_id}", status_code=204)
async def remove_generation(
    generation_id: str,
    operator: Operator = Depends(require_operator),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Delete a superseded/failed generation and its vectors."""
    if not await delete_generation(db, generation_id):
        raise HTTPException(status_code=404, detail="Generation not found or still active")
    await db.commit()


@router.get("/retrieval-profile")
async def get_profile(
    operator: Operator = Depends(require_operator),
    db: AsyncSession = Depends(get_db),
) -> dict:
    profile = await get_active_profile(db)
    return {
        "id": profile.id,
        "name": profile.name,
        "revision": profile.revision,
        "config": json.loads(profile.config_json or "{}"),
    }


@router.put("/retrieval-profile")
async def put_profile(
    request: RetrievalProfileRequest,
    operator: Operator = Depends(require_operator),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Update retrieval tuning — bumps revision; generations snapshot it."""
    profile = await get_active_profile(db)
    config = request.model_dump()
    if config["child_overlap"] >= config["child_tokens"]:
        raise HTTPException(
            status_code=400, detail="child_overlap must be smaller than child_tokens"
        )
    profile.config_json = json.dumps(config)
    profile.revision += 1
    _audit(db, operator, "knowledge.retrieval_profile_updated", profile.id)
    await db.commit()
    return {"id": profile.id, "revision": profile.revision, "config": config}
