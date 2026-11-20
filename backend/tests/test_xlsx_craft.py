"""W3X: XLSX preflight, native tables/charts, validation/CF tests."""

import zipfile
from io import BytesIO

import pytest
from openpyxl import load_workbook

from agentos.artifacts.formats import xlsx as xlsx_fmt


def _wb(data: bytes):
    return load_workbook(BytesIO(data))


def _with_extra_part(data: bytes, part: str, content: bytes = b"<x/>") -> bytes:
    src = zipfile.ZipFile(BytesIO(data))
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for n in src.namelist():
            zf.writestr(n, src.read(n))
        zf.writestr(part, content)
    return buf.getvalue()


def test_feature_inventory_counts_everything() -> None:
    data = xlsx_fmt.build(
        {
            "sheets": [
                {
                    "name": "S",
                    "rows": [["h1", "h2"], [1, 2]],
                    "tables": [{"name": "T1", "ref": "A1:B2"}],
                    "charts": [{"type": "bar", "data": "B1:B2", "categories": "A1:A2"}],
                    "data_validations": [{"range": "A1:A2", "type": "list", "formula1": '"x,y"'}],
                    "conditional_formats": [
                        {"range": "B1:B2", "operator": "greaterThan", "formula": ["1"]}
                    ],
                }
            ]
        },
        ".",
    )
    f = xlsx_fmt.inspect(data)["features"]
    assert f["tables"] == 1 and f["charts"] == 1
    assert f["data_validations"] == 1 and f["conditional_formatting"] == 1
    assert f["drops_on_edit"] == []
    # per-sheet detail for W4 preview
    detail = xlsx_fmt.inspect(data)["structure"]["sheet_details"][0]
    assert detail["tables"] == ["T1"] and detail["charts"] == 1


def test_pivot_parts_block_revise_until_acknowledged() -> None:
    data = xlsx_fmt.build({"sheets": [{"name": "S", "rows": [[1]]}]}, ".")
    risky = _with_extra_part(data, "xl/pivotCache/pivotCacheDefinition1.xml")
    assert xlsx_fmt._feature_inventory(risky)["drops_on_edit"] == ["pivot_tables"]
    with pytest.raises(ValueError, match="accept_feature_loss"):
        xlsx_fmt.revise(risky, [{"op": "set_cell", "sheet": "S", "cell": "A1", "value": 2}], ".")
    rev = xlsx_fmt.revise(
        risky,
        [{"op": "accept_feature_loss"}, {"op": "set_cell", "sheet": "S", "cell": "A1", "value": 2}],
        ".",
    )
    assert _wb(rev)["S"]["A1"].value == 2
    # clean workbook revises without the pseudo-op
    rev2 = xlsx_fmt.revise(data, [{"op": "set_cell", "sheet": "S", "cell": "A1", "value": 9}], ".")
    assert _wb(rev2)["S"]["A1"].value == 9


@pytest.mark.parametrize(
    "part",
    [
        "xl/slicers/slicer1.xml",
        "xl/activeX/activeX1.xml",
        "xl/embeddings/Microsoft_Excel_Worksheet1.xlsx",
        "xl/customXml/item1.xml",
        "xl/threadedComments/threadedComment1.xml",
    ],
)
def test_other_drop_categories_detected(part: str) -> None:
    data = xlsx_fmt.build({"sheets": [{"name": "S", "rows": [[1]]}]}, ".")
    risky = _with_extra_part(data, part)
    assert xlsx_fmt._feature_inventory(risky)["drops_on_edit"]


def test_table_create_update_remove() -> None:
    data = xlsx_fmt.build(
        {
            "sheets": [
                {
                    "name": "S",
                    "rows": [["A", "B"], [1, 2], [3, 4]],
                    "tables": [{"name": "Sales", "ref": "A1:B3", "style": "TableStyleMedium9"}],
                }
            ]
        },
        ".",
    )
    ws = _wb(data)["S"]
    assert "Sales" in ws.tables
    # duplicate name rejected workbook-wide
    with pytest.raises(ValueError, match="already used"):
        xlsx_fmt.revise(
            data,
            [{"op": "add_table", "sheet": "S", "name": "Sales", "ref": "D1:E3"}],
            ".",
        )
    rev = xlsx_fmt.revise(
        data,
        [
            {"op": "add_table", "sheet": "S", "name": "Extra", "ref": "D1:E3"},
            {"op": "remove_table", "sheet": "S", "name": "Sales"},
        ],
        ".",
    )
    ws2 = _wb(rev)["S"]
    assert list(ws2.tables.keys()) == ["Extra"]


