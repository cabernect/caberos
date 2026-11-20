"""Native PowerPoint renderer for the shared presentation spec.

Content is never inferred from HTML. Layout fits structured objects within
readable type limits; raster fallbacks must be explicitly supplied.
"""

import base64
import hashlib
import textwrap
import unicodedata
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

from PIL import Image
from pptx import Presentation
from pptx.chart.data import CategoryChartData
from pptx.dml.color import RGBColor
from pptx.enum.chart import XL_CHART_TYPE, XL_LEGEND_POSITION
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_AUTO_SIZE, PP_ALIGN
from pptx.util import Inches, Pt

from ..sandbox.workspace import resolve_within
from .deck_spec import normalize

_WIDTH, _HEIGHT = 13.333333, 7.5
_LEFT, _CONTENT_W = 2 / 3, 12
_BODY_TOP, _BODY_BOTTOM = 1.55, 6.75
_LINE_SPACING, _BLOCK_GAP = 1.25, 0.14
_FONTS = {"sans": "Aptos", "serif": "Georgia", "mono": "Consolas"}
_MAX_IMAGE_BYTES = 4 * 1024 * 1024


class NativeLayoutError(ValueError):
    def __init__(self, slide_number: int, reason: str):
        self.reason = reason
        super().__init__(f"Slide {slide_number}: {reason}")


@dataclass
class _BlockBox:
    block: dict
    left: float
    top: float
    width: float
    height: float
    size: float
    row_heights: tuple[float, ...] = ()


@dataclass
class _SlideLayout:
    title_size: float
    title_top: float
    title_height: float
    blocks: list[_BlockBox]


def fallback_slides(spec: dict, workspace_path: str | Path | None = None) -> dict[int, str]:
    """Return exactly which slides need a raster fallback, and why."""
    normalized = normalize(spec)
    snapshots = {a["path"] for a in spec.get("assets", []) if a.get("data_uri")}
    reasons = {}
    for index, slide in enumerate(normalized["slides"]):
        if "html" in slide:
            reasons[index] = "HTML fragment has no structured PowerPoint equivalent"
        elif workspace_path is None and any(
            b.get("type") == "image"
            and not str(b.get("src", "")).startswith("data:")
            and b.get("src") not in snapshots
            for b in slide.get("blocks", [])
        ):
            reasons[index] = "Legacy deck has no pinned image snapshot in its source spec"
    return reasons


def _image_bytes(block: dict, spec: dict, workspace_path: str | Path | None) -> bytes:
    src = str(block.get("src", ""))
    snapshot = next((a for a in spec.get("assets", []) if a.get("path") == src), None)
    uri = snapshot.get("data_uri") if snapshot else src
    if isinstance(uri, str) and uri.startswith("data:image/"):
        try:
            header, encoded = uri.split(",", 1)
            if ";base64" not in header or len(encoded) > _MAX_IMAGE_BYTES * 4 // 3 + 4:
                raise ValueError("image encoding/size unsupported")
            data = base64.b64decode("".join(encoded.split()), validate=True)
        except (ValueError, TypeError) as exc:
            raise ValueError(f"invalid embedded image: {src[:60]}") from exc
    elif workspace_path is not None and not src.startswith("data:"):
        path = resolve_within(workspace_path, src)
        if path.stat().st_size > _MAX_IMAGE_BYTES:
            raise ValueError("image exceeds 4MB")
        data = path.read_bytes()
    else:
        raise ValueError("image has no pinned source bytes")
    if len(data) > _MAX_IMAGE_BYTES:
        raise ValueError("image exceeds 4MB")
    if snapshot and snapshot.get("sha256") != hashlib.sha256(data).hexdigest():
        raise ValueError("pinned image hash mismatch")
    with Image.open(BytesIO(data)) as image:
        if (
            image.format not in {"PNG", "JPEG", "GIF", "WEBP"}
            or image.width * image.height > 20_000_000
        ):
            raise ValueError("image format/dimensions unsupported")
        image.verify()
    return data


