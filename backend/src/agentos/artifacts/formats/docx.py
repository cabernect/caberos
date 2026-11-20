"""DOCX handler — python-docx structured build/revise/inspect/validate.

The model passes a block spec; this module owns the Office XML. Validation
reopens the file through zip + XML parsing independent of the writer path.
"""

import re
import zipfile
from io import BytesIO
from pathlib import Path
from xml.etree import ElementTree

from docx import Document
from docx.enum.section import WD_SECTION
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor

from ...sandbox.workspace import resolve_within

_PAGE_SIZES = {
    "letter": (8.5, 11),
    "legal": (8.5, 14),
    "a4": (8.2677165, 11.6929134),
}
# Named style roles an author may override. Heading levels accept h1-h6
# per-level overrides on top of the shared "heading" role.
_STYLE_ROLES = {"title", "heading", "body", "list", "caption", "table"}
_STYLE_KEYS = {"font", "size", "color", "bold", "italic"}
_SPACING_KEYS = {"space_before", "space_after", "line_spacing"}
_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
_MAX_BLOCKS = 500
_MAX_IMAGE_INCHES = 20

# Named template subset (W3 slice 6): each preset is a bounded {page, styles}
# bundle. Explicit spec page/styles keys override template values per-key.
_TEMPLATES = {
    "memo": {
        "page": {"size": "letter", "margins": {"top": 1, "bottom": 1, "left": 1, "right": 1}},
        "styles": {
            "body": {"font": "Aptos", "size": 11, "space_after": 6},
            "heading": {"font": "Aptos Display", "size": 14, "color": "#1c1917"},
        },
    },
    "report": {
        "page": {
            "size": "letter",
            "margins": {"top": 1.2, "bottom": 1.2, "left": 1.2, "right": 1.2},
        },
        "styles": {
            "title": {"font": "Georgia", "size": 30, "color": "#1c1917"},
            "heading": {"font": "Georgia", "size": 18, "color": "#3f6212", "space_after": 10},
            "body": {"font": "Aptos", "size": 11, "line_spacing": 1.25},
            "caption": {"size": 9, "italic": True},
        },
    },
    "letter": {
        "page": {
            "size": "letter",
            "margins": {"top": 1.2, "bottom": 1.2, "left": 1.2, "right": 1.2},
        },
        "styles": {
            "body": {"font": "Times New Roman", "size": 12, "line_spacing": 1.15},
            "heading": {"font": "Times New Roman", "size": 14, "bold": True},
        },
    },
}


def _merge_spec(base: dict, override: dict) -> dict:
    """Deep-merge page/styles dicts: override wins per leaf key."""
    out = {k: dict(v) if isinstance(v, dict) else v for k, v in base.items()}
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            merged = dict(out[key])
            merged.update(value)
            out[key] = merged
        else:
            out[key] = value
    return out


def _validate_spec(spec: dict) -> None:
    """Bounded create-spec validation — bad styles fail before any bytes."""
    if not isinstance(spec, dict):
        raise ValueError("docx spec must be an object")
    if "title" in spec and not isinstance(spec["title"], str):
        raise ValueError("docx title must be plain text")
    if "template" in spec and spec["template"] not in _TEMPLATES:
        raise ValueError(f"template must be one of {sorted(_TEMPLATES)}")
    blocks = spec.get("blocks", [])
    if not isinstance(blocks, list) or len(blocks) > _MAX_BLOCKS:
        raise ValueError(f"docx needs at most {_MAX_BLOCKS} blocks")
    for i, block in enumerate(blocks):
        _validate_block(block, i)

    if "page" in spec:
        _validate_page(spec["page"], "page")
    for key in ("header", "footer"):
        if key in spec:
            _validate_header_footer(spec[key], f"docx {key}")

    styles = spec.get("styles", {})
    if not isinstance(styles, dict):
        raise ValueError("styles must be an object of named roles")
    for role, style in styles.items():
        if role not in _STYLE_ROLES and not re.fullmatch(r"h[1-6]", str(role)):
            raise ValueError(f"unknown style role: {role!r}")
        if not isinstance(style, dict):
            raise ValueError(f"style {role} must be an object")
        if set(style) - _STYLE_KEYS - _SPACING_KEYS:
            raise ValueError(f"style {role} has unsupported keys")
        if role == "table" and set(style) & _SPACING_KEYS:
            raise ValueError("style table does not support spacing keys")
        if "font" in style and (not isinstance(style["font"], str) or not style["font"].strip()):
            raise ValueError(f"style {role}.font must be a font name")
        if "size" in style and (
            type(style["size"]) not in (int, float) or not 6 <= style["size"] <= 96
        ):
            raise ValueError(f"style {role}.size must be 6-96 points")
        if "color" in style and (
            not isinstance(style["color"], str) or not _COLOR_RE.match(style["color"])
        ):
            raise ValueError(f"style {role}.color must be #RRGGBB")
        for flag in ("bold", "italic"):
            if flag in style and not isinstance(style[flag], bool):
                raise ValueError(f"style {role}.{flag} must be true or false")
        for key in ("space_before", "space_after"):
            if key in style and (type(style[key]) not in (int, float) or not 0 <= style[key] <= 72):
                raise ValueError(f"style {role}.{key} must be 0-72 points")
        if "line_spacing" in style and (
            type(style["line_spacing"]) not in (int, float) or not 0.8 <= style["line_spacing"] <= 3
        ):
            raise ValueError(f"style {role}.line_spacing must be 0.8-3")