def test_chart_types_and_validation() -> None:
    data = xlsx_fmt.build(
        {
            "sheets": [
                {
                    "name": "S",
                    "rows": [["R", "V"], ["a", 1], ["b", 2]],
                    "charts": [
                        {
                            "type": "line",
                            "title": "T",
                            "data": "B2:B3",
                            "categories": "A2:A3",
                            "anchor": "E2",
                        }
                    ],
                }
            ]
        },
        ".",
    )
    ws = _wb(data)["S"]
    assert len(ws._charts) == 1
    # bad type / missing data / bad ref rejected
    for op in [
        {"op": "add_chart", "sheet": "S", "type": "radar", "data": "B2:B3"},
        {"op": "add_chart", "sheet": "S", "type": "bar"},
        {"op": "add_chart", "sheet": "S", "type": "bar", "data": "not a ref!!"},
    ]:
        with pytest.raises(ValueError):
            xlsx_fmt.revise(data, [op], ".")


def test_data_validation_and_conditional_format() -> None:
    data = xlsx_fmt.build(
        {
            "sheets": [
                {
                    "name": "S",
                    "rows": [["q"], [5], [50]],
                    "data_validations": [
                        {
                            "range": "A2:A3",
                            "type": "whole",
                            "formula1": "0",
                            "formula2": "100",
                            "error": "out of range",
                        }
                    ],
                    "conditional_formats": [
                        {
                            "range": "A2:A3",
                            "operator": "greaterThan",
                            "formula": ["40"],
                            "fill": "#FFCCCC",
                            "bold": True,
                        }
                    ],
                }
            ]
        },
        ".",
    )
    ws = _wb(data)["S"]
    dv = ws.data_validations.dataValidation[0]
    assert dv.type == "whole" and dv.formula2 == "100" and dv.error == "out of range"
    cf = list(ws.conditional_formatting)[0]
    assert cf.rules[0].operator == "greaterThan"
    # revise add/remove
    rev = xlsx_fmt.revise(
        data,
        [
            {
                "op": "add_data_validation",
                "sheet": "S",
                "range": "B1",
                "type": "list",
                "formula1": '"x,y"',
            },
            {"op": "remove_data_validation", "sheet": "S", "range": "A2:A3"},
            {
                "op": "add_conditional_format",
                "sheet": "S",
                "range": "B1",
                "operator": "equal",
                "formula": ["x"],
            },
        ],
        ".",
    )
    ws2 = _wb(rev)["S"]
    assert [str(d.sqref) for d in ws2.data_validations.dataValidation] == ["B1"]
    assert "B1" in [str(r.sqref) for r in ws2.conditional_formatting]
    # invalid DV type / CF operator / bad range rejected
    for op in [
        {"op": "add_data_validation", "sheet": "S", "range": "A1", "type": "bogus"},
        {
            "op": "add_conditional_format",
            "sheet": "S",
            "range": "A1",
            "operator": "bogus",
            "formula": ["1"],
        },
        {"op": "add_data_validation", "sheet": "S", "range": "!!", "type": "list"},
    ]:
        with pytest.raises(ValueError):
            xlsx_fmt.revise(data, [op], ".")


def test_remove_conditional_format_roundtrip() -> None:
    data = xlsx_fmt.build(
        {
            "sheets": [
                {
                    "name": "S",
                    "rows": [[1]],
                    "conditional_formats": [
                        {"range": "A1", "operator": "greaterThan", "formula": ["0"]}
                    ],
                }
            ]
        },
        ".",
    )
    rev = xlsx_fmt.revise(
        data,
        [
            {
                "op": "add_conditional_format",
                "sheet": "S",
                "range": "B1",
                "operator": "equal",
                "formula": ["x"],
            },
            {"op": "remove_conditional_format", "sheet": "S", "range": "B1"},
            {"op": "remove_conditional_format", "sheet": "S", "range": "A1"},
        ],
        ".",
    )
    assert len(_wb(rev)["S"].conditional_formatting) == 0
    # removing a range with no rules is an error, not a silent no-op
    with pytest.raises(ValueError, match="no conditional formatting"):
        xlsx_fmt.revise(
            data, [{"op": "remove_conditional_format", "sheet": "S", "range": "Z9"}], "."
        )


_XDR = "http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing"


def _with_drawing(data: bytes, inner: str, part: str = "xl/drawings/drawing1.xml") -> bytes:
    drawing = (
        f'<xdr:wsDr xmlns:xdr="{_XDR}"><xdr:twoCellAnchor>{inner}'
        "<xdr:clientData/></xdr:twoCellAnchor></xdr:wsDr>"
    )
    return _with_extra_part(data, part, drawing.encode())


