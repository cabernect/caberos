"""W0 corpus properties only; no renderer, Office app or HTML script execution."""

import hashlib
import json
import runpy
import subprocess
import sys
import zipfile
from io import BytesIO
from pathlib import Path
from xml.etree import ElementTree

import pytest
from bs4 import BeautifulSoup
from docx import Document
from openpyxl import load_workbook
from pptx import Presentation

from agentos import previews
from agentos.artifacts.formats import docx, pptx, xlsx

FIXTURES = Path(__file__).parent / "fixtures" / "artifacts"


def test_corpus_regeneration_is_byte_stable_and_matches_local_corpus(tmp_path):
    first, second = tmp_path / "first", tmp_path / "second"
    for output in (first, second):
        subprocess.run(
            [sys.executable, str(FIXTURES / "generate.py"), "--output-dir", str(output)],
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
    for path in first.rglob("*"):
        if path.is_file():
            relative = path.relative_to(first)
            assert path.read_bytes() == (second / relative).read_bytes(), relative
            assert path.read_bytes() == (FIXTURES / relative).read_bytes(), relative


def test_normalization_removes_nested_zip_and_core_timestamp_variation():
    normalize = runpy.run_path(str(FIXTURES / "fixture_variants.py"))["canonical_office"]

    def package(year: int, nested: bytes | None = None) -> bytes:
        out = BytesIO()
        with zipfile.ZipFile(out, "w") as archive:
            info = zipfile.ZipInfo("docProps/core.xml", (year, 1, 1, 0, 0, 0))
            archive.writestr(
                info,
                f'<cp:coreProperties xmlns:cp="urn:cp" xmlns:dcterms="urn:dcterms">'
                f"<dcterms:modified>{year}-01-01T00:00:00Z</dcterms:modified>"
                "</cp:coreProperties>",
            )
            if nested:
                archive.writestr("ppt/embeddings/chart.xlsx", nested)
        return out.getvalue()

    older = package(2020, package(2020))
    newer = package(2025, package(2025))
    assert older != newer
    assert normalize(older) == normalize(newer)
    assert normalize(normalize(older)) == normalize(older)


@pytest.mark.parametrize(
    ("name", "handler"),
    [
        ("analysis-deck.pptx", pptx),
        ("analysis-deck-external-edit.pptx", pptx),
        ("deck-missing-font.pptx", pptx),
        ("deck-transition.pptx", pptx),
        ("report-missing-font.docx", docx),
        ("uploaded-features.xlsx", xlsx),
    ],
)
def test_variants_reopen_as_valid_office_packages(name, handler):
    assert handler.validate((FIXTURES / name).read_bytes())["valid"]


def test_font_and_external_edit_variants_contain_real_content_changes():
    baseline = Presentation(FIXTURES / "analysis-deck.pptx")
    changed = Presentation(FIXTURES / "analysis-deck-external-edit.pptx")
    assert changed.slides[0].shapes.title.text != baseline.slides[0].shapes.title.text
    deck = Presentation(FIXTURES / "deck-missing-font.pptx")
    assert deck.slides[0].shapes.title.text_frame.paragraphs[0].runs[0].font.name == (
        "CaberOS Fixture Missing Font 0000"
    )
    report = Document(FIXTURES / "report-missing-font.docx")
    assert report.styles["Normal"].font.name == "CaberOS Fixture Missing Font 0000"


def test_transition_probe_is_present_but_does_not_claim_playback():
    with zipfile.ZipFile(FIXTURES / "deck-transition.pptx") as archive:
        root = ElementTree.fromstring(archive.read("ppt/slides/slide1.xml"))
    ns = {"p": "http://schemas.openxmlformats.org/presentationml/2006/main"}
    assert root.find("p:transition/p:fade", ns) is not None
    manifest = json.loads((FIXTURES / "manifest.json").read_text())
    entry = next(f for f in manifest["files"] if f["file"] == "deck-transition.pptx")
    assert entry["expected"]["native_playback_verified"] is False


def test_existing_pptx_ids_survive_supported_reorder_and_title_revision(tmp_path):
    data = (FIXTURES / "analysis-deck.pptx").read_bytes()
    before = Presentation(BytesIO(data))
    original = before.slides[3]
    slide_id = original.slide_id
    shape_ids = [shape.shape_id for shape in original.shapes]
    changed = pptx.revise(
        data,
        [
            {"op": "move_slide", "from": 3, "to": 1},
            {"op": "set_title", "slide": 1, "text": "Reordered latency"},
        ],
        tmp_path,
    )
    after = Presentation(BytesIO(changed))
    assert after.slides[1].slide_id == slide_id
    assert [shape.shape_id for shape in after.slides[1].shapes] == shape_ids
    assert after.slides[1].shapes.title.text == "Reordered latency"


def test_uploaded_workbook_contains_features_outside_structured_create_surface():
    book = load_workbook(FIXTURES / "uploaded-features.xlsx")
    assert "WeeklyMetrics" in book["Weekly"].tables
    assert len(book["Weekly"].data_validations.dataValidation) == 1
    assert len(book["Weekly"].conditional_formatting) == 1
    assert book["Notes"].protection.sheet
    with zipfile.ZipFile(FIXTURES / "uploaded-features.xlsx") as archive:
        assert "xl/charts/chart1.xml" in archive.namelist()
        assert "xl/drawings/drawing1.xml" in archive.namelist()


def test_formula_types_and_expected_values_are_not_calculated_caches():
    book = load_workbook(FIXTURES / "workbook.xlsx")
    cached = load_workbook(FIXTURES / "workbook.xlsx", data_only=True)
    manifest = json.loads((FIXTURES / "manifest.json").read_text())
    entry = next(f for f in manifest["files"] if f["file"] == "workbook.xlsx")
    expected = entry["expected"]
    assert expected["formulas"] == 8
    assert expected["formula_results_verified"] is False
    for ref in expected["formula_results_after_native_recalculation"]:
        sheet, cell = ref.split("!")
        assert book[sheet][cell].data_type == "f"
        assert cached[sheet][cell].value is None
    assert book["Notes"]["B3"].value == "=SUM(Summary!B2:C2)"
    assert book["Notes"]["B4"].value == '=IF(Summary!C2>Summary!B2,"growth","flat")'
    assert book["Weekly"]["B8"].value == "=AVERAGE(B2:B7)"


def test_html_fixtures_are_text_only_with_explicit_execution_policy():
    manifest = json.loads((FIXTURES / "manifest.json").read_text())
    for entry in manifest["files"]:
        if entry["file"].startswith("hostile-"):
            assert entry["execution_policy"] == "isolated-opt-in-only"
            assert entry["expected"]["runtime_isolation_verified"] is False
            assert (
                hashlib.sha256((FIXTURES / entry["file"]).read_bytes()).hexdigest()
                == entry["sha256"]
            )
    html = (FIXTURES / "deck.html").read_text()
    soup = BeautifulSoup(html, "html.parser")
    ids = [slide["data-slide-id"] for slide in soup.select("section.slide")]
    assert ids == ["cover", "summary", "owners", "next"]
    assert "prefers-reduced-motion" in html
    assert "fixtureShowSlide" in html
    assert not soup.select("[src], link[href]")


@pytest.mark.parametrize(
    ("name", "kind", "content_key"),
    [
        ("analysis-deck.pptx", "slides", "slides"),
        ("analysis-deck-external-edit.pptx", "slides", "slides"),
        ("analysis-deck-longtitle.pptx", "slides", "slides"),
        ("deck-vietnamese.pptx", "slides", "slides"),
        ("deck-missing-font.pptx", "slides", "slides"),
        ("deck-transition.pptx", "slides", "slides"),
        ("report.docx", "document", "elements"),
        ("report-vietnamese.docx", "document", "elements"),
        ("report-missing-font.docx", "document", "elements"),
        ("workbook.xlsx", "workbook", "sheets"),
        ("uploaded-features.xlsx", "workbook", "sheets"),
    ],
)
def test_existing_office_previews_work_without_office_engine_or_creation_provenance(
    name, kind, content_key, monkeypatch
):
    def unexpected_process(*args, **kwargs):
        pytest.fail("Existing Office preview must not launch an Office engine")

    monkeypatch.setattr(subprocess, "Popen", unexpected_process)
    data = (FIXTURES / name).read_bytes()
    before = hashlib.sha256(data).hexdigest()
    uploaded = previews.preview_bytes(data, f"uploaded-{name}")
    generated = previews.preview_bytes(data, f"generated-{name}")
    assert uploaded["kind"] == generated["kind"] == kind
    assert uploaded[content_key]
    assert not uploaded.get("error")
    assert {k: v for k, v in uploaded.items() if k != "name"} == {
        k: v for k, v in generated.items() if k != "name"
    }
    assert hashlib.sha256(data).hexdigest() == before


def test_approximate_office_fixture_preview_retains_supported_content_not_native_layout():
    deck = previews.preview_bytes((FIXTURES / "analysis-deck.pptx").read_bytes(), "upload.pptx")
    assert deck["slide_count"] == 8
    assert deck["slides"][0]["title"] == "Q3 Platform Review"
    elements = [element for slide in deck["slides"] for element in slide["elements"]]
    assert {"chart", "table", "image", "notes"} <= {element["type"] for element in elements}
    assert any("latency win" in element.get("text", "") for element in elements)
    report = previews.preview_bytes((FIXTURES / "report.docx").read_bytes(), "upload.docx")
    assert any(element.get("text") == "1. Reliability" for element in report["elements"])
    assert "page_count" not in report  # Extracted content is not native Word pagination.
    book = previews.preview_bytes((FIXTURES / "uploaded-features.xlsx").read_bytes(), "upload.xlsx")
    assert book["formulas_recalculated"] is False
    notes = next(sheet for sheet in book["sheets"] if sheet["name"] == "Notes")
    assert notes["rows"][2][1] == "=SUM(Summary!B2:C2)"


@pytest.mark.parametrize(
    ("name", "kind"), [("bad.pptx", "slides"), ("bad.docx", "document"), ("bad.xlsx", "workbook")]
)
def test_malformed_office_preview_errors_are_separate_from_limited_supported_views(name, kind):
    payload = previews.preview_bytes(b"not an Office ZIP", name)
    assert payload["kind"] == kind
    assert payload["error"]


@pytest.mark.parametrize(
    ("name", "data", "kind"),
    [
        ("uploaded.md", b"# Notes", "markdown"),
        ("uploaded.txt", b"Notes", "text"),
        ("uploaded.py", b"print('notes')", "code"),
        ("uploaded.csv", b"Metric,Value\nLatency,279\n", "table"),
        ("uploaded.png", b"\x89PNG\r\n\x1a\n", "image"),
        ("uploaded.svg", b'<svg xmlns="http://www.w3.org/2000/svg"/>', "image"),
        ("uploaded.mp3", b"synthetic media metadata input", "media"),
        ("uploaded.mp4", b"synthetic media metadata input", "media"),
        ("uploaded.html", b"<script>throw Error('must not execute')</script>", "html"),
    ],
)
def test_non_office_upload_preview_support_is_preserved(name, data, kind):
    payload = previews.preview_bytes(data, name)
    assert payload["kind"] == kind
    if kind == "html":
        assert payload["content"] == data.decode()
        assert "<script" not in payload["html_document"]
        assert "script-src 'none'" in payload["html_document"]
