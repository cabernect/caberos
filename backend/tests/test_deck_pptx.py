"""The shared JSON source feeds the native PPTX renderer directly."""

import json
from io import BytesIO
from pathlib import Path

import pytest
from pptx import Presentation

from agentos.artifacts import deck_pptx
from agentos.artifacts.formats import deck, pptx

FIXTURES = Path(__file__).parent / "fixtures/artifacts"


def _spec():
    return json.loads((FIXTURES / "shared-presentation.json").read_text())


def test_same_spec_renders_native_editable_content(tmp_path):
    spec = _spec()
    web = deck.build(spec, FIXTURES)
    native = pptx.build(spec, FIXTURES)
    canonical = json.loads(web)
    assert canonical["kind"] == "deck"
    assert len(canonical["slides"]) == 4
    prs = Presentation(BytesIO(native))
    assert len(prs.slides) == 4
    assert [s.shapes.title.text for s in prs.slides] == [s.get("title", "") for s in spec["slides"]]
    assert any("Author content once" in s.text for s in prs.slides[1].shapes if s.has_text_frame)
    table = next(s.table for s in prs.slides[2].shapes if s.has_table)
    picture = next(s for s in prs.slides[3].shapes if s.shape_type == 13)
    assert table.cell(1, 0).text == "HTML"
    assert picture.image.blob == (FIXTURES / "workspace/figure.png").read_bytes()
    assert prs.slides[1].notes_slide.notes_text_frame.text == spec["slides"][1].get("notes", "")
    for slide in prs.slides:
        for shape in slide.shapes:
            assert shape.left >= 0 and shape.top >= 0
            assert shape.left + shape.width <= prs.slide_width + 2
            assert shape.top + shape.height <= prs.slide_height + 2
    # Native objects stay editable after save/reopen.
    prs.slides[0].shapes.title.text = "Edited in native text"
    table.cell(1, 0).text = "Edited table cell"
    saved = BytesIO()
    prs.save(saved)
    reopened = Presentation(BytesIO(saved.getvalue()))
    assert reopened.slides[0].shapes.title.text == "Edited in native text"
    assert (
        next(s.table for s in reopened.slides[2].shapes if s.has_table).cell(1, 0).text
        == "Edited table cell"
    )


def test_designed_eight_slide_deck_exports_native_objects():
    """A02: varied layouts, native chart/table/image, notes — all editable."""
    spec = {
        "kind": "deck",
        "title": "Designed analysis",
        "slides": [
            {
                "id": "cover",
                "title": "Q3 Analysis",
                "layout": "title",
                "blocks": [{"type": "paragraph", "text": "Eight-slide designed deck"}],
                "notes": "Open with the headline.",
            },
            {
                "id": "section",
                "title": "Market",
                "layout": "section",
                "blocks": [{"type": "divider"}],
            },
            {
                "id": "kpi",
                "title": "Key figures",
                "layout": "content",
                "blocks": [
                    {"type": "heading", "text": "Revenue grew"},
                    {
                        "type": "bullets",
                        "items": ["Revenue up", "Margin steady"],
                        "reveal": "items",
                    },
                    {"type": "table", "rows": [["Metric", "Q3"], ["Revenue", "42"]]},
                ],
            },
            {
                "id": "chart",
                "title": "Trend",
                "layout": "content",
                "blocks": [
                    {
                        "type": "chart",
                        "chart_type": "bar",
                        "categories": ["Q1", "Q2", "Q3"],
                        "series": [{"name": "Revenue", "values": [30, 36, 42]}],
                    }
                ],
            },
            {
                "id": "visual",
                "title": "Evidence",
                "layout": "two_content",
                "blocks": [
                    {"type": "image", "src": "figure.png", "alt": "Synthetic figure"},
                    {"type": "paragraph", "column": 1, "text": "Caption column."},
                ],
                "notes": "Image pinned per revision.",
            },
            {
                "id": "motion",
                "title": "Motion",
                "layout": "content",
                "blocks": [
                    {
                        "type": "paragraph",
                        "text": "Animated in slideshow only",
                        "animation": {"type": "rise", "duration_ms": 300},
                    }
                ],
                "transition": {"type": "fade", "duration_ms": 400},
            },
            {
                "id": "dense",
                "title": "Dense grid",
                "layout": "two_content",
                "blocks": [
                    {"type": "bullets", "column": 0, "items": ["Left a", "Left b"]},
                    {"type": "table", "column": 1, "rows": [["K", "V"], ["x", "1"]]},
                ],
            },
            {
                "id": "close",
                "title": "Summary",
                "layout": "section",
                "blocks": [{"type": "paragraph", "text": "Key takeaways"}],
            },
        ],
        "motion": {
            "transition": {"type": "fade", "duration_ms": 500},
            "entrance": {"type": "rise", "duration_ms": 250},
        },
    }
    canonical = json.loads(deck.build(spec, FIXTURES / "workspace"))
    prs = Presentation(BytesIO(deck_pptx.build(canonical)))
    assert len(prs.slides) == 8
    charts = [s for s in prs.slides for s in s.shapes if s.has_chart]
    assert len(charts) == 1
    assert charts[0].chart.plots[0].series[0].values == (30.0, 36.0, 42.0)
    pictures = [s for s in prs.slides for s in s.shapes if s.shape_type == 13]
    assert len(pictures) == 1
    tables = [s for s in prs.slides for s in s.shapes if s.has_table]
    assert len(tables) == 2
    notes = [s.notes_slide.notes_text_frame.text for s in prs.slides]
    assert notes[0] == "Open with the headline."
    assert notes[4] == "Image pinned per revision."
    titles = [s.shapes.title.text for s in prs.slides]
    assert titles[0] == "Q3 Analysis" and titles[-1] == "Summary"
    for slide in prs.slides:
        for shape in slide.shapes:
            assert shape.left >= 0 and shape.top >= 0
            assert shape.left + shape.width <= prs.slide_width + 2
            assert shape.top + shape.height <= prs.slide_height + 2
    # Motion is browser-only: export plan must disclose it, never claim it.
    from agentos.artifacts import deck_exports

    plan = deck_exports.plan(canonical, "sha")
    assert plan["declared_motion"] is True
    assert plan["browser_motion_exported"] is False
    assert plan["image_fallbacks"] == []