_DRAWING_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/drawing"
_DRAWING_CT = "application/vnd.openxmlformats-officedocument.drawing+xml"


def _with_referenced_drawing(data: bytes, part: str, inner: str) -> bytes:
    """Wire a drawing into sheet1 the way Excel does — content-type
    override, worksheet relationship and <drawing> element — so the part
    is genuinely referenced, not a stray zip member."""
    drawing = (
        f'<xdr:wsDr xmlns:xdr="{_XDR}"><xdr:twoCellAnchor>{inner}'
        "<xdr:clientData/></xdr:twoCellAnchor></xdr:wsDr>"
    ).encode()
    src = zipfile.ZipFile(BytesIO(data))
    parts = {n: src.read(n) for n in src.namelist()}
    sheet = "xl/worksheets/sheet1.xml"
    sheet_xml = parts[sheet]
    if b'xmlns:r="' not in sheet_xml:
        sheet_xml = sheet_xml.replace(
            b"<worksheet ",
            b'<worksheet xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" ',
            1,
        )
    parts[sheet] = sheet_xml.replace(b"</worksheet>", b'<drawing r:id="rIdDraw1"/></worksheet>')
    rels = "xl/worksheets/_rels/sheet1.xml.rels"
    rel = (
        f'<Relationship Id="rIdDraw1" Type="{_DRAWING_REL}" '
        f'Target="../drawings/{part.rsplit("/", 1)[-1]}"/>'
    ).encode()
    if rels in parts:
        parts[rels] = parts[rels].replace(b"</Relationships>", rel + b"</Relationships>")
    else:
        parts[rels] = (
            b'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            + rel
            + b"</Relationships>"
        )
    parts["[Content_Types].xml"] = parts["[Content_Types].xml"].replace(
        b"</Types>",
        f'<Override PartName="/{part}" ContentType="{_DRAWING_CT}"/></Types>'.encode(),
    )
    parts[part] = drawing
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for n, payload in parts.items():
            zf.writestr(n, payload)
    return buf.getvalue()


@pytest.mark.parametrize("part", ["xl/drawings/drawing1.xml", "xl/drawings/shapes.xml"])
def test_drawing_shapes_block_revise_until_acknowledged(part: str) -> None:
    """Text boxes / autoshapes in drawings are dropped by openpyxl's
    round-trip — preflight must flag them like pivot tables. Detection
    follows the xdr:wsDr root, not the part filename."""
    data = xlsx_fmt.build({"sheets": [{"name": "S", "rows": [[1]]}]}, ".")
    textbox = _with_drawing(data, '<xdr:sp macro="" textlink=""/>', part)
    assert xlsx_fmt._feature_inventory(textbox)["drops_on_edit"] == ["shapes"]
    with pytest.raises(ValueError, match="accept_feature_loss"):
        xlsx_fmt.revise(textbox, [{"op": "set_cell", "sheet": "S", "cell": "A1", "value": 2}], ".")
    # pictures and chart frames are preserved — no false positive
    picture = _with_drawing(data, "<xdr:pic><xdr:nvPicPr/></xdr:pic>", part)
    assert xlsx_fmt._feature_inventory(picture)["drops_on_edit"] == []


def test_referenced_drawing_with_textbox_blocks_revise() -> None:
    """A drawing wired through real OPC relationships (content-type
    override + sheet rel + <drawing> element) is still flagged — the
    scanner keys on the xdr:wsDr document, not the part name."""
    data = xlsx_fmt.build({"sheets": [{"name": "S", "rows": [[1]]}]}, ".")
    risky = _with_referenced_drawing(
        data, "xl/drawings/shapes.xml", '<xdr:sp macro="" textlink=""/>'
    )
    _wb(risky)  # wiring is valid — openpyxl loads it
    assert xlsx_fmt._feature_inventory(risky)["drops_on_edit"] == ["shapes"]
    with pytest.raises(ValueError, match="accept_feature_loss"):
        xlsx_fmt.revise(risky, [{"op": "set_cell", "sheet": "S", "cell": "A1", "value": 2}], ".")


def test_formulas_stay_unevaluated_and_counted() -> None:
    data = xlsx_fmt.build(
        {
            "sheets": [
                {
                    "name": "S",
                    "rows": [[1, 2]],
                    "cells": {"C1": {"formula": "=SUM(A1:B1)"}, "D1": {"value": "plain"}},
                }
            ]
        },
        ".",
    )
    ws = _wb(data)["S"]
    assert ws["C1"].value == "=SUM(A1:B1)" or ws["C1"].data_type == "f"
    info = xlsx_fmt.inspect(data)
    assert info["structure"]["formulas"] == 1
    assert info["formulas_recalculated"] is False