def _apply_text_style(style, spec: dict) -> None:
    font = style.font
    if "font" in spec:
        font.name = spec["font"]
    if "size" in spec:
        font.size = Pt(spec["size"])
    if "color" in spec:
        font.color.rgb = RGBColor.from_string(spec["color"].lstrip("#"))
    if "bold" in spec:
        font.bold = spec["bold"]
    if "italic" in spec:
        font.italic = spec["italic"]
    fmt = style.paragraph_format
    if "space_before" in spec:
        fmt.space_before = Pt(spec["space_before"])
    if "space_after" in spec:
        fmt.space_after = Pt(spec["space_after"])
    if "line_spacing" in spec:
        fmt.line_spacing = spec["line_spacing"]


def _apply_styles(doc, styles: dict) -> None:
    named = {
        "title": ["Title"],
        "heading": [f"Heading {i}" for i in range(1, 7)],
        "body": ["Normal"],
        "list": ["List Bullet", "List Number"],
        "caption": ["Caption"],
    }
    for role, style_names in named.items():
        if role not in styles:
            continue
        for name in style_names:
            if name in doc.styles:
                _apply_text_style(doc.styles[name], styles[role])
    for level in range(1, 7):
        override = styles.get(f"h{level}")
        name = f"Heading {level}"
        if override and name in doc.styles:
            _apply_text_style(doc.styles[name], override)


def _apply_page(section, page: dict) -> None:
    size = _PAGE_SIZES.get(page.get("size", "letter"))
    section.page_width, section.page_height = Inches(size[0]), Inches(size[1])
    margins = {"top": 1, "bottom": 1, "left": 1, "right": 1, **page.get("margins", {})}
    section.top_margin = Inches(margins["top"])
    section.bottom_margin = Inches(margins["bottom"])
    section.left_margin = Inches(margins["left"])
    section.right_margin = Inches(margins["right"])


def _apply_page_overrides(section, page: dict) -> None:
    """Section-break page overrides: only the keys the author set."""
    if "size" in page:
        w, h = _PAGE_SIZES[page["size"]]
        section.page_width, section.page_height = Inches(w), Inches(h)
    for side, attr in (
        ("top", "top_margin"),
        ("bottom", "bottom_margin"),
        ("left", "left_margin"),
        ("right", "right_margin"),
    ):
        if side in page.get("margins", {}):
            setattr(section, attr, Inches(page["margins"][side]))


def _add_field(paragraph, instruction: str, cached: str) -> None:
    """Insert a Word field (PAGE/NUMPAGES) with a cached display value.

    Word recalculates the cached value on open/print — the stored number is a
    placeholder, not a computed page count."""
    fld = OxmlElement("w:fldSimple")
    fld.set(qn("w:instr"), f" {instruction} ")
    run = OxmlElement("w:r")
    text = OxmlElement("w:t")
    text.text = cached
    run.append(text)
    fld.append(run)
    paragraph._p.append(fld)


def _fill_header_footer(container, hf: dict) -> None:
    align = {
        "left": WD_ALIGN_PARAGRAPH.LEFT,
        "center": WD_ALIGN_PARAGRAPH.CENTER,
        "right": WD_ALIGN_PARAGRAPH.RIGHT,
    }[hf.get("align", "left")]
    # Reuse the container's first paragraph — headers/footers start with one
    # empty paragraph; adding another leaves a stray blank line.
    p = container.paragraphs[0] if container.paragraphs else container.add_paragraph()
    p.alignment = align
    if hf.get("text"):
        p.add_run(hf["text"])
    if hf.get("page_numbers"):
        _add_field(p, "PAGE", "1")
    if hf.get("total_pages"):
        if hf.get("page_numbers"):
            p.add_run(" of ")
        _add_field(p, "NUMPAGES", "1")


def _apply_keep_flags(paragraph, block: dict) -> None:
    fmt = paragraph.paragraph_format
    if block.get("keep_with_next"):
        fmt.keep_with_next = True
    if block.get("page_break_before"):
        fmt.page_break_before = True