def test_export_uses_pinned_spec_assets_not_live_workspace(tmp_path):
    image = tmp_path / "figure.png"
    image.write_bytes((FIXTURES / "workspace/figure.png").read_bytes())
    spec = {
        "kind": "deck",
        "slides": [{"title": "Pinned", "blocks": [{"type": "image", "src": "figure.png"}]}],
    }
    canonical = json.loads(deck.build(spec, tmp_path))
    assert canonical["assets"][0]["data_uri"].startswith("data:image/png;base64,")
    image.write_bytes(b"not the original image anymore")
    out = deck_pptx.export_pptx(canonical, source_sha256="exact-source-hash", revision_id="rev-old")
    prs = Presentation(BytesIO(out))
    picture = next(s for s in prs.slides[0].shapes if s.shape_type == 13)
    assert picture.image.blob == (FIXTURES / "workspace/figure.png").read_bytes()
    notes = prs.slides[0].notes_slide.notes_text_frame.text
    assert notes == ""
    assert "rev-old" in prs.core_properties.comments
    from xml.etree import ElementTree
    from zipfile import ZipFile

    with ZipFile(BytesIO(out)) as package:
        metadata = ElementTree.fromstring(package.read("docProps/custom.xml"))
        manifest = json.loads(
            next(
                metadata.iter(
                    "{http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes}lpwstr"
                )
            ).text
        )
    assert manifest["source_sha256"] == "exact-source-hash"
    assert manifest["image_fallbacks"] == []
    # Tampering with the pinned snapshot is caught, not silently rendered.
    canonical["assets"][0]["sha256"] = "tampered"
    with pytest.raises(ValueError, match="hash mismatch"):
        deck_pptx.build(canonical)


def test_unsupported_slide_requires_declared_fallback():
    spec = {
        "kind": "deck",
        "slides": [
            {
                "title": "Editable",
                "blocks": [{"type": "paragraph", "text": "Keep as text"}],
            },
            {"title": "Custom", "html": "<p>Custom markup</p>"},
        ],
    }
    # "html" is not a valid block/layout in the canonical spec — an old or
    # foreign spec fails validation instead of silently degrading.
    with pytest.raises(ValueError):
        deck_pptx.build(spec)


def test_native_overflow_is_not_silently_clipped():
    with pytest.raises(ValueError, match="split the slide"):
        deck_pptx.build(
            {
                "kind": "deck",
                "slides": [
                    {
                        "title": "Too much",
                        "blocks": [{"type": "paragraph", "text": "long text " * 500}],
                    }
                ],
            }
        )


def test_unpinned_image_is_declared_fallback():
    spec = {
        "kind": "deck",
        "slides": [{"title": "Old", "blocks": [{"type": "image", "src": "gone.png"}]}],
    }
    assert 0 in deck_pptx.fallback_slides(spec)


def test_corrupt_asset_inventory_is_not_admitted():
    spec = {"kind": "deck", "slides": [{"title": "One"}], "assets": "not a list"}
    with pytest.raises(ValueError, match="assets must be a list"):
        deck_pptx.build(spec)
