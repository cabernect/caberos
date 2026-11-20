"""W3 slice 1: DOCX style/page schema tests."""

from io import BytesIO

import pytest
from docx import Document

from agentos.artifacts.formats import docx as docx_fmt


def _reopen(data: bytes) -> Document:
    return Document(BytesIO(data))


def test_default_spec_preserves_old_defaults() -> None:
    data = docx_fmt.build({"title": "T", "blocks": [{"type": "paragraph", "text": "Hi"}]}, ".")
    doc = _reopen(data)
    section = doc.sections[0]
    assert round(section.page_width.inches, 2) == 8.5
    assert round(section.page_height.inches, 2) == 11
    assert section.left_margin.inches == 1
    # Untouched template styles keep their original fonts.
    assert doc.styles["Normal"].font.name is None or doc.styles["Normal"].font.name != "Georgia"


def test_named_styles_apply_to_docx_styles() -> None:
    data = docx_fmt.build(
        {
            "styles": {
                "heading": {"font": "Georgia", "size": 22, "color": "#1c1917", "space_after": 8},
                "h1": {"size": 26, "bold": True},
                "body": {"font": "Aptos", "size": 11, "line_spacing": 1.3},
                "list": {"italic": True},
                "caption": {"size": 9, "color": "#666666"},
            },
            "blocks": [
                {"type": "heading", "level": 1, "text": "S"},
                {"type": "paragraph", "text": "B"},
                {"type": "list", "items": ["i"], "style": "bullet"},
                {"type": "caption", "text": "cap"},
            ],
        },
        ".",
    )
    doc = _reopen(data)
    h1 = doc.styles["Heading 1"].font
    assert h1.name == "Georgia" and h1.size.pt == 26 and h1.bold is True
    h2 = doc.styles["Heading 2"].font
    assert h2.size.pt == 22  # heading role, h1 override doesn't leak
    normal = doc.styles["Normal"]
    assert normal.font.name == "Aptos"
    assert normal.paragraph_format.line_spacing == 1.3
    assert doc.styles["List Bullet"].font.italic is True
    assert doc.styles["Caption"].font.size.pt == 9
    assert docx_fmt.validate(data)["valid"]


def test_page_size_and_margins() -> None:
    data = docx_fmt.build(
        {"page": {"size": "a4", "margins": {"top": 0.8, "left": 1.2}}, "blocks": []}, "."
    )
    section = _reopen(data).sections[0]
    assert section.page_width.inches == pytest.approx(8.27, abs=0.01)
    assert section.top_margin.inches == pytest.approx(0.8)
    assert section.left_margin.inches == pytest.approx(1.2)
    assert section.right_margin.inches == 1  # unset sides keep default


def test_table_style_reaches_cells_and_header_bold() -> None:
    data = docx_fmt.build(
        {
            "styles": {"table": {"size": 9, "color": "#333333"}},
            "blocks": [{"type": "table", "header": ["H"], "rows": [["v"]]}],
        },
        ".",
    )
    doc = _reopen(data)
    cells = doc.tables[0].rows[0].cells + doc.tables[0].rows[1].cells
    for cell in cells:
        run = cell.paragraphs[0].runs[0]
        assert run.font.size.pt == 9
    header_run = doc.tables[0].rows[0].cells[0].paragraphs[0].runs[0]
    body_run = doc.tables[0].rows[1].cells[0].paragraphs[0].runs[0]
    assert header_run.font.bold is True
    assert body_run.font.bold is not True


@pytest.mark.parametrize(
    "spec,match",
    [
        ({"styles": {"nope": {"size": 12}}}, "unknown style role"),
        ({"styles": {"body": {"size": 200}}}, "6-96"),
        ({"styles": {"body": {"color": "red"}}}, "#RRGGBB"),
        ({"styles": {"body": {"font": 12}}}, "font name"),
        ({"styles": {"body": {"bogus": 1}}}, "unsupported keys"),
        ({"styles": {"table": {"space_after": 4}}}, "spacing keys"),
        ({"page": {"size": "tabloid"}}, "page.size"),
        ({"page": {"margins": {"top": 5}}}, "0.3-2.5"),
        ({"blocks": [{"type": "heading", "level": 9}]}, "0-6"),
        ({"blocks": [{"type": "weird"}]}, "unsupported type"),
        ({"blocks": [{"type": "image", "width_inches": 99}]}, "width_inches"),
    ],
)
def test_invalid_specs_rejected(spec: dict, match: str) -> None:
    with pytest.raises(ValueError, match=match):
        docx_fmt.build(spec, ".")