def _fit_picture(doc, img_path: Path, block: dict):
    """Add a picture sized by exactly one of width/height/fit, preserving
    the image's natural aspect ratio."""
    from docx.image.image import Image as DocxImage

    if "fit" in block:
        im = DocxImage.from_file(str(img_path))
        w_in = im.px_width / im.horz_dpi if im.horz_dpi else im.width / 914400
        h_in = im.px_height / im.vert_dpi if im.vert_dpi else im.height / 914400
        scale = min(block["fit"].get("width", w_in) / w_in, block["fit"].get("height", h_in) / h_in)
        return doc.add_picture(str(img_path), width=Inches(w_in * scale))
    if "height_inches" in block:
        return doc.add_picture(str(img_path), height=Inches(block["height_inches"]))
    return doc.add_picture(str(img_path), width=Inches(block.get("width_inches", 4)))


def build(spec: dict, workspace_path: str | Path) -> bytes:
    _validate_spec(spec)
    doc = Document()
    # US Letter + uniform 1" margins — set explicit defaults rather than
    # whatever the python-docx template happens to ship.
    template = _TEMPLATES.get(spec.get("template", ""), {})
    page_spec = _merge_spec(template.get("page", {}), spec.get("page", {}))
    style_spec = _merge_spec(template.get("styles", {}), spec.get("styles", {}))
    first = doc.sections[0]
    _apply_page(first, page_spec)
    if spec.get("header"):
        _fill_header_footer(first.header, spec["header"])
    if spec.get("footer"):
        _fill_header_footer(first.footer, spec["footer"])
    if style_spec:
        _apply_styles(doc, style_spec)
    table_style = style_spec.get("table", {})
    blocks = spec.get("blocks", [])
    has_cover = any(isinstance(b, dict) and b.get("type") == "cover" for b in blocks)
    title = spec.get("title")
    if title and not has_cover:
        doc.add_heading(title, level=0)
    if spec.get("template"):
        # Provenance inside the file itself: python-docx has no custom
        # properties API, so the named template rides in subject.
        doc.core_properties.subject = f"caberos-template:{spec['template']}"
    seen_ids: set[str] = set()
    next_id = _bookmark_id_counter(doc)
    for i, block in enumerate(blocks):
        bid = block.get("id") or f"b{i}"
        if bid in seen_ids:
            raise ValueError(f"duplicate block id: {bid}")
        seen_ids.add(bid)
        start, end = _block_anchors(doc, block, workspace_path, table_style, doc_title=title)
        next_id = _tag_block(doc, start, end, f"{_BOOKMARK_PREFIX}{bid}"[:40], next_id)
    buf = BytesIO()
    doc.save(buf)
    return buf.getvalue()


_STYLE_BLOCK_KEYS = {
    "bold",
    "italic",
    "size",
    "color",
    "font",
    "keep_with_next",
    "page_break_before",
}


def _bookmark_element(doc, name: str):
    for tag in ("w:bookmarkStart", "w:bookmarkEnd"):
        for el in doc.element.body.iter(qn(tag)):
            if el.get(qn("w:name")) == name:
                return el
    return None


def _body_top(el, body):
    while el.getparent() is not body:
        el = el.getparent()
    return el


def _block_body_range(doc, bid: str):
    """(first, last) body-level elements spanned by a block's bookmark."""
    name = f"{_BOOKMARK_PREFIX}{bid}"[:40]
    start = _bookmark_element(doc, name)
    if start is None or start.tag != qn("w:bookmarkStart"):
        raise ValueError(f"no block with id: {bid}")
    end = None
    for el in doc.element.body.iter(qn("w:bookmarkEnd")):
        if el.get(qn("w:name")) == name:
            end = el
            break
    if end is None:
        raise ValueError(f"block {bid} has a bookmarkStart but no bookmarkEnd")
    body = doc.element.body
    return _body_top(start, body), _body_top(end, body)


def _iter_range_paragraphs(doc, start_el, end_el):
    """All w:p paragraphs across body-level elements start_el..end_el,
    including table cell paragraphs."""
    from docx.table import Table as DocxTable
    from docx.text.paragraph import Paragraph as DocxParagraph

    cur = start_el
    while True:
        if cur.tag == qn("w:p"):
            yield DocxParagraph(cur, doc)
        elif cur.tag == qn("w:tbl"):
            for row in DocxTable(cur, doc).rows:
                for cell in row.cells:
                    yield from cell.paragraphs
        if cur is end_el:
            return
        cur = cur.getnext()
        if cur is None:
            raise ValueError("block range is not contiguous in document body")


def _existing_bookmark_names(doc) -> set[str]:
    return {el.get(qn("w:name")) for el in doc.element.body.iter(qn("w:bookmarkStart"))}


