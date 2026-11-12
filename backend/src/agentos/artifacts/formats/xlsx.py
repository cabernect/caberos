"""XLSX handler — openpyxl structured build/revise/inspect/validate.

Formula honesty: openpyxl persists formula strings without evaluating them.
`formulas_recalculated` is reported separately from authorship and is only
true when a real calculation engine produced values.
"""

import zipfile
from io import BytesIO
from pathlib import Path
from xml.etree import ElementTree

from openpyxl import Workbook, load_workbook


def build(spec: dict, workspace_path: str | Path) -> bytes:
    wb = Workbook()
    wb.remove(wb.active)
    for sheet_spec in spec.get("sheets", [{"name": "Sheet1"}]):
        _build_sheet(wb, sheet_spec)
    if not wb.sheetnames:
        wb.create_sheet("Sheet1")
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


def revise(data: bytes, ops: list[dict], workspace_path: str | Path) -> bytes:
    wb = load_workbook(BytesIO(data))
    for op in ops:
        kind = op["op"]
        if kind == "set_cell":
            _set_cell(wb[op["sheet"]], op["cell"], op)
        elif kind == "append_rows":
            for row in op["rows"]:
                wb[op["sheet"]].append(row)
        elif kind == "add_sheet":
            _build_sheet(wb, op)
        elif kind == "remove_sheet":
            wb.remove(wb[op["sheet"]])
        elif kind == "style_range":
            for cell in _range_cells(wb[op["sheet"]], op["range"]):
                _apply_format(cell, op["style"])
        elif kind == "merge_cells":
            wb[op["sheet"]].merge_cells(op["range"])
        elif kind == "set_column_width":
            wb[op["sheet"]].column_dimensions[op["col"]].width = op["width"]
        elif kind == "set_row_height":
            wb[op["sheet"]].row_dimensions[op["row"]].height = op["height"]
        elif kind == "set_auto_filter":
            wb[op["sheet"]].auto_filter.ref = op["ref"] or None
        elif kind == "set_freeze":
            wb[op["sheet"]].freeze_panes = op["ref"] or None
        else:
            raise ValueError(f"unknown xlsx op: {kind}")
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


def inspect(data: bytes) -> dict:
    wb = load_workbook(BytesIO(data))
    formulas = 0
    cells = 0
    sheets: list[dict] = []
    for ws in wb.worksheets:
        sheet_cells = 0
        for row in ws.iter_rows():
            for cell in row:
                if cell.value is not None:
                    cells += 1
                    sheet_cells += 1
                    if isinstance(cell.value, str) and cell.value.startswith("="):
                        formulas += 1
        sheets.append(
            {
                "name": ws.title,
                "cells": sheet_cells,
                "merged": [str(r) for r in ws.merged_cells.ranges],
                "auto_filter": ws.auto_filter.ref or None,
                "freeze": ws.freeze_panes,
            }
        )
    return {
        "structure": {
            "sheets": wb.sheetnames,
            "cells": cells,
            "formulas": formulas,
            "sheet_details": sheets,
        },
        "formulas_recalculated": False,
    }


def validate(data: bytes) -> dict:
    errors: list[str] = []
    try:
        zf = zipfile.ZipFile(BytesIO(data))
        if zf.testzip() is not None:
            errors.append("corrupt zip member")
        names = set(zf.namelist())
        for required in ("[Content_Types].xml", "xl/workbook.xml"):
            if required not in names:
                errors.append(f"missing part: {required}")
        if "xl/workbook.xml" in names:
            ElementTree.fromstring(zf.read("xl/workbook.xml"))
    except zipfile.BadZipFile:
        errors.append("not a zip container")
    except ElementTree.ParseError as e:
        errors.append(f"workbook.xml not well-formed: {e}")
    if not errors:
        try:
            load_workbook(BytesIO(data))
        except Exception as e:
            errors.append(f"parser reopen failed: {e}")
    return {"valid": not errors, "errors": errors}


def to_elements(data: bytes, workspace_path: str | Path) -> list[dict]:
    """Extract render elements — one section per sheet, data as tables.
    Formula cells render as their formula string (unevaluated — same
    honesty contract as inspect's formulas_recalculated: false)."""
    wb = load_workbook(BytesIO(data))
    elements: list[dict] = []
    for i, ws in enumerate(wb.worksheets):
        if i:
            elements.append({"type": "page_break"})
        elements.append({"type": "heading", "text": ws.title, "level": 2})
        rows = []
        for row in ws.iter_rows():
            vals = ["" if c.value is None else str(c.value) for c in row]
            if any(vals):
                rows.append(vals)
        if rows:
            elements.append({"type": "table", "header": rows[0], "rows": rows[1:]})
        else:
            elements.append({"type": "paragraph", "text": "(empty sheet)"})
    return elements


