"""Native layout regressions exercised through the real export interface."""

import copy
from io import BytesIO

import pytest
from pptx import Presentation

from agentos.artifacts import deck_exports, deck_pptx


@pytest.mark.parametrize("layout", ["title", "section", "content", "two_content"])
def test_multiline_title_stays_native_and_clear_of_body(layout):
    title = "An illustrative financial review with a longer descriptive heading"
    source = {
        "title": "Synthetic layout test",
        "slides": [
            {
                "title": title,
                "layout": layout,
                "blocks": [{"type": "paragraph", "text": "Keep this content editable."}],
            }
        ],
    }
    original = copy.deepcopy(source)
    prs = Presentation(BytesIO(deck_pptx.build(source)))
    slide = prs.slides[0]
    heading = slide.shapes.title
    body = next(
        s for s in slide.shapes if s.has_text_frame and s.text == "Keep this content editable."
    )
    assert heading.text == title
    assert heading.text_frame.paragraphs[0].font.size.pt >= 26
    assert heading.top + heading.height <= body.top
    assert body.top + body.height < prs.slide_height
    assert not any(s.shape_type == 13 for s in slide.shapes)
    assert source == original


def test_dense_table_and_paragraphs_fit_at_bounded_readable_sizes():
    paragraph = "Illustrative analysis preserves every original number and note. " * 4
    source = {
        "title": "Synthetic layout test",
        "slides": [
            {
                "title": "Growth, margins and illustrative comparisons",
                "blocks": [
                    {
                        "type": "table",
                        "rows": [
                            [
                                "Illustrative metric",
                                "Current quarter",
                                "Previous quarter",
                                "Change",
                            ],
                            *[[f"Metric {i}", "125.50", "110.25", "+13.8%"] for i in range(5)],
                        ],
                    },
                    {"type": "paragraph", "text": paragraph},
                    {"type": "paragraph", "text": paragraph},
                ],
            }
        ],
    }
    assert deck_exports.plan(source, "source-hash")["image_fallbacks"] == []
    prs = Presentation(BytesIO(deck_pptx.build(source)))
    slide = prs.slides[0]
    table = next(s.table for s in slide.shapes if s.has_table)
    assert len(table.rows) == 6
    assert table.cell(0, 0).text == "Illustrative metric"
    assert table.cell(1, 1).text == "125.50"
    paragraphs = [s for s in slide.shapes if s.has_text_frame and s.text == paragraph]
    assert len(paragraphs) == 2
    assert all(16 <= s.text_frame.paragraphs[0].font.size.pt <= 20 for s in paragraphs)
    assert any(s.text_frame.paragraphs[0].font.size.pt < 20 for s in paragraphs)
    assert table.cell(0, 0).text_frame.paragraphs[0].font.size.pt >= 12
    assert not any(s.shape_type == 13 for s in slide.shapes)
    shapes = [s for s in slide.shapes if s.has_table or s in paragraphs]
    for before, after in zip(shapes, shapes[1:]):
        assert before.top + before.height <= after.top


def test_table_assigns_the_measured_height_to_each_row():
    source = {
        "slides": [
            {
                "title": "Uneven table rows",
                "blocks": [
                    {
                        "type": "table",
                        "rows": [
                            ["Label", "Value"],
                            ["A longer illustrative label with many words. " * 5, "1"],
                            ["Short", "2"],
                        ],
                    }
                ],
            }
        ]
    }
    prs = Presentation(BytesIO(deck_pptx.build(source)))
    shape = next(s for s in prs.slides[0].shapes if s.has_table)
    rows = shape.table.rows
    assert rows[1].height > rows[0].height
    assert rows[1].height > rows[2].height
    assert sum(row.height for row in rows) == shape.height


def test_overflow_plan_keeps_real_slide_number_without_nested_prefix():
    source = {
        "slides": [
            {"title": "Native", "blocks": []},
            {"title": "Too dense", "blocks": [{"type": "paragraph", "text": "long text " * 500}]},
        ]
    }
    fallbacks = deck_exports.plan(source, "source-hash")["image_fallbacks"]
    assert len(fallbacks) == 1
    assert fallbacks[0]["slide"] == 2
    assert not fallbacks[0]["reason"].startswith("Slide ")
    assert "split the slide" in fallbacks[0]["reason"]


def test_fitting_does_not_borrow_space_from_another_column():
    source = {
        "slides": [
            {
                "title": "One overfull column",
                "layout": "two_content",
                "blocks": [{"type": "paragraph", "column": 0, "text": "long text " * 500}],
            }
        ]
    }
    with pytest.raises(ValueError, match="split the slide"):
        deck_pptx.build(source)


async def test_overflow_still_requires_explicit_current_plan_approval(monkeypatch):
    async def unexpected_capture(*args, **kwargs):
        pytest.fail("Unapproved fallback must never launch a browser capture")

    monkeypatch.setattr(deck_exports.deck_render, "render", unexpected_capture)
    source = {
        "slides": [
            {
                "title": "Overfull",
                "blocks": [
                    {"type": "paragraph", "text": "long text " * 500},
                ],
            }
        ]
    }
    plan = deck_exports.plan(source, "source-hash")
    for options in ({}, {"allow_fallback": True, "expected_plan": "obsolete-plan"}):
        with pytest.raises(ValueError, match="approval of the current export plan"):
            await deck_exports.pptx(
                source,
                source_sha256="source-hash",
                revision_id="rev-1",
                **options,
            )
    assert plan["image_fallbacks"][0]["slide"] == 1