def _append_tagged_blocks(doc, blocks: list[dict], workspace_path) -> list:
    """Build blocks at the document end (python-docx appends before sectPr),
    tag bookmarks, and return the new body-level elements."""
    body = doc.element.body
    before = set(body)
    next_id = _bookmark_id_counter(doc)
    existing = _existing_bookmark_names(doc)
    n = 0
    for block in blocks:
        _validate_block(block, len(doc.paragraphs))
        bid = block.get("id")
        if not bid:
            while f"{_BOOKMARK_PREFIX}x{n}" in existing:
                n += 1
            bid = f"x{n}"
            n += 1
        name = f"{_BOOKMARK_PREFIX}{bid}"[:40]
        if name in existing:
            raise ValueError(f"block id already exists: {bid}")
        start, end = _block_anchors(doc, block, workspace_path)
        next_id = _tag_block(doc, start, end, name, next_id)
        existing.add(name)
    return [el for el in body if el not in before]


def _op_insert_blocks(doc, op: dict, workspace_path) -> None:
    blocks = op.get("blocks")
    if not isinstance(blocks, list) or not blocks:
        raise ValueError("insert_blocks needs a non-empty blocks list")
    for b in blocks:
        if isinstance(b, dict) and b.get("type") == "section_break":
            raise ValueError("section_break cannot be inserted mid-document")
    created = _append_tagged_blocks(doc, blocks, workspace_path)
    position = op.get("position", "end")
    anchor = None
    if position == "start":
        anchor = next(
            (el for el in doc.element.body if el.tag in (qn("w:p"), qn("w:tbl"))),
            None,
        )
    elif "after" in op or "before" in op:
        key = "after" if "after" in op else "before"
        first, last = _block_body_range(doc, op[key])
        anchor = last if key == "after" else first
        position = key
    elif position != "end":
        raise ValueError("insert_blocks position must be start/end or use after/before")
    if anchor is None:
        return  # appended at end already
    if position == "start" or position == "before":
        for el in created:
            anchor.addprevious(el)
    else:
        for el in reversed(created):
            anchor.addnext(el)


def _op_remove_block(doc, op: dict) -> None:
    first, last = _block_body_range(doc, op["block"])
    body = doc.element.body
    cur = first
    while True:
        nxt = cur.getnext()
        body.remove(cur)
        if cur is last:
            break
        cur = nxt
        if cur is None:
            raise ValueError("block range is not contiguous in document body")


def _op_style_block(doc, op: dict) -> None:
    keys = set(op) - {"op", "block"}
    if not keys or keys - _STYLE_BLOCK_KEYS:
        raise ValueError(f"style_block accepts only {sorted(_STYLE_BLOCK_KEYS)}")
    first, last = _block_body_range(doc, op["block"])
    color = op.get("color")
    if color is not None and not _COLOR_RE.match(str(color)):
        raise ValueError("style_block.color must be #RRGGBB")
    size = op.get("size")
    if size is not None and (type(size) not in (int, float) or not 6 <= size <= 96):
        raise ValueError("style_block.size must be 6-96 points")
    for para in _iter_range_paragraphs(doc, first, last):
        for run in para.runs:
            if "bold" in op:
                run.font.bold = op["bold"]
            if "italic" in op:
                run.font.italic = op["italic"]
            if "size" in op:
                run.font.size = Pt(op["size"])
            if "color" in op:
                run.font.color.rgb = RGBColor.from_string(str(color).lstrip("#"))
            if "font" in op:
                run.font.name = op["font"]
        fmt = para.paragraph_format
        if "keep_with_next" in op:
            fmt.keep_with_next = bool(op["keep_with_next"])
        if "page_break_before" in op:
            fmt.page_break_before = bool(op["page_break_before"])


def _table_index_by_block_id(doc, bid: str) -> int:
    name = f"{_BOOKMARK_PREFIX}{bid}"[:40]
    for i, table in enumerate(doc.tables):
        if any(bm.get(qn("w:name")) == name for bm in table._tbl.iter(qn("w:bookmarkStart"))):
            return i
    raise ValueError(f"no table block with id: {bid}")


def revise(data: bytes, ops: list[dict], workspace_path: str | Path) -> bytes:
    doc = Document(BytesIO(data))
    for op in ops:
        kind = op["op"]
        if kind == "append_blocks":
            _append_tagged_blocks(doc, op["blocks"], workspace_path)
        elif kind == "replace_paragraph":
            if "block" in op:
                idx = _paragraph_index_by_block_id(doc, op["block"])
            else:
                idx = op["index"]
            _set_paragraph_text(doc.paragraphs[idx], op["text"])
        elif kind == "set_cell":
            t, r, c = op["table"], op["row"], op["col"]
            if isinstance(t, str):
                t = _table_index_by_block_id(doc, t)
            _set_cell_text(doc.tables[t].rows[r].cells[c], op["text"])
        elif kind == "insert_blocks":
            _op_insert_blocks(doc, op, workspace_path)
        elif kind == "remove_block":
            _op_remove_block(doc, op)
        elif kind == "style_block":
            _op_style_block(doc, op)
        else:
            raise ValueError(f"unknown docx op: {kind}")
    buf = BytesIO()
    doc.save(buf)
    return buf.getvalue()


