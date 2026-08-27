"""Knowledge Vault capabilities."""

import base64
import io
import json
import zipfile
from pathlib import Path
from typing import Any

from sqlalchemy import func, or_, select

from ...config import settings
from ...knowledge.ingest import search_documents
from ...models.document import Document, DocumentChunk
from ...models.source import RunSource


def _render_pdf_page(path: Path, page_number: int) -> bytes:
    import pypdfium2 as pdfium

    pdf = pdfium.PdfDocument(str(path))
    try:
        if page_number < 1 or page_number > len(pdf):
            raise ValueError("PDF page not found")
        page = pdf[page_number - 1]
        try:
            image = page.render(scale=1.5).to_pil()
            buffer = io.BytesIO()
            image.save(buffer, format="PNG", optimize=True)
            return buffer.getvalue()
        finally:
            page.close()
    finally:
        pdf.close()


def _docx_image(path: Path, image_index: int) -> tuple[str, bytes]:
    with zipfile.ZipFile(path) as archive:
        images = sorted(name for name in archive.namelist() if name.startswith("word/media/"))
        if image_index < 1 or image_index > len(images):
            raise ValueError("DOCX image not found")
        image_name = images[image_index - 1]
        return Path(image_name).name, archive.read(image_name)


def _visual_content(
    document: Document, result: dict[str, Any], agent_id: str
) -> list[dict[str, Any]]:
    path = _document_path(document, agent_id)
    if path.suffix.lower() == ".pdf" and result.get("page_number"):
        return _image_content(
            f"{document.display_name} page {result['page_number']}.png",
            _render_pdf_page(path, result["page_number"]),
        )
    location = result.get("source_location") or ""
    if path.suffix.lower() == ".docx" and location.startswith("image "):
        image_name, content = _docx_image(path, int(location.removeprefix("image ")))
        return _image_content(image_name, content)
    return []


