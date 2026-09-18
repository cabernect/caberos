"""Pure-Python PDF rendering — reportlab backend.

Renders a normalized element list (the same vocabulary as docx spec blocks)
to PDF bytes. This is the universal export path when LibreOffice isn't
installed, and the build backend for direct spec→PDF creation.

Font honesty: reportlab's built-in Helvetica is latin-1 only — non-latin
text (Vietnamese, CJK, emoji) renders as boxes. We register the first
Unicode TTF found on the platform; the bundled Bitstream Vera is the
last resort (partial Latin Extended coverage).
"""

import os
from io import BytesIO
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    Image,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

_FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",  # Linux / Docker
    "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
    "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",  # macOS
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
    "C:/Windows/Fonts/arial.ttf",  # Windows
]

_BOLD_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
]

_REGISTERED: dict[str, str] = {}


def _font(bold: bool = False) -> str:
    """Register and return the best available Unicode font name."""
    key = "bold" if bold else "regular"
    if key in _REGISTERED:
        return _REGISTERED[key]
    candidates = list(_BOLD_CANDIDATES if bold else _FONT_CANDIDATES)
    if not bold:
        import reportlab

        candidates.append(str(Path(reportlab.__file__).parent / "fonts" / "Vera.ttf"))
    name = f"AgentOS{'Bold' if bold else 'Sans'}"
    for path in candidates:
        if not os.path.exists(path):
            continue
        try:
            pdfmetrics.registerFont(TTFont(name, path))
            _REGISTERED[key] = name
            return name
        except Exception:
            continue
    # Bold can fall back to the regular face; regular falls back to latin-1 Helvetica.
    _REGISTERED[key] = _font() if bold else "Helvetica"
    return _REGISTERED[key]


def _esc(text: object) -> str:
    return escape(str(text)).replace("\n", "<br/>")


def _styles() -> dict[str, ParagraphStyle]:
    regular, bold = _font(), _font(bold=True)
    return {
        "h1": ParagraphStyle(
            "h1", fontName=bold, fontSize=18, leading=22, spaceBefore=6, spaceAfter=10
        ),
        "h2": ParagraphStyle(
            "h2", fontName=bold, fontSize=15, leading=19, spaceBefore=5, spaceAfter=8
        ),
        "h3": ParagraphStyle(
            "h3", fontName=bold, fontSize=12.5, leading=16, spaceBefore=4, spaceAfter=6
        ),
        "body": ParagraphStyle("body", fontName=regular, fontSize=10.5, leading=15, spaceAfter=6),
        "cell": ParagraphStyle("cell", fontName=regular, fontSize=9.5, leading=13),
        "cellb": ParagraphStyle("cellb", fontName=bold, fontSize=9.5, leading=13),
        "note": ParagraphStyle(
            "note", fontName=regular, fontSize=8.5, leading=12, textColor=colors.grey
        ),
    }


def _make_table(data: list[list], styles: dict, avail_width: float) -> Table:
    rows = [
        [Paragraph(_esc(c), styles["cellb" if i == 0 else "cell"]) for c in row]
        for i, row in enumerate(data)
    ]
    ncols = max(len(r) for r in data)
    table = Table(rows, colWidths=[avail_width / ncols] * ncols)
    table.setStyle(
        TableStyle(
            [
                ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    return table


def _image_flowable(el: dict, workspace_path: str | Path | None):
    data = el.get("data")
    if data is None and el.get("path") and workspace_path is not None:
        from ..sandbox.workspace import resolve_within

        img = resolve_within(workspace_path, el["path"])
        if img.exists():
            data = img.read_bytes()
    if not data:
        return Paragraph("[image unavailable]", _styles()["note"])
    try:
        from PIL import Image as PILImage

        with PILImage.open(BytesIO(data)) as pil:
            w, h = pil.size
        width = min(6 * inch, w)
        return Image(BytesIO(data), width=width, height=width * h / w)
    except Exception:
        return Paragraph("[image unreadable]", _styles()["note"])


def render_document(elements: list[dict], workspace_path: str | Path | None = None) -> bytes:
    """Render normalized elements → PDF bytes.

    Element vocabulary (superset of docx spec blocks):
      heading {text, level 1-3} · paragraph {text} · list {style, items}
      table {header, rows} · image {data|path} · chart {categories, series}
      notes {text} · page_break {}
    Unknown kinds render as a bracketed marker, never crash the export.
    """
    styles = _styles()
    margin = 0.9 * inch
    avail_width = letter[0] - 2 * margin
    story: list = []

    for el in elements:
        kind = el.get("type")
        if kind == "heading":
            level = min(max(int(el.get("level", 1) or 1), 1), 3)
            story.append(Paragraph(_esc(el.get("text", "")), styles[f"h{level}"]))
        elif kind == "paragraph":
            story.append(Paragraph(_esc(el.get("text", "")), styles["body"]))
        elif kind == "list":
            numbered = el.get("style") == "number"
            for i, item in enumerate(el.get("items", []), 1):
                marker = f"{i}." if numbered else "•"
                story.append(Paragraph(f"{marker} {_esc(item)}", styles["body"]))
        elif kind == "table":
            data = [el.get("header", []), *el.get("rows", [])]
            if data and any(any(str(c) for c in r) for r in data):
                story.append(_make_table(data, styles, avail_width))
                story.append(Spacer(1, 6))
        elif kind == "chart":
            # Data-table representation — honest content, no fake chart image.
            header = [el.get("chart", "chart"), *el.get("categories", [])]
            rows = [
                [s.get("name", ""), *[str(v) for v in s.get("values", [])]]
                for s in el.get("series", [])
            ]
            story.append(_make_table([header, *rows], styles, avail_width))
            story.append(Spacer(1, 6))
        elif kind == "image":
            story.append(_image_flowable(el, workspace_path))
            story.append(Spacer(1, 6))
        elif kind == "notes":
            story.append(Paragraph(_esc(el.get("text", "")), styles["note"]))
        elif kind == "page_break":
            story.append(PageBreak())
        else:
            story.append(Paragraph(f"[unsupported: {_esc(kind)}]", styles["note"]))

    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=letter,
        leftMargin=margin,
        rightMargin=margin,
        topMargin=margin,
        bottomMargin=margin,
    )
    doc.build(story)
    return buf.getvalue()