def _bookmark_name(el) -> str | None:
    for bm in el.iter(qn("w:bookmarkStart")):
        name = bm.get(qn("w:name"))
        if name and name.startswith(_BOOKMARK_PREFIX):
            return name[len(_BOOKMARK_PREFIX) :]
    return None


def _inspect_blocks(doc) -> list[dict]:
    """Addressable block list in document order. `id` is the stable bookmark
    id (None for content without one, e.g. imported documents)."""
    from docx.table import Table as DocxTable
    from docx.text.paragraph import Paragraph as DocxParagraph

    blocks: list[dict] = []
    table_i = 0
    for child in doc.element.body.iterchildren():
        if child.tag.endswith("}p"):
            p = DocxParagraph(child, doc)
            style = p.style.name if p.style is not None else ""
            bid = _bookmark_name(child)
            kind = (
                "heading"
                if style == "Title" or style.startswith("Heading")
                else "list"
                if style.startswith("List")
                else "caption"
                if style == "Caption"
                else "paragraph"
            )
            blocks.append(
                {
                    "id": bid,
                    "kind": kind,
                    "style": style,
                    "index": len([b for b in blocks]),
                    "preview": p.text[:80],
                }
            )
        elif child.tag.endswith("}tbl"):
            t = DocxTable(child, doc)
            first_row = [c.text for c in t.rows[0].cells] if t.rows else []
            bid = _bookmark_name(child)
            blocks.append(
                {
                    "id": bid,
                    "kind": "table",
                    "style": "Table Grid",
                    "index": table_i,
                    "preview": " | ".join(first_row)[:80],
                }
            )
            table_i += 1
    # Re-number paragraph indexes across the whole block list.
    for i, b in enumerate(blocks):
        b["index"] = i
    return blocks


def _diagnostics(doc) -> list[str]:
    """Heuristic content diagnostics — labels, not Word pagination proof."""
    out: list[str] = []
    prev_level = 0
    for p in doc.paragraphs:
        style = p.style.name if p.style is not None else ""
        if style == "Title":
            level = 0
        elif style.startswith("Heading") and style[-1:].isdigit():
            level = int(style[-1])
        else:
            continue
        if level and prev_level and level > prev_level + 1:
            out.append(f"heading-level-jump: {style} follows a level-{prev_level} heading")
        if level:
            prev_level = level
        if not p.text.strip():
            out.append(f"empty-heading: {style} has no text")
    for i, table in enumerate(doc.tables):
        section = doc.sections[0]
        avail = section.page_width - section.left_margin - section.right_margin
        widths = []
        for col in table.columns:
            try:
                widths.append(col.width)
            except Exception:
                pass
        if widths and sum(widths) > avail * 1.02:
            out.append(
                f"wide-table: table {i} is ~{sum(widths).inches:.1f}in "
                f"vs {avail.inches:.1f}in text width"
            )
    return out


def _set_paragraph_text(para, text: str) -> None:
    """Replace paragraph text while preserving bookmark anchors.

    `paragraph.text = ...` clears every content child, including the
    bookmarkStart/bookmarkEnd elements that carry stable block ids — save and
    reinsert them so revisions don't silently unaddress blocks. Run-level
    formatting inside the paragraph is still replaced (documented limit)."""
    p = para._p
    starts = [el for el in p.iter(qn("w:bookmarkStart"))]
    ends = [el for el in p.iter(qn("w:bookmarkEnd"))]
    for el in [*starts, *ends]:
        el.getparent().remove(el)
    para.text = text
    ppr = p.find(qn("w:pPr"))
    insert_at = list(p).index(ppr) + 1 if ppr is not None else 0
    for el in starts:
        p.insert(insert_at, el)
        insert_at += 1
    for el in ends:
        p.append(el)


def _set_cell_text(cell, text: str) -> None:
    """set_cell equivalent that preserves bookmark anchors — cell.text would
    drop them and could leave a dangling bookmarkEnd."""
    tc = cell._tc
    paras = [el for el in tc if el.tag == qn("w:p")]
    first = cell.paragraphs[0]
    orphans: list = []
    for extra in paras[1:]:
        orphans.extend(
            el for el in extra.iter() if el.tag in (qn("w:bookmarkStart"), qn("w:bookmarkEnd"))
        )
        tc.remove(extra)
    _set_paragraph_text(first, text)
    # Rehome any bookmark markers that lived in removed paragraphs.
    p = first._p
    ppr = p.find(qn("w:pPr"))
    insert_at = list(p).index(ppr) + 1 if ppr is not None else 0
    for el in orphans:
        if el.tag == qn("w:bookmarkStart"):
            p.insert(insert_at, el)
            insert_at += 1
        else:
            p.append(el)