def _text_height(text: str, size: float, width: float) -> float:
    # Conservative word-wrap budget, not a native font measurement. NFC keeps
    # combining accents from consuming extra character slots in Vietnamese.
    chars_per_line = max(1, int(width * 72 / (size * 0.62)))
    lines = sum(
        max(
            1,
            len(
                textwrap.wrap(
                    unicodedata.normalize("NFC", line),
                    width=chars_per_line,
                    break_on_hyphens=False,
                )
            ),
        )
        for line in text.split("\n")
    )
    return lines * size * _LINE_SPACING / 72 + 0.08


def _block_text(block: dict) -> str:
    if block["type"] == "bullets":
        return "\n".join("\u2022 " + str(item) for item in block.get("items", []))
    return str(block.get("text", ""))


def _layout_slide(content: dict, images: dict, slide_number: int) -> _SlideLayout:
    cover = content["layout"] in {"title", "section"}
    columns = content["layout"] == "two_content"
    title = content.get("title", "")
    title_top = 0.65 if cover else 0.42
    title_sizes = range(38, 29, -2) if cover else range(30, 25, -1)
    titles = [
        (size, _text_height(title, size, _CONTENT_W) if title else 0)
        for size in title_sizes
        if not title or _text_height(title, size, _CONTENT_W) <= (2 if cover else 1.45)
    ]
    if not titles:
        raise NativeLayoutError(
            slide_number,
            "title exceeds the multiline title area; shorten it or split the slide",
        )
    # Preserve body readability first, then choose the largest title that fits.
    for body_size in range(20, 15, -1):
        for title_size, title_height in titles:
            body_top = (
                title_top + title_height + 0.3
                if cover
                else (max(_BODY_TOP, title_top + title_height + 0.35) if title else 0.6)
            )
            positions = [body_top, body_top]
            boxes = []
            for block in content.get("blocks", []):
                kind = block["type"]
                column = block.get("column", 0) if columns else 0
                width = (_CONTENT_W - 0.5) / 2 if columns else _CONTENT_W
                left = _LEFT + column * ((_CONTENT_W + 0.5) / 2)
                size = body_size + 4 if kind == "heading" else body_size
                heights = ()
                if kind in {"heading", "paragraph", "bullets"}:
                    height = _text_height(_block_text(block), size, width)
                elif kind == "table":
                    rows = block["rows"]
                    cols = max(map(len, rows))
                    if not 1 <= cols <= 12:
                        raise NativeLayoutError(slide_number, "native tables require 1-12 columns")
                    size = max(12, body_size - 6)
                    heights = tuple(
                        max(
                            (_text_height(str(c), size, width / cols - 0.16) for c in row),
                            default=_text_height("", size, width / cols - 0.16),
                        )
                        + 0.12
                        for row in rows
                    )
                    height = sum(heights)
                elif kind == "image":
                    ratio = images[block["id"]][1]
                    height = min(2.6, width * ratio)
                    image_width = height / ratio
                    if cover:
                        left += (width - image_width) / 2
                    width = image_width
                elif kind == "chart":
                    height = 2.9
                elif kind == "divider":
                    height = 0.16
                else:
                    raise NativeLayoutError(slide_number, f"unsupported structured block {kind!r}")
                boxes.append(
                    _BlockBox(block, left, positions[column], width, height, size, heights)
                )
                positions[column] += height + _BLOCK_GAP
            bottom = max((box.top + box.height for box in boxes), default=title_top + title_height)
            if bottom > _BODY_BOTTOM:
                continue
            if cover:
                offset = (_BODY_BOTTOM - bottom) / 2
                for box in boxes:
                    box.top += offset
                return _SlideLayout(title_size, title_top + offset, title_height, boxes)
            return _SlideLayout(title_size, title_top, title_height, boxes)
    raise NativeLayoutError(
        slide_number,
        "content exceeds the native slide at the 16 pt body / 12 pt table minimum; split the slide",
    )


def _format_text(frame, text: str, size: float, font: str, color: str, *, bold=False, center=False):
    frame.clear()
    frame.word_wrap = True
    frame.auto_size = MSO_AUTO_SIZE.NONE
    frame.margin_left = frame.margin_right = 0
    frame.margin_top = frame.margin_bottom = 0
    for index, line in enumerate(text.split("\n")):
        p = frame.paragraphs[0] if index == 0 else frame.add_paragraph()
        p.text = line
        p.font.name, p.font.size, p.font.bold = font, Pt(size), bold
        p.font.color.rgb = RGBColor.from_string(color.lstrip("#"))
        p.line_spacing = Pt(size * _LINE_SPACING)
        p.space_before = p.space_after = Pt(0)
        p.alignment = PP_ALIGN.CENTER if center else PP_ALIGN.LEFT