def test_vietnamese_and_long_text_builds() -> None:
    text = "Đường sắt tốc độ cao Bắc–Nam kết nối Hà Nội với Thành phố Hồ Chí Minh " * 20
    data = docx_fmt.build(
        {
            "title": "Báo cáo dài: " + "Tiêu đề " * 15,
            "styles": {"body": {"font": "Times New Roman"}},
            "blocks": [{"type": "paragraph", "text": text}],
        },
        ".",
    )
    doc = _reopen(data)
    assert doc.paragraphs[-1].text == text
    assert docx_fmt.validate(data)["valid"]


def test_revise_append_blocks_validates_and_preserves(tmp_path) -> None:
    spec = {"blocks": [{"type": "paragraph", "text": "one"}]}
    data = docx_fmt.build(spec, ".")
    rev = docx_fmt.revise(
        data,
        [
            {
                "op": "append_blocks",
                "blocks": [
                    {"type": "caption", "text": "cap"},
                    {"type": "paragraph", "text": "two"},
                ],
            }
        ],
        ".",
    )
    doc = _reopen(rev)
    texts = [p.text for p in doc.paragraphs]
    assert "one" in texts and "two" in texts and "cap" in texts
    # Invalid appended block type fails without producing output.
    with pytest.raises(ValueError, match="unsupported type"):
        docx_fmt.revise(data, [{"op": "append_blocks", "blocks": [{"type": "bogus"}]}], ".")


def test_header_footer_and_page_number_fields() -> None:
    data = docx_fmt.build(
        {
            "header": {"text": "Confidential", "align": "center"},
            "footer": {"text": "Page ", "page_numbers": True, "total_pages": True},
            "blocks": [{"type": "paragraph", "text": "x"}],
        },
        ".",
    )
    doc = _reopen(data)
    header = doc.sections[0].header
    assert header.paragraphs[0].text == "Confidential"
    footer_xml = doc.sections[0].footer._element.xml
    assert "PAGE" in footer_xml and "NUMPAGES" in footer_xml
    assert docx_fmt.validate(data)["valid"]


def test_section_break_overrides_and_inheritance() -> None:
    data = docx_fmt.build(
        {
            "footer": {"page_numbers": True},
            "blocks": [
                {"type": "paragraph", "text": "one"},
                {
                    "type": "section_break",
                    "page": {"margins": {"left": 1.5}},
                    "footer": {"text": "Appendix", "align": "right"},
                },
                {"type": "paragraph", "text": "two"},
            ],
        },
        ".",
    )
    doc = _reopen(data)
    assert len(doc.sections) == 2
    s2 = doc.sections[1]
    assert s2.left_margin.inches == pytest.approx(1.5)
    assert s2.top_margin.inches == 1  # unspecified sides keep previous values
    # Section 2 has its own footer (unlinked) with custom text.
    assert not s2.footer.is_linked_to_previous
    assert s2.footer.paragraphs[0].text == "Appendix"
    # inspect reports per-section detail.
    sections = docx_fmt.inspect(data)["structure"]["sections"]
    assert len(sections) == 2
    assert sections[1]["footer_linked"] is False


def test_cover_block_renders_title_page() -> None:
    data = docx_fmt.build(
        {
            "title": "Annual Report",
            "blocks": [{"type": "cover", "subtitle": "FY2026"}],
        },
        ".",
    )
    doc = _reopen(data)
    assert doc.paragraphs[0].style.name == "Title"
    assert doc.paragraphs[0].text == "Annual Report"
    assert "FY2026" in [p.text for p in doc.paragraphs]
    # Title is not duplicated as a Heading 0 paragraph.
    title_paras = [p for p in doc.paragraphs if p.style.name == "Title"]
    assert len(title_paras) == 1


def test_keep_with_next_and_page_break_before() -> None:
    data = docx_fmt.build(
        {
            "blocks": [
                {"type": "heading", "level": 1, "text": "H", "keep_with_next": True},
                {"type": "paragraph", "text": "body", "page_break_before": True},
            ],
        },
        ".",
    )
    doc = _reopen(data)
    assert doc.paragraphs[0].paragraph_format.keep_with_next is True
    assert doc.paragraphs[1].paragraph_format.page_break_before is True


def test_table_repeat_header_and_column_widths() -> None:
    data = docx_fmt.build(
        {
            "blocks": [
                {
                    "type": "table",
                    "header": ["A", "B"],
                    "rows": [["1", "2"]],
                    "repeat_header": True,
                    "column_widths": [2.0, 3.5],
                }
            ],
        },
        ".",
    )
    doc = _reopen(data)
    table = doc.tables[0]
    assert "tblHeader" in table.rows[0]._tr.xml
    assert table.columns[0].width.inches == pytest.approx(2.0)
    assert table.columns[1].width.inches == pytest.approx(3.5)