def _paragraph_index_by_block_id(doc, bid: str) -> int:
    """Resolve a stable block id to a top-level paragraph index.

    Bookmarks inside tables/cells do not map to doc.paragraphs — callers get
    a clear error instead of a wrong paragraph."""
    name = f"{_BOOKMARK_PREFIX}{bid}"[:40]
    for i, p in enumerate(doc.paragraphs):
        if any(bm.get(qn("w:name")) == name for bm in p._p.iter(qn("w:bookmarkStart"))):
            return i
    raise ValueError(f"no paragraph block with id: {bid}")


def inspect(data: bytes) -> dict:
    doc = Document(BytesIO(data))
    headings, paragraphs, list_items = [], 0, 0
    for p in doc.paragraphs:
        if p.style.name.startswith("Heading"):
            headings.append(p.text)
        elif p.style.name.startswith("List"):
            list_items += 1
        elif p.text.strip():
            paragraphs += 1
    blocks = _inspect_blocks(doc)
    subject = doc.core_properties.subject or ""
    template = (
        subject.removeprefix("caberos-template:")
        if subject.startswith("caberos-template:")
        else None
    )
    return {
        "diagnostics": _diagnostics(doc),
        "structure": {
            "template": template,
            "headings": headings,
            "paragraphs": paragraphs,
            "list_items": list_items,
            "tables": len(doc.tables),
            "images": len(doc.inline_shapes),
            "sections": [
                {
                    "index": i,
                    "header_linked": sec.header.is_linked_to_previous,
                    "footer_linked": sec.footer.is_linked_to_previous,
                }
                for i, sec in enumerate(doc.sections)
            ],
            "blocks": blocks,
        },
    }


def validate(data: bytes) -> dict:
    """Reopen via zip structure + XML parse — independent of the writer."""
    errors: list[str] = []
    try:
        zf = zipfile.ZipFile(BytesIO(data))
        if zf.testzip() is not None:
            errors.append("corrupt zip member")
        names = set(zf.namelist())
        for required in ("[Content_Types].xml", "word/document.xml"):
            if required not in names:
                errors.append(f"missing part: {required}")
        if "word/document.xml" in names:
            ElementTree.fromstring(zf.read("word/document.xml"))
    except zipfile.BadZipFile:
        errors.append("not a zip container")
    except ElementTree.ParseError as e:
        errors.append(f"document.xml not well-formed: {e}")
    if not errors:
        try:
            Document(BytesIO(data))
        except Exception as e:
            errors.append(f"parser reopen failed: {e}")
    return {"valid": not errors, "errors": errors}


def to_elements(data: bytes, workspace_path: str | Path) -> list[dict]:
    """Extract the normalized render elements (pdf_render vocabulary) from
    docx bytes — paragraphs/tables/images in document order."""
    from docx.table import Table as DocxTable
    from docx.text.paragraph import Paragraph as DocxParagraph

    doc = Document(BytesIO(data))
    elements: list[dict] = []
    rels = doc.part.related_parts
    embed = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}embed"

    for child in doc.element.body.iterchildren():
        if child.tag.endswith("}p"):
            p = DocxParagraph(child, doc)
            style = p.style.name if p.style is not None else ""
            if style == "Title" or style.startswith("Heading"):
                level = int(style[-1]) if style[-1:].isdigit() else 1
                elements.append({"type": "heading", "text": p.text, "level": level})
            elif style.startswith("List"):
                elements.append(
                    {
                        "type": "list",
                        "style": "number" if "Number" in style else "bullet",
                        "items": [p.text],
                    }
                )
            elif p.text.strip():
                elements.append({"type": "paragraph", "text": p.text})
            for blip in child.xpath('.//*[local-name()="blip"]'):
                rid = blip.get(embed)
                if rid and rid in rels:
                    elements.append({"type": "image", "data": rels[rid].blob})
        elif child.tag.endswith("}tbl"):
            t = DocxTable(child, doc)
            rows = [[c.text for c in r.cells] for r in t.rows]
            if rows:
                elements.append({"type": "table", "header": rows[0], "rows": rows[1:]})

    # Merge consecutive same-style lists so numbering continues correctly.
    merged: list[dict] = []
    for el in elements:
        if (
            el["type"] == "list"
            and merged
            and merged[-1]["type"] == "list"
            and merged[-1].get("style") == el.get("style")
        ):
            merged[-1]["items"].extend(el["items"])
        else:
            merged.append(el)
    return merged


_BLOCK_TYPES = {
    "heading",
    "paragraph",
    "list",
    "table",
    "image",
    "page_break",
    "caption",
    "cover",
    "section_break",
}
_KEEP_KEYS = {"keep_with_next", "page_break_before"}
_HEADER_FOOTER_KEYS = {"text", "align", "page_numbers", "total_pages"}
_ALIGNS = {"left", "center", "right"}


