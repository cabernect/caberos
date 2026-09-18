"""PDF handler — build via reportlab + inspect/validate via pypdf.

No revise: PDFs are write-once — a rendered end state, not an editable
source. Direct creation takes the docx-style block spec and renders it
through agentos.artifacts.pdf_render (same normalized element vocabulary).
Office→PDF export of existing artifacts lives in the service.
"""

from io import BytesIO
from pathlib import Path

from pypdf import PdfReader


def build(spec: dict, workspace_path: str | Path) -> bytes:
    from ..pdf_render import render_document

    elements: list[dict] = []
    if title := spec.get("title"):
        elements.append({"type": "heading", "text": title, "level": 1})
    elements.extend(spec.get("blocks", []))
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
