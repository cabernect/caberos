"""XLSX handler — openpyxl structured build/revise/inspect/validate.

Formula honesty: openpyxl persists formula strings without evaluating them.
`formulas_recalculated` is reported separately from authorship and is only
true when a real calculation engine produced values.
"""

import re
import zipfile
from io import BytesIO
from pathlib import Path
from xml.etree import ElementTree

from openpyxl import Workbook, load_workbook

# ZIP-part prefixes openpyxl cannot model — a load+save round-trip drops
# them silently. revise() refuses on these unless the ops batch carries an
# explicit {"op": "accept_feature_loss"} acknowledgement.
_DROP_PREFIXES = {
    "xl/pivotCache/": "pivot_tables",
    "xl/pivotTables/": "pivot_tables",
    "xl/slicerCaches/": "slicers",
    "xl/slicers/": "slicers",
    "xl/timelines/": "timelines",
    "xl/activeX/": "form_controls",
    "xl/ctrlProps/": "form_controls",
    "xl/embeddings/": "embedded_objects",
    "xl/customXml/": "custom_xml",
    "xl/richData/": "rich_data",
    "xl/threadedComments/": "threaded_comments",
    "xl/persons/": "persons",
}


_XDR = "{http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing}"
_DRAWING_ROOT = f"{_XDR}wsDr"
_UNSUPPORTED_DRAWING_TAGS = {f"{_XDR}sp", f"{_XDR}grpSp", f"{_XDR}cxnSp", f"{_XDR}contentPart"}


def _has_unsupported_drawing_shapes(data: bytes) -> bool:
    """True when a drawing part holds objects openpyxl cannot round-trip.

    Pictures, charts and tables survive load+save; shapes, text boxes,
    connectors, groups and ink content parts are silently dropped.
    Drawing parts are found by their ``xdr:wsDr`` root, not filename —
    OPC allows any part name (``drawing.xml``, ``shapes.xml``, ...)."""
    try:
        with zipfile.ZipFile(BytesIO(data)) as zf:
            for name in zf.namelist():
                if not name.endswith(".xml") or name.endswith(".rels"):
                    continue
                try:
                    root = ElementTree.fromstring(zf.read(name))
                except ElementTree.ParseError:
                    continue
                if root.tag != _DRAWING_ROOT:
                    continue
                if any(el.tag in _UNSUPPORTED_DRAWING_TAGS for el in root.iter()):
                    return True
    except zipfile.BadZipFile:
        pass
    return False


def _part_names(data: bytes) -> set[str]:
    try:
        with zipfile.ZipFile(BytesIO(data)) as zf:
            return set(zf.namelist())
    except zipfile.BadZipFile:
        return set()


def _feature_inventory(data: bytes) -> dict:
    """Feature inventory from ZIP parts + openpyxl — what a revise would
    preserve, warn about, or drop. Categories are evidence, not guesses."""
    names = _part_names(data)
    inv = {
        "charts": sum(1 for n in names if n.startswith("xl/charts/")),
        "tables": sum(1 for n in names if n.startswith("xl/tables/")),
        "images": sum(1 for n in names if n.startswith("xl/media/")),
        "external_links": sum(1 for n in names if n.startswith("xl/externalLinks/")),
        "macros": int("xl/vbaProject.bin" in names),
        "data_validations": 0,
        "conditional_formatting": 0,
        "defined_names": 0,
    }
    drops = {cat for prefix, cat in _DROP_PREFIXES.items() for n in names if n.startswith(prefix)}
    if _has_unsupported_drawing_shapes(data):
        drops.add("shapes")
    try:
        wb = load_workbook(BytesIO(data))
        inv["defined_names"] = len(wb.defined_names)
        for ws in wb.worksheets:
            inv["data_validations"] += len(ws.data_validations.dataValidation)
            inv["conditional_formatting"] += sum(len(r.rules) for r in ws.conditional_formatting)
        wb.close()
    except Exception:
        pass  # inventory is best-effort; validate() reports real corruption
    inv["drops_on_edit"] = sorted(drops)
    return inv