def _validate_page(page: dict, label: str) -> None:
    if not isinstance(page, dict) or set(page) - {"size", "margins"}:
        raise ValueError(f"{label} accepts only size and margins")
    if "size" in page and page["size"] not in _PAGE_SIZES:
        raise ValueError(f"{label}.size must be one of {sorted(_PAGE_SIZES)}")
    margins = page.get("margins", {})
    if not isinstance(margins, dict) or set(margins) - {"top", "bottom", "left", "right"}:
        raise ValueError(f"{label}.margins accepts top/bottom/left/right in inches")
    for side, value in margins.items():
        if type(value) not in (int, float) or not 0.3 <= value <= 2.5:
            raise ValueError(f"{label} margin {side} must be 0.3-2.5 inches")


def _validate_header_footer(hf: dict, label: str) -> None:
    if not isinstance(hf, dict) or set(hf) - _HEADER_FOOTER_KEYS:
        raise ValueError(f"{label} accepts only text/align/page_numbers/total_pages")
    if "text" in hf and not isinstance(hf["text"], str):
        raise ValueError(f"{label}.text must be plain text")
    if "align" in hf and hf["align"] not in _ALIGNS:
        raise ValueError(f"{label}.align must be one of {sorted(_ALIGNS)}")
    for flag in ("page_numbers", "total_pages"):
        if flag in hf and not isinstance(hf[flag], bool):
            raise ValueError(f"{label}.{flag} must be true or false")


def _inches(value, label: str) -> float:
    if type(value) not in (int, float) or not 0 < value <= _MAX_IMAGE_INCHES:
        raise ValueError(f"{label} must be 0-{_MAX_IMAGE_INCHES} inches")
    return float(value)


def _validate_block(block: dict, index: int) -> None:
    label = f"block {index}"
    if not isinstance(block, dict) or block.get("type") not in _BLOCK_TYPES:
        raise ValueError(f"{label} has an unsupported type")
    kind = block["type"]
    if kind == "heading" and block.get("level", 1) not in range(0, 7):
        raise ValueError(f"{label} heading level must be 0-6")
    if kind == "image":
        dims = [k for k in ("width_inches", "height_inches", "fit") if k in block]
        if len(dims) > 1:
            raise ValueError(f"{label} image accepts at most one of width_inches/height_inches/fit")
        if "fit" in block:
            fit = block["fit"]
            if not isinstance(fit, dict) or set(fit) - {"width", "height"} or not fit:
                raise ValueError(f"{label} image fit accepts width/height in inches")
            for key, value in fit.items():
                _inches(value, f"{label} image fit.{key}")
        elif "width_inches" in block:
            _inches(block["width_inches"], f"{label} image width_inches")
        elif "height_inches" in block:
            _inches(block["height_inches"], f"{label} image height_inches")
        if "path" in block and not isinstance(block["path"], str):
            raise ValueError(f"{label} image path must be a string")
    if kind in {"heading", "paragraph", "caption", "list", "table", "image", "cover"}:
        unknown = (
            set(block)
            - _KEEP_KEYS
            - {
                "type",
                "id",
                "text",
                "level",
                "items",
                "style",
                "header",
                "rows",
                "path",
                "width_inches",
                "height_inches",
                "fit",
                "title",
                "subtitle",
                "column_widths",
                "repeat_header",
            }
        )
        if unknown:
            raise ValueError(f"{label} has unsupported keys: {sorted(unknown)}")
        if "id" in block and not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,35}", str(block["id"])):
            raise ValueError(f"{label} id must be 1-36 chars: letter then letters/digits/_/-")
        for flag in _KEEP_KEYS:
            if flag in block and not isinstance(block[flag], bool):
                raise ValueError(f"{label}.{flag} must be true or false")
    if kind == "table":
        widths = block.get("column_widths")
        if widths is not None:
            if not isinstance(widths, list) or not widths or len(widths) > 20:
                raise ValueError(f"{label} column_widths must be a list of 1-20 widths")
            for w in widths:
                if type(w) not in (int, float) or not 0.2 <= w <= 10:
                    raise ValueError(f"{label} column width must be 0.2-10 inches")
        if "repeat_header" in block and not isinstance(block["repeat_header"], bool):
            raise ValueError(f"{label}.repeat_header must be true or false")
    if kind == "section_break":
        unknown = set(block) - {"type", "header", "footer", "page"}
        if unknown:
            raise ValueError(f"{label} has unsupported keys: {sorted(unknown)}")
        if "header" in block:
            _validate_header_footer(block["header"], f"{label} header")
        if "footer" in block:
            _validate_header_footer(block["footer"], f"{label} footer")
        if "page" in block:
            _validate_page(block["page"], f"{label} page")
    if kind == "cover":
        for key in ("title", "subtitle"):
            if key in block and not isinstance(block[key], str):
                raise ValueError(f"{label} cover.{key} must be plain text")


def _style_table_cell(cell, style: dict, *, header: bool) -> None:
    for paragraph in cell.paragraphs:
        for run in paragraph.runs:
            if "font" in style:
                run.font.name = style["font"]
            if "size" in style:
                run.font.size = Pt(style["size"])
            if "color" in style:
                run.font.color.rgb = RGBColor.from_string(style["color"].lstrip("#"))
            run.font.bold = header or style.get("bold", False)