def test_image_height_and_fit_preserve_aspect() -> None:
    from pathlib import Path

    src = Path("tests/fixtures/artifacts/workspace/figure.png")
    if not src.exists():
        pytest.skip("fixture image missing")
    data = docx_fmt.build(
        {
            "blocks": [
                {"type": "image", "path": "figure.png", "height_inches": 2},
                {"type": "image", "path": "figure.png", "fit": {"width": 3, "height": 3}},
            ],
        },
        "tests/fixtures/artifacts/workspace",
    )
    doc = _reopen(data)
    shapes = doc.inline_shapes
    assert len(shapes) == 2
    # 960x540 at 72dpi = 13.33x7.5in natural; height=2 → width ≈ 3.56
    assert shapes[0].width.inches == pytest.approx(3.56, abs=0.05)
    # fit 3x3 box: scale limited by width → ~3in wide, ~1.69in tall
    assert shapes[1].width.inches <= 3.0 + 0.01
    assert docx_fmt.validate(data)["valid"]


@pytest.mark.parametrize(
    "block",
    [
        {"type": "image", "path": "x.png", "width_inches": 4, "height_inches": 2},
        {"type": "section_break", "bogus": 1},
        {"type": "table", "header": [], "rows": [], "column_widths": [0.1]},
        {"type": "footer"},
        {"type": "paragraph", "text": "x", "unknown_key": 1},
    ],
)
def test_invalid_new_blocks_rejected(block: dict) -> None:
    with pytest.raises(ValueError):
        docx_fmt.build({"blocks": [block]}, ".")


def test_stable_block_ids_in_inspect_and_revise() -> None:
    spec = {
        "blocks": [
            {"id": "intro", "type": "paragraph", "text": "first"},
            {"type": "table", "id": "data", "header": ["A"], "rows": [["1"]]},
            {"type": "paragraph", "text": "last"},
        ]
    }
    data = docx_fmt.build(spec, ".")
    blocks = docx_fmt.inspect(data)["structure"]["blocks"]
    assert [b["id"] for b in blocks] == ["intro", "data", "b2"]
    assert blocks[1]["kind"] == "table" and blocks[1]["preview"] == "A"

    rev = docx_fmt.revise(
        data, [{"op": "replace_paragraph", "block": "intro", "text": "changed"}], "."
    )
    doc = _reopen(rev)
    assert doc.paragraphs[0].text == "changed"
    # IDs survive the revision — inspect still resolves them.
    assert docx_fmt.inspect(rev)["structure"]["blocks"][0]["id"] == "intro"


def test_block_id_rejects_table_and_unknown() -> None:
    data = docx_fmt.build(
        {"blocks": [{"type": "table", "id": "t1", "header": ["A"], "rows": [["1"]]}]}, "."
    )
    with pytest.raises(ValueError, match="no paragraph block"):
        docx_fmt.revise(data, [{"op": "replace_paragraph", "block": "t1", "text": "x"}], ".")
    with pytest.raises(ValueError, match="no paragraph block"):
        docx_fmt.revise(data, [{"op": "replace_paragraph", "block": "nope", "text": "x"}], ".")


def test_duplicate_and_invalid_block_ids_rejected() -> None:
    with pytest.raises(ValueError, match="duplicate block id"):
        docx_fmt.build(
            {
                "blocks": [
                    {"id": "x", "type": "paragraph", "text": "a"},
                    {"id": "x", "type": "paragraph", "text": "b"},
                ]
            },
            ".",
        )
    with pytest.raises(ValueError, match="id must be"):
        docx_fmt.build({"blocks": [{"id": "1bad!", "type": "paragraph", "text": "a"}]}, ".")


def test_appended_blocks_get_stable_ids() -> None:
    data = docx_fmt.build({"blocks": [{"type": "paragraph", "text": "one"}]}, ".")
    rev = docx_fmt.revise(
        data,
        [{"op": "append_blocks", "blocks": [{"id": "tail", "type": "paragraph", "text": "two"}]}],
        ".",
    )
    blocks = docx_fmt.inspect(rev)["structure"]["blocks"]
    assert blocks[-1]["id"] == "tail"


def _three_para_doc() -> bytes:
    return docx_fmt.build(
        {
            "blocks": [
                {"id": "a", "type": "paragraph", "text": "Alpha"},
                {"id": "b", "type": "paragraph", "text": "Beta"},
                {"id": "c", "type": "paragraph", "text": "Gamma"},
                {"id": "t", "type": "table", "header": ["H"], "rows": [["1"], ["2"]]},
            ]
        },
        ".",
    )


def test_insert_blocks_after_and_start() -> None:
    data = _three_para_doc()
    rev = docx_fmt.revise(
        data,
        [
            {
                "op": "insert_blocks",
                "after": "b",
                "blocks": [{"id": "mid", "type": "paragraph", "text": "Inserted"}],
            }
        ],
        ".",
    )
    assert [p.text for p in _reopen(rev).paragraphs] == [
        "Alpha",
        "Beta",
        "Inserted",
        "Gamma",
    ]
    rev2 = docx_fmt.revise(
        data,
        [
            {
                "op": "insert_blocks",
                "position": "start",
                "blocks": [{"type": "paragraph", "text": "First"}],
            }
        ],
        ".",
    )
    assert _reopen(rev2).paragraphs[0].text == "First"
    # inserted block carries a stable id
    assert docx_fmt.inspect(rev)["structure"]["blocks"][2]["id"] == "mid"


