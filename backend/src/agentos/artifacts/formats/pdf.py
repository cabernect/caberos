"""PDF handler — read-only: inspect + validate via pypdf.

No build/revise: imported PDFs are retained read-only per the plan. PDF
*export* of Office artifacts lives in the service (renderer-backed), not here.
"""

from io import BytesIO

from pypdf import PdfReader


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
