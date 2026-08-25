"""Shared Knowledge Vault API — ingest, list, search, and delete documents."""

from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import require_operator
from ..config import settings
from ..db import get_db
from ..knowledge.ingest import delete_document, ingest_document, list_documents, search_documents
from ..models.agent import Agent
from ..models.document import Document, DocumentChunk
from ..models.operator import Operator
from ..sandbox.workspace import WorkspaceManager

router = APIRouter(prefix="/api/knowledge", tags=["knowledge"])
_MAX_UPLOAD_BYTES = 25 * 1024 * 1024
_SUPPORTED_SUFFIXES = {".md", ".markdown", ".txt", ".pdf", ".docx", ".xlsx"}


class IngestRequest(BaseModel):
    path: str = Field(min_length=1, max_length=4096)


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=1000)
    limit: int = Field(default=5, ge=1, le=20)


async def _resolve_scope(scope: str, db: AsyncSession) -> str | None:
    """Resolve a public scope to a real agent, preventing arbitrary filesystem paths."""
    if scope == "shared":
        return None
    if await db.scalar(select(Agent.id).where(Agent.id == scope)) is None:
        raise HTTPException(status_code=404, detail="Knowledge scope not found")
    return scope


def _document_response(document) -> dict:
    return {
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
    }


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
    if file_path.suffix.lower() not in _SUPPORTED_SUFFIXES:
        raise HTTPException(status_code=400, detail="Unsupported document format")

    content = await file.read(_MAX_UPLOAD_BYTES + 1)
    if len(content) > _MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="File exceeds the 25 MB upload limit")

    vault_root = Path(settings.knowledge_root) / "shared"
    vault_root.mkdir(parents=True, exist_ok=True)
    target = vault_root / filename
    target.write_bytes(content)
    try:
        document = await ingest_document(db, target, vault_root, filename)
        await db.commit()
    except (ValueError, UnicodeError) as error:
        await db.rollback()
        target.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail=str(error)) from error
    return _document_response(document)


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
    return {"documents": [_document_response(d) for d in await list_documents(db, agent_id)]}


@router.post("/scopes/{scope}/search")
async def search_scope(
    scope: str,
    request: SearchRequest,
    operator: Operator = Depends(require_operator),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Preview documents in one scope."""
    agent_id = await _resolve_scope(scope, db)
    return {"results": await search_documents(db, request.query, request.limit, agent_id)}


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
    if file_path.suffix.lower() not in _SUPPORTED_SUFFIXES:
        raise HTTPException(status_code=400, detail="Unsupported document format")
    content = await file.read(_MAX_UPLOAD_BYTES + 1)
    if len(content) > _MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="File exceeds the 25 MB upload limit")
    knowledge_root = Path(settings.knowledge_root).resolve()
    vault_root = knowledge_root / (
        "shared" if agent_id is None else Path("agents") / agent_id
    )
    vault_root = vault_root.resolve()
    try:
        vault_root.relative_to(knowledge_root)
    except ValueError as error:
        raise HTTPException(status_code=400, detail="Invalid knowledge scope path") from error
    vault_root.mkdir(parents=True, exist_ok=True)
    target = vault_root / filename
    target.write_bytes(content)
    try:
        document = await ingest_document(db, target, vault_root, filename, agent_id)
        await db.commit()
    except (ValueError, UnicodeError) as error:
        await db.rollback()
        target.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail=str(error)) from error
    return _document_response(document)


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
    if document is None or not await delete_document(db, document_id):
        raise HTTPException(status_code=404, detail="Document not found")
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
        raise HTTPException(status_code=400, detail=f"Document does not exist: {request.path}")
    vault_root = Path(settings.knowledge_root)
    vault_root.mkdir(parents=True, exist_ok=True)
    target = vault_root / source.name
    target.write_bytes(source.read_bytes())
    try:
        document = await ingest_document(db, target, vault_root, request.path)
        await db.commit()
    except (ValueError, UnicodeError) as error:
        await db.rollback()
        target.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail=str(error)) from error
    return _document_response(document)


@router.post("/search")
async def search(
    request: SearchRequest,
    operator: Operator = Depends(require_operator),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Search the shared Vault."""
    return {"results": await search_documents(db, request.query, request.limit)}


@router.delete("/documents/{document_id}", status_code=204)
async def remove(
    document_id: str,
    operator: Operator = Depends(require_operator),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Delete a document and its indexed chunks."""
    if not await delete_document(db, document_id):
        raise HTTPException(status_code=404, detail="Document not found")
    await db.commit()