def _textbox(
    slide,
    text,
    y,
    height,
    size,
    font,
    color,
    *,
    bold=False,
    center=False,
    left=_LEFT,
    width=_CONTENT_W,
):
    box = slide.shapes.add_textbox(Inches(left), Inches(y), Inches(width), Inches(height))
    _format_text(box.text_frame, text, size, font, color, bold=bold, center=center)
    return box


def _bar(slide, y, width, accent, left=_LEFT):
    shape = slide.shapes.add_shape(
        MSO_SHAPE.RECTANGLE, Inches(left), Inches(y), Inches(width), Inches(0.045)
    )
    shape.fill.solid()
    shape.fill.fore_color.rgb = RGBColor.from_string(accent.lstrip("#"))
    shape.line.fill.background()


def build(
    spec: dict,
    workspace_path: str | Path | None = None,
    *,
    fallback_images: dict[int, bytes] | None = None,
    fallback_reasons: dict[int, str] | None = None,
) -> bytes:
    """Shared spec -> editable text/tables/pictures. Never reads live assets on export."""
    model = normalize(spec)
    fallback_images = fallback_images or {}
    reasons = (
        fallback_reasons if fallback_reasons is not None else fallback_slides(spec, workspace_path)
    )
    missing = set(reasons) - set(fallback_images)
    if missing:
        raise ValueError(
            "Image fallback required for slides " + ", ".join(str(i + 1) for i in sorted(missing))
        )
    if set(fallback_images) - set(reasons):
        raise ValueError("image fallback supplied for a natively supported slide")
    prs = Presentation()
    prs.slide_width, prs.slide_height = Inches(_WIDTH), Inches(_HEIGHT)
    theme = model["theme"]
    background = theme.get("background", "#ffffff")
    accent = theme.get("accent", "#3f6212")
    color = theme.get("text", "#1c1917")
    font = _FONTS[theme.get("font", "sans")]
    prs.core_properties.title = model["title"]
    total_image_bytes = 0
    for index, content in enumerate(model["slides"]):
        if index in reasons:
            slide = prs.slides.add_slide(prs.slide_layouts[6])
            slide.shapes.add_picture(
                BytesIO(fallback_images[index]),
                0,
                0,
                width=prs.slide_width,
                height=prs.slide_height,
            )
        else:
            images = {}
            for block in content.get("blocks", []):
                if block["type"] == "image":
                    data = _image_bytes(block, spec, workspace_path)
                    total_image_bytes += len(data)
                    if total_image_bytes > 25 * 1024 * 1024:
                        raise ValueError("native deck images exceed 25MB")
                    with Image.open(BytesIO(data)) as image:
                        images[block["id"]] = (data, image.height / image.width)
            layout = _layout_slide(content, images, index + 1)
            slide = prs.slides.add_slide(prs.slide_layouts[5])
            slide.background.fill.solid()
            slide.background.fill.fore_color.rgb = RGBColor.from_string(background.lstrip("#"))
            cover = content.get("layout") in {"title", "section"}
            title = str(content.get("title", ""))
            title_box = slide.shapes.title
            title_box.left, title_box.top = Inches(_LEFT), Inches(layout.title_top)
            title_box.width, title_box.height = Inches(_CONTENT_W), Inches(layout.title_height)
            _format_text(
                title_box.text_frame, title, layout.title_size, font, color, bold=True, center=cover
            )
            if title:
                _bar(
                    slide,
                    layout.title_top + layout.title_height + 0.12,
                    0.7,
                    accent,
                    left=(_WIDTH - 0.7) / 2 if cover else _LEFT,
                )
            for box in layout.blocks:
                block = box.block
                left, y, width, height = box.left, box.top, box.width, box.height
                kind = block.get("type")
                if kind in {"paragraph", "heading", "bullets"}:
                    _textbox(
                        slide,
                        _block_text(block),
                        y,
                        height,
                        box.size,
                        font,
                        color,
                        bold=kind == "heading",
                        center=cover,
                        left=left,
                        width=width,
                    )
                elif kind == "divider":
                    _bar(slide, y, 0.7, accent, left=left)
                elif kind == "table":
                    rows = block["rows"]
                    cols = max(map(len, rows))
                    shape = slide.shapes.add_table(
                        len(rows),
                        cols,
                        Inches(left),
                        Inches(y),
                        Inches(width),
                        Inches(height),
                    )
                    for r, row in enumerate(rows):
                        shape.table.rows[r].height = Inches(box.row_heights[r])
                        for c in range(cols):
                            cell = shape.table.cell(r, c)
                            cell.margin_left = cell.margin_right = Inches(0.08)
                            cell.margin_top = cell.margin_bottom = Inches(0.06)
                            cell.fill.solid()
                            cell.fill.fore_color.rgb = RGBColor.from_string(
                                (accent if r == 0 else background).lstrip("#")
                            )
                            _format_text(
                                cell.text_frame,
                                str(row[c]) if c < len(row) else "",
                                box.size,
                                font,
                                background if r == 0 else color,
                                bold=r == 0,
                            )
                elif kind == "image":
                    slide.shapes.add_picture(
                        BytesIO(images[block["id"]][0]),
                        Inches(left),
                        Inches(y),
                        width=Inches(width),
                        height=Inches(height),
                    )
                elif kind == "chart":
                    chart_data = CategoryChartData()
                    chart_data.categories = block["categories"]
                    for series in block["series"]:
                        chart_data.add_series(series["name"], series["values"])
                    chart_type = {
                        "bar": XL_CHART_TYPE.COLUMN_CLUSTERED,
                        "line": XL_CHART_TYPE.LINE_MARKERS,
                        "pie": XL_CHART_TYPE.PIE,
                    }[block.get("chart_type", "bar")]
                    chart = slide.shapes.add_chart(
                        chart_type,
                        Inches(left),
                        Inches(y),
                        Inches(width),
                        Inches(height),
                        chart_data,
                    ).chart
                    chart.has_legend = len(block["series"]) > 1 or block.get("chart_type") == "pie"
                    if chart.has_legend:
                        chart.legend.position = XL_LEGEND_POSITION.BOTTOM
                        chart.legend.font.size = Pt(11)
            _textbox(
                slide,
                f"{model['title']}  |  {index + 1} / {len(model['slides'])}",
                7,
                0.25,
                9,
                font,
                color,
            )
        slide.notes_slide.notes_text_frame.text = str(content.get("notes") or "")
    out = BytesIO()
    prs.save(out)
    return out.getvalue()


