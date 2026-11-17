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