def _load_preserving(data: bytes):
    """openpyxl load that keeps what it can: external links always, VBA
    project binary when present (preserved, never executed)."""
    names = _part_names(data)
    return load_workbook(BytesIO(data), keep_links=True, keep_vba="xl/vbaProject.bin" in names)


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
    drops = _feature_inventory(data)["drops_on_edit"]
    if drops and not any(op.get("op") == "accept_feature_loss" for op in ops):
        raise ValueError(
            "workbook contains features a round-trip edit cannot preserve: "
            + ", ".join(drops)
            + '. Pass {"op": "accept_feature_loss"} to produce a '
            "reduced-feature copy, or don't edit this file."
        )
    wb = _load_preserving(data)
    for op in ops:
        kind = op["op"]
        if kind == "accept_feature_loss":
            continue
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
        elif kind == "add_table":
            _add_table(wb[op["sheet"]], op)
        elif kind == "remove_table":
            tables = wb[op["sheet"]].tables
            if op["name"] not in tables:
                raise ValueError(f"no table named {op['name']!r} on sheet {op['sheet']!r}")
            tables.pop(op["name"])
        elif kind == "add_chart":
            _add_chart(wb[op["sheet"]], op)
        elif kind == "add_data_validation":
            _add_data_validation(wb[op["sheet"]], op)
        elif kind == "remove_data_validation":
            _remove_data_validation(wb[op["sheet"]], op["range"])
        elif kind == "add_conditional_format":
            _add_conditional_format(wb[op["sheet"]], op)
        elif kind == "remove_conditional_format":
            _remove_conditional_format(wb[op["sheet"]], op["range"])
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
                "tables": sorted(ws.tables.keys()),
                "charts": len(ws._charts),
                "data_validations": len(ws.data_validations.dataValidation),
                "conditional_formats": sum(len(r.rules) for r in ws.conditional_formatting),
            }
        )
    features = _feature_inventory(data)
    return {
        "structure": {
            "sheets": wb.sheetnames,
            "cells": cells,
            "formulas": formulas,
            "sheet_details": sheets,
        },
        "features": features,
        "edit_safety": {
            "preserved": [
                "styles",
                "merges",
                "tables",
                "charts",
                "images",
                "defined_names",
                "data_validations",
                "conditional_formatting",
                "external_links",
                "macros(via keep_vba)",
            ],
            "dropped_without_acknowledgement": features["drops_on_edit"],
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


_TABLE_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.]{0,254}$")
_TABLE_STYLE_RE = re.compile(r"^TableStyle(Light|Medium|Dark)[1-9]\d?$")


def _check_table_name(wb: Workbook, name) -> str:
    if not isinstance(name, str) or not _TABLE_NAME_RE.match(name):
        raise ValueError(
            "table name must start with a letter/underscore and use letters, digits, '.', '_' only"
        )
    for ws in wb.worksheets:
        if name in ws.tables:
            raise ValueError(f"table name already used: {name!r}")
    return name


def _add_table(ws, spec: dict) -> None:
    from openpyxl.worksheet.table import Table, TableStyleInfo

    name = _check_table_name(ws.parent, spec.get("name", ""))
    ref = spec.get("ref")
    if not isinstance(ref, str):
        raise ValueError("table needs a ref like 'A1:C10'")
    style = spec.get("style", "TableStyleMedium2")
    if not _TABLE_STYLE_RE.match(str(style)):
        raise ValueError(f"invalid table style: {style!r}")
    table = Table(displayName=name, ref=ref)
    table.tableStyleInfo = TableStyleInfo(name=style, showRowStripes=True, showColumnStripes=False)
    ws.add_table(table)


_CHART_TYPES = {}


def _chart_class(kind: str):
    if not _CHART_TYPES:
        from openpyxl.chart import BarChart, LineChart, PieChart

        _CHART_TYPES.update({"bar": BarChart, "line": LineChart, "pie": PieChart})
    cls = _CHART_TYPES.get(kind)
    if cls is None:
        raise ValueError(f"chart type must be one of {sorted(_CHART_TYPES)}")
    return cls


def _range_reference(ws, ref: str):
    from openpyxl.chart import Reference
    from openpyxl.utils import range_boundaries

    try:
        min_col, min_row, max_col, max_row = range_boundaries(ref)
    except Exception:
        raise ValueError(f"invalid range ref: {ref!r}") from None
    return Reference(ws, min_col=min_col, min_row=min_row, max_col=max_col, max_row=max_row)


def _add_chart(ws, spec: dict) -> None:
    chart = _chart_class(spec.get("type", "bar"))()
    if title := spec.get("title"):
        chart.title = str(title)
    data = spec.get("data")
    if not isinstance(data, str):
        raise ValueError("chart needs a data ref like 'B2:D10'")
    chart.add_data(_range_reference(ws, data), titles_from_data=True)
    if cats := spec.get("categories"):
        chart.set_categories(_range_reference(ws, cats))
    anchor = spec.get("anchor", "E2")
    if not isinstance(anchor, str):
        raise ValueError("chart anchor must be a cell ref like 'E2'")
    ws.add_chart(chart, anchor)


_DV_TYPES = {"list", "whole", "decimal", "date", "time", "textLength"}
_CF_OPERATORS = {
    "equal",
    "notEqual",
    "greaterThan",
    "greaterThanOrEqual",
    "lessThan",
    "lessThanOrEqual",
    "between",
    "notBetween",
}


def _sqref(ref) -> str:
    """Validate a sqref (single range or space-separated list)."""
    from openpyxl.utils.cell import range_boundaries

    if not isinstance(ref, str) or not ref.strip():
        raise ValueError("range must be a non-empty ref like 'B2:B10'")
    for part in ref.split():
        try:
            range_boundaries(part)
        except Exception:
            raise ValueError(f"invalid range ref: {part!r}") from None
    return ref


def _add_data_validation(ws, spec: dict) -> None:
    from openpyxl.worksheet.datavalidation import DataValidation

    dv_type = spec.get("type", "list")
    if dv_type not in _DV_TYPES:
        raise ValueError(f"data validation type must be one of {sorted(_DV_TYPES)}")
    dv = DataValidation(
        type=dv_type,
        formula1=spec.get("formula1"),
        formula2=spec.get("formula2"),
        allow_blank=bool(spec.get("allow_blank", True)),
        showErrorMessage=bool(spec.get("show_error", True)),
        errorTitle=spec.get("error_title"),
        error=spec.get("error"),
        promptTitle=spec.get("prompt_title"),
        prompt=spec.get("prompt"),
    )
    dv.sqref = _sqref(spec.get("range"))
    ws.add_data_validation(dv)


def _remove_data_validation(ws, ref: str) -> None:
    target = _sqref(ref)
    keep = [dv for dv in ws.data_validations.dataValidation if str(dv.sqref) != target]
    if len(keep) == len(ws.data_validations.dataValidation):
        raise ValueError(f"no data validation on range {target!r}")
    ws.data_validations.dataValidation = keep


def _add_conditional_format(ws, spec: dict) -> None:
    from openpyxl.formatting.rule import CellIsRule
    from openpyxl.styles import Font, PatternFill
    from openpyxl.styles.differential import DifferentialStyle

    operator = spec.get("operator")
    if operator not in _CF_OPERATORS:
        raise ValueError(f"conditional format operator must be one of {sorted(_CF_OPERATORS)}")
    formulas = spec.get("formula")
    if not isinstance(formulas, list) or not formulas or len(formulas) > 2:
        raise ValueError("conditional format needs a formula list of 1-2 values")
    dxf = DifferentialStyle()
    if fill := spec.get("fill"):
        dxf.fill = PatternFill("solid", fgColor=_hex(fill))
    if spec.get("bold"):
        dxf.font = Font(bold=True)
    rule = CellIsRule(
        operator=operator,
        formula=[str(f) for f in formulas],
        fill=dxf.fill,
        font=dxf.font,
    )
    ws.conditional_formatting.add(_sqref(spec.get("range")), rule)


def _remove_conditional_format(ws, ref: str) -> None:
    """Remove every rule registered on exactly this sqref — mirrors
    _remove_data_validation's exact-range semantics."""
    target = _sqref(ref)
    try:
        del ws.conditional_formatting[target]
    except KeyError:
        raise ValueError(f"no conditional formatting on range {target!r}") from None


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
    for table_spec in sheet_spec.get("tables", []):
        _add_table(ws, table_spec)
    for chart_spec in sheet_spec.get("charts", []):
        _add_chart(ws, chart_spec)
    for dv_spec in sheet_spec.get("data_validations", []):
        _add_data_validation(ws, dv_spec)
    for cf_spec in sheet_spec.get("conditional_formats", []):
        _add_conditional_format(ws, cf_spec)


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
