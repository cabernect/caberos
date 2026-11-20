"""PDF handler — build via reportlab + inspect/validate via pypdf.

No revise: PDFs are write-once — a rendered end state, not an editable
source. Direct creation takes the docx-style block spec and renders it
through agentos.artifacts.pdf_render (same normalized element vocabulary).
"""

from io import BytesIO
from pathlib import Path

from pypdf import PdfReader


def build(spec: dict, workspace_path: str | Path) -> bytes:
    from ..pdf_render import render_document

    elements: list[dict] = []
    title = spec.get("title")
    blocks = spec.get("blocks", [])
    has_cover = any(isinstance(b, dict) and b.get("type") == "cover" for b in blocks)
    if title and not has_cover:
        elements.append({"type": "heading", "text": title, "level": 1})
    for block in blocks:
        kind = block.get("type") if isinstance(block, dict) else None
        if kind == "cover":
            # PDF has no cover-page concept — render as heading + subtitle.
            cover_title = block.get("title") or title
            if cover_title:
                elements.append({"type": "heading", "text": cover_title, "level": 1})
            if block.get("subtitle"):
                elements.append({"type": "paragraph", "text": block["subtitle"]})
            elements.append({"type": "page_break"})
        elif kind == "section_break":
            elements.append({"type": "page_break"})
        else:
            elements.append(block)
    return render_document(elements, workspace_path)


def inspect(data: bytes) -> dict:
    reader = PdfReader(BytesIO(data))
    return {"structure": {"pages": len(reader.pages)}}


def validate(data: bytes) -> dict:
    errors: list[str] = []
    try:
        reader = PdfReader(BytesIO(data))
        len(reader.pages)
    except Exception as e:
        errors.append(f"pdf parse failed: {e}")
    return {"valid": not errors, "errors": errors}