def _build_sheet(wb: Workbook, sheet_spec: dict) -> None:
    ws = wb.create_sheet(sheet_spec.get("name", "Sheet"))
    # Print/page defaults — a sheet that paginates sanely on export or print:
    # landscape, shrink columns to one page wide, modest margins.
    ws.page_setup.orientation = "landscape"
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    ws.page_margins.left = ws.page_margins.right = 0.5
    ws.page_margins.top = ws.page_margins.bottom = 0.6
    for row in sheet_spec.get("rows", []):
        ws.append(row)
    for ref, cell_spec in sheet_spec.get("cells", {}).items():
        _set_cell(ws, ref, cell_spec)
    if freeze := sheet_spec.get("freeze"):
        ws.freeze_panes = freeze
    if auto_filter := sheet_spec.get("auto_filter"):
        from openpyxl.utils import get_column_letter

        ref = auto_filter if isinstance(auto_filter, str) else None
        if ref is None:
            ref = f"A1:{get_column_letter(ws.max_column)}{max(ws.max_row, 1)}"
        ws.auto_filter.ref = ref
    for ref in sheet_spec.get("merges", []):
        ws.merge_cells(ref)
    for row_idx, height in sheet_spec.get("row_heights", {}).items():
        ws.row_dimensions[int(row_idx)].height = height
    for col, width in sheet_spec.get("column_widths", {}).items():
        ws.column_dimensions[col].width = width
    for fmt_range, fmt in sheet_spec.get("formats", {}).items():
        for cell in _range_cells(ws, fmt_range):
            _apply_format(cell, fmt)


def _range_cells(ws, ref: str):
    """Yield cells for a range ref — tolerates a single cell ('B2')."""
    from openpyxl.cell.cell import Cell

    target = ws[ref]
    if isinstance(target, Cell):
        return iter([target])
    return (cell for row in target for cell in row)


def _set_cell(ws, ref: str, cell_spec: dict | str | int | float) -> None:
    if not isinstance(cell_spec, dict):
        cell_spec = {"value": cell_spec}
    if "formula" in cell_spec:
        ws[ref] = cell_spec["formula"]
    elif "value" in cell_spec:
        ws[ref] = cell_spec["value"]
    _apply_format(ws[ref], cell_spec)


_BORDERS = {"thin", "medium", "thick", "dashed", "dotted", "double"}
_ALIGNS = {"left", "center", "right", "justify", "general"}
_VALIGNS = {"top", "center", "bottom"}


def _hex(value: str) -> str:
    """Normalize '#RRGGBB'/'RRGGBB' → '00RRGGBB' openpyxl ARGB."""
    v = value.lstrip("#").upper()
    if len(v) != 6 or any(c not in "0123456789ABCDEF" for c in v):
        raise ValueError(f"invalid hex color: {value!r}")
    return "00" + v


def _apply_format(cell, fmt: dict) -> None:
    from copy import copy

    if fmt.get("number_format"):
        cell.number_format = fmt["number_format"]
    font_changes = {k: fmt[k] for k in ("bold", "italic", "color") if k in fmt}
    if "font_size" in fmt:
        font_changes["size"] = fmt["font_size"]
    if font_changes:
        font = copy(cell.font)
        for k, v in font_changes.items():
            setattr(font, k, _hex(v) if k == "color" else v)
        cell.font = font
    if fill := fmt.get("fill"):
        from openpyxl.styles import PatternFill

        cell.fill = PatternFill("solid", fgColor=_hex(fill))
    align_changes = {k: fmt[k] for k in ("align", "valign", "wrap_text") if k in fmt}
    if align_changes:
        alignment = copy(cell.alignment)
        if "align" in align_changes:
            if align_changes["align"] not in _ALIGNS:
                raise ValueError(f"invalid align: {align_changes['align']!r}")
            alignment.horizontal = align_changes["align"]
        if "valign" in align_changes:
            if align_changes["valign"] not in _VALIGNS:
                raise ValueError(f"invalid valign: {align_changes['valign']!r}")
            alignment.vertical = {"center": "center", "bottom": "bottom"}.get(
                align_changes["valign"], align_changes["valign"]
            )
        if "wrap_text" in align_changes:
            alignment.wrap_text = bool(align_changes["wrap_text"])
        cell.alignment = alignment
    if border := fmt.get("border"):
        from openpyxl.styles import Border, Side

        style = border.get("style") if isinstance(border, dict) else border
        if style not in _BORDERS:
            raise ValueError(f"invalid border style: {style!r}")
        color = _hex(border.get("color", "000000")) if isinstance(border, dict) else "00000000"
        side = Side(style=style, color=color)
        cell.border = Border(left=side, right=side, top=side, bottom=side)