def export_pptx(
    spec: dict,
    *,
    source_sha256: str,
    revision_id: str | None,
    fallback_images: dict[int, bytes] | None = None,
    fallback_reasons: dict[int, str] | None = None,
) -> bytes:
    """Spec -> native PPTX bytes with source provenance stamped in."""
    data = build(spec, fallback_images=fallback_images, fallback_reasons=fallback_reasons)
    prs = Presentation(BytesIO(data))
    indices = sorted(fallback_images or {})
    fallback_label = ", ".join(str(i + 1) for i in indices) or "none"
    prs.core_properties.subject = "Presentation spec export"
    prs.core_properties.comments = (
        f"Spec export; sha256 {source_sha256}; rev {revision_id or 'live'}; "
        f"image slides {fallback_label}"
    )[:255]
    out = BytesIO()
    prs.save(out)
    from .deck_metadata import stamp

    return stamp(
        out.getvalue(),
        {
            "source_sha256": source_sha256,
            "revision_id": revision_id,
            "renderer": "caberos-native-pptx-3",
            "browser_motion_exported": False,
            "theme_sha256": hashlib.sha256(
                str(sorted(spec.get("theme", {}).items())).encode()
            ).hexdigest(),
            "assets": [{k: a.get(k) for k in ("path", "sha256")} for a in spec.get("assets", [])],
            "image_fallbacks": [
                {"slide": i + 1, "reason": (fallback_reasons or {}).get(i, "image fallback")}
                for i in indices
            ],
        },
    )