_BOOKMARK_PREFIX = "cbr_"


def _bookmark_id_counter(doc) -> int:
    ids = []
    for el in doc.element.body.iter(qn("w:bookmarkStart")):
        raw = el.get(qn("w:id"))
        if raw and raw.isdigit():
            ids.append(int(raw))
    return max(ids, default=0) + 1


def _tag_block(doc, start_p, end_p, name: str, next_id: int) -> int:
    """Wrap a block's first/last paragraphs in a Word bookmark so the block
    keeps a stable address across revisions. Returns the next free id."""
    if start_p is None:
        return next_id
    bm_id = str(next_id)
    for el, tag in ((start_p, "w:bookmarkStart"), (end_p, "w:bookmarkEnd")):
        bm = OxmlElement(tag)
        bm.set(qn("w:id"), bm_id)
        bm.set(qn("w:name"), name)
        # bookmarkStart belongs after pPr; bookmarkEnd is the last child.
        if tag == "w:bookmarkStart":
            ppr = el.find(qn("w:pPr"))
            el.insert(list(el).index(ppr) + 1 if ppr is not None else 0, bm)
        else:
            el.append(bm)
    return next_id + 1


def _block_anchors(
    doc,
    block: dict,
    workspace_path: str | Path,
    table_style: dict | None = None,
    doc_title: str | None = None,
):
    """Run _add_block and return (first_p, last_p) CT_P elements to bookmark."""
    kind = block["type"]
    if kind == "heading":
        p = doc.add_heading(block["text"], level=block.get("level", 1))
        _apply_keep_flags(p, block)
        return p._p, p._p
    if kind == "paragraph":
        p = doc.add_paragraph(block["text"])
        _apply_keep_flags(p, block)
        return p._p, p._p
    if kind == "caption":
        p = doc.add_paragraph(block.get("text", ""), style="Caption")
        _apply_keep_flags(p, block)
        return p._p, p._p
    if kind == "cover":
        first = None
        if title := block.get("title") or doc_title:
            first = doc.add_paragraph(title, style="Title")._p
        if subtitle := block.get("subtitle"):
            p = doc.add_paragraph(subtitle)
            p.paragraph_format.space_before = Pt(12)
            if first is None:
                first = p._p
        doc.add_page_break()
        last = doc.paragraphs[-1]._p if doc.paragraphs else None
        return first, last if last is not None else first
    if kind == "section_break":
        section = doc.add_section(WD_SECTION.NEW_PAGE)
        if "page" in block:
            _apply_page_overrides(section, block["page"])
        if "header" in block:
            section.header.is_linked_to_previous = False
            _fill_header_footer(section.header, block["header"])
        if "footer" in block:
            section.footer.is_linked_to_previous = False
            _fill_header_footer(section.footer, block["footer"])
        return None, None
    if kind == "list":
        style = "List Number" if block.get("style") == "number" else "List Bullet"
        items = [str(i) for i in block["items"]]
        paras = []
        for i, item in enumerate(items):
            p = doc.add_paragraph(item, style=style)
            paras.append(p)
            if block.get("keep_with_next") and i != len(items) - 1:
                p.paragraph_format.keep_with_next = True
            if block.get("page_break_before") and i == 0:
                p.paragraph_format.page_break_before = True
        return paras[0]._p, paras[-1]._p
    if kind == "table":
        rows = [block.get("header", []), *block.get("rows", [])]
        table = doc.add_table(rows=len(rows), cols=max(len(r) for r in rows))
        table.style = "Table Grid"
        table_style = table_style or {}
        if widths := block.get("column_widths"):
            table.autofit = False
            for i, w in enumerate(widths):
                if i < len(table.columns):
                    table.columns[i].width = Inches(w)
        for i, row in enumerate(rows):
            for j, cell in enumerate(row):
                table.rows[i].cells[j].text = str(cell)
                if table_style:
                    _style_table_cell(table.rows[i].cells[j], table_style, header=i == 0)
        if block.get("repeat_header") and table.rows:
            trPr = table.rows[0]._tr.get_or_add_trPr()
            trPr.append(OxmlElement("w:tblHeader"))
        if block.get("keep_with_next") or block.get("page_break_before"):
            _apply_keep_flags(table.rows[0].cells[0].paragraphs[0], block)
        first_cell = table.rows[0].cells[0]
        last_cell = table.rows[-1].cells[-1]
        return first_cell.paragraphs[0]._p, last_cell.paragraphs[-1]._p
    if kind == "image":
        img = resolve_within(workspace_path, block["path"])
        _fit_picture(doc, img, block)
        p = doc.paragraphs[-1]._p
        return p, p
    if kind == "page_break":
        doc.add_page_break()
        p = doc.paragraphs[-1]._p
        return p, p
    raise ValueError(f"unknown docx block: {kind}")