def test_remove_block_paragraph_list_and_table() -> None:
    data = docx_fmt.build(
        {
            "blocks": [
                {"id": "keep", "type": "paragraph", "text": "stay"},
                {"id": "lst", "type": "list", "items": ["i1", "i2", "i3"]},
                {"id": "tbl", "type": "table", "header": ["H"], "rows": [["1"]]},
            ]
        },
        ".",
    )
    rev = docx_fmt.revise(data, [{"op": "remove_block", "block": "lst"}], ".")
    doc = _reopen(rev)
    texts = [p.text for p in doc.paragraphs]
    assert "i1" not in texts and "i2" not in texts and "i3" not in texts
    assert "stay" in texts and len(doc.tables) == 1
    rev2 = docx_fmt.revise(rev, [{"op": "remove_block", "block": "tbl"}], ".")
    assert len(_reopen(rev2).tables) == 0


def test_style_block_formats_runs_and_flags() -> None:
    data = _three_para_doc()
    rev = docx_fmt.revise(
        data,
        [
            {
                "op": "style_block",
                "block": "a",
                "bold": True,
                "color": "#ff0000",
                "keep_with_next": True,
            }
        ],
        ".",
    )
    p = _reopen(rev).paragraphs[0]
    assert p.runs[0].font.bold is True
    assert str(p.runs[0].font.color.rgb) == "FF0000"
    assert p.paragraph_format.keep_with_next is True


def test_set_cell_by_table_block_id() -> None:
    data = _three_para_doc()
    rev = docx_fmt.revise(
        data, [{"op": "set_cell", "table": "t", "row": 1, "col": 0, "text": "99"}], "."
    )
    assert _reopen(rev).tables[0].rows[1].cells[0].text == "99"
    # table id survives the cell edit (bookmark preserved)
    assert "t" in [b["id"] for b in docx_fmt.inspect(rev)["structure"]["blocks"]]


def test_insert_rejects_section_break_and_bad_anchor() -> None:
    data = _three_para_doc()
    with pytest.raises(ValueError, match="section_break"):
        docx_fmt.revise(
            data,
            [{"op": "insert_blocks", "blocks": [{"type": "section_break"}]}],
            ".",
        )
    with pytest.raises(ValueError, match="no block with id"):
        docx_fmt.revise(
            data,
            [
                {
                    "op": "insert_blocks",
                    "after": "ghost",
                    "blocks": [{"type": "paragraph", "text": "x"}],
                }
            ],
            ".",
        )


def test_named_template_applies_preset_and_records_provenance() -> None:
    data = docx_fmt.build({"template": "report", "blocks": []}, ".")
    doc = _reopen(data)
    assert doc.styles["Heading 1"].font.name == "Georgia"
    assert doc.styles["Normal"].font.name == "Aptos"
    assert doc.core_properties.subject == "caberos-template:report"
    assert docx_fmt.inspect(data)["structure"]["template"] == "report"


def test_template_override_wins_per_key() -> None:
    data = docx_fmt.build(
        {"template": "report", "styles": {"body": {"size": 14}}, "blocks": []}, "."
    )
    doc = _reopen(data)
    assert doc.styles["Normal"].font.size.pt == 14
    # Untouched template keys still apply.
    assert doc.styles["Heading 1"].font.name == "Georgia"


def test_unknown_template_rejected() -> None:
    with pytest.raises(ValueError, match="template must be one of"):
        docx_fmt.build({"template": "resume", "blocks": []}, ".")


def test_diagnostics_flag_heading_jump_and_empty_heading() -> None:
    data = docx_fmt.build(
        {
            "blocks": [
                {"type": "heading", "level": 1, "text": "Top"},
                {"type": "heading", "level": 3, "text": "Deep"},
                {"type": "heading", "level": 2, "text": "  "},
            ]
        },
        ".",
    )
    diag = docx_fmt.inspect(data)["diagnostics"]
    assert any("heading-level-jump" in d for d in diag)
    assert any("empty-heading" in d for d in diag)


def test_clean_document_has_no_diagnostics() -> None:
    data = docx_fmt.build(
        {
            "blocks": [
                {"type": "heading", "level": 1, "text": "A"},
                {"type": "heading", "level": 2, "text": "B"},
                {"type": "paragraph", "text": "text"},
            ]
        },
        ".",
    )
    assert docx_fmt.inspect(data)["diagnostics"] == []