async def doc_list(args: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
    """List bounded metadata for documents visible to the active agent."""
    db = kwargs["db"]
    agent_id = kwargs["agent_id"]
    limit = max(1, min(args.get("limit", 20), 50))
    statement = select(Document).where(
        or_(Document.agent_id.is_(None), Document.agent_id == agent_id)
    )
    query = str(args.get("query", "")).strip()
    if query:
        pattern = f"%{query}%"
        statement = statement.where(
            or_(Document.display_name.ilike(pattern), Document.source_path.ilike(pattern))
        )
    status = args.get("status")
    if status:
        statement = statement.where(Document.status == status)
    statement = statement.order_by(Document.display_name).limit(limit)
    documents = list((await db.execute(statement)).scalars().all())
    chunk_counts = (
        dict(
            (
                document_id,
                count,
            )
            for document_id, count in (
                await db.execute(
                    select(DocumentChunk.document_id, func.count(DocumentChunk.id))
                    .where(DocumentChunk.document_id.in_([document.id for document in documents]))
                    .group_by(DocumentChunk.document_id)
                )
            ).all()
        )
        if documents
        else {}
    )
    metadata = [
        {
            "document_id": document.id,
            "display_name": document.display_name,
            "source_path": document.source_path,
            "mime_type": document.mime_type,
            "size_bytes": document.size_bytes,
            "status": document.status,
            "error": document.error,
            "indexed_at": document.indexed_at.isoformat() if document.indexed_at else None,
            "chunk_count": chunk_counts.get(document.id, 0),
            "structure": json.loads(document.structure_json or "{}"),
            "scope": "shared" if document.agent_id is None else "private",
        }
        for document in documents
    ]
    return {"documents": metadata, "count": len(metadata)}


async def doc_search(args: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
    """Search shared knowledge and the active agent's private knowledge."""
    query = args["query"]
    limit = args.get("limit", 5)
    db = kwargs["db"]
    results = await search_documents(
        db,
        query,
        limit=limit,
        agent_id=kwargs["agent_id"],
    )
    run_id = kwargs.get("run_id")
    if run_id:
        for result in results:
            exists = await db.scalar(
                select(RunSource.id).where(
                    RunSource.run_id == run_id,
                    RunSource.chunk_id == result["chunk_id"],
                )
            )
            if exists is None:
                db.add(
                    RunSource(
                        run_id=run_id,
                        chunk_id=result["chunk_id"],
                        document_id=result["document_id"],
                        source_path=result["source_path"],
                        storage_path=result["storage_path"],
                        heading_path=json.dumps(result["heading_path"], ensure_ascii=False),
                        page_number=result.get("page_number"),
                        sheet_name=result.get("sheet_name"),
                        source_location=result.get("source_location"),
                        excerpt=result["text"],
                    )
                )
        await db.flush()

    response: dict[str, Any] = {"query": query, "results": results, "count": len(results)}
    if kwargs.get("supports_vision"):
        model_content: list[dict[str, Any]] = []
        seen_visuals: set[tuple[str, int | str]] = set()
        for result in results[:2]:
            document = await db.scalar(select(Document).where(Document.id == result["document_id"]))
            if document is None:
                continue
            visual_key = (
                result["document_id"],
                result.get("page_number") or result.get("source_location") or "",
            )
            if visual_key in seen_visuals:
                continue
            seen_visuals.add(visual_key)
            try:
                model_content.extend(_visual_content(document, result, kwargs["agent_id"]))
            except (OSError, ValueError, TypeError, zipfile.BadZipFile):
                continue
        if model_content:
            response["_model_content"] = model_content
    return response


def _document_path(document: Document, agent_id: str) -> Path:
    """Resolve a Vault document to a contained local file."""
    root = Path(settings.knowledge_root).resolve()
    scope_roots = [root / ("shared" if document.agent_id is None else "agents" / agent_id), root]
    relative = Path(document.storage_path)
    for scope_root in scope_roots:
        scope_root = scope_root.resolve()
        candidate = (scope_root / relative).resolve()
        try:
            candidate.relative_to(scope_root)
        except ValueError:
            continue
        if candidate.is_file():
            return candidate
    raise ValueError("Document file is unavailable")


def _image_content(name: str, content: bytes) -> list[dict[str, Any]]:
    suffix = Path(name).suffix.lower()
    mime = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".gif": "image/gif",
        ".webp": "image/webp",
    }.get(suffix)
    if not mime:
        return []
    return [
        {"type": "text", "text": f"Visual source: {name}"},
        {
            "type": "image_url",
            "image_url": {"url": f"data:{mime};base64,{base64.b64encode(content).decode('ascii')}"},
        },
    ]


async def doc_inspect(args: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
    """Inspect a bounded PDF page or DOCX embedded image with a vision model."""
    db = kwargs["db"]
    agent_id = kwargs["agent_id"]
    document = await db.scalar(
        select(Document).where(
            Document.id == args["document_id"],
            or_(Document.agent_id.is_(None), Document.agent_id == agent_id),
        )
    )
    if document is None:
        return {"error": "Document not found"}
    if not kwargs.get("supports_vision"):
        return {"error": "The selected model cannot inspect visual document content"}
    path = _document_path(document, agent_id)
    page_number = args.get("page_number")
    image_index = args.get("image_index", 1)

    if path.suffix.lower() == ".pdf":
        if not isinstance(page_number, int) or page_number < 1:
            return {"error": "PDF inspection requires a positive page_number"}
        import pypdfium2 as pdfium

        pdf = pdfium.PdfDocument(str(path))
        if page_number > len(pdf):
            return {"error": "PDF page not found"}
        page = pdf[page_number - 1]
        bitmap = page.render(scale=1.5)
        image = bitmap.to_pil()
        buffer = io.BytesIO()
        image.save(buffer, format="PNG", optimize=True)
        page.close()
        pdf.close()
        return {
            "document_id": document.id,
            "page_number": page_number,
            "source_path": document.source_path,
            "_model_content": _image_content(
                f"{document.display_name} page {page_number}.png", buffer.getvalue()
            ),
        }

    if path.suffix.lower() == ".docx":
        if not isinstance(image_index, int) or image_index < 1:
            return {"error": "image_index must be a positive integer"}
        with zipfile.ZipFile(path) as archive:
            images = sorted(name for name in archive.namelist() if name.startswith("word/media/"))
            if image_index > len(images):
                return {"error": "DOCX image not found"}
            image_name = images[image_index - 1]
            content = archive.read(image_name)
        return {
            "document_id": document.id,
            "image_index": image_index,
            "source_path": document.source_path,
            "_model_content": _image_content(Path(image_name).name, content),
        }

    return {"error": "Visual inspection is supported for PDF and DOCX documents"}
