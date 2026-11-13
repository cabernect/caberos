"""Synthetic W0 inputs, not production authoring or preservation guarantees."""

import re
import zipfile
from io import BytesIO
from xml.etree import ElementTree

from docx import Document
from openpyxl import load_workbook
from openpyxl.chart import BarChart, Reference
from openpyxl.formatting.rule import CellIsRule
from openpyxl.styles import PatternFill
from openpyxl.worksheet.datavalidation import DataValidation
from openpyxl.worksheet.table import Table, TableStyleInfo
from pptx import Presentation

FIXED_TIME = "2000-01-01T00:00:00Z"
MISSING_FONT = "CaberOS Fixture Missing Font 0000"
PML = "http://schemas.openxmlformats.org/presentationml/2006/main"


def canonical_office(data: bytes) -> bytes:
    """Normalize only package timestamps/order, including embedded Office ZIPs.

    This is fixture generation only. It must never normalize real revision bytes.
    """
    out = BytesIO()
    with zipfile.ZipFile(BytesIO(data)) as source, zipfile.ZipFile(out, "w") as target:
        for name in sorted(source.namelist()):
            payload = source.read(name)
            if name == "docProps/core.xml":
                payload = re.sub(
                    rb"(<dcterms:(?:created|modified)\b[^>]*>)[^<]*(</dcterms:\w+>)",
                    lambda match: match[1] + FIXED_TIME.encode() + match[2],
                    payload,
                )
            elif name.endswith((".xlsx", ".docx", ".pptx")):
                payload = canonical_office(payload)
            info = zipfile.ZipInfo(name, (2000, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3
            info.external_attr = 0o600 << 16
            target.writestr(info, payload)
    return out.getvalue()


def _saved(document) -> bytes:
    out = BytesIO()
    document.save(out)
    return out.getvalue()


def missing_font_deck(data: bytes) -> bytes:
    deck = Presentation(BytesIO(data))
    for slide in deck.slides:
        for shape in slide.shapes:
            if shape.has_text_frame:
                for paragraph in shape.text_frame.paragraphs:
                    for run in paragraph.runs:
                        run.font.name = MISSING_FONT
    return _saved(deck)


def missing_font_report(data: bytes) -> bytes:
    report = Document(BytesIO(data))
    report.styles["Normal"].font.name = MISSING_FONT
    for paragraph in report.paragraphs:
        for run in paragraph.runs:
            run.font.name = MISSING_FONT
    return _saved(report)


def externally_edited_deck(data: bytes) -> bytes:
    deck = Presentation(BytesIO(data))
    deck.slides[0].shapes.title.text = "External edit: Q3 Platform Review"
    deck.core_properties.last_modified_by = "Synthetic external editor"
    return _saved(deck)


def transition_deck(data: bytes) -> bytes:
    """A schema-shaped fade probe, not native-verified effect support."""
    out = BytesIO()
    with zipfile.ZipFile(BytesIO(data)) as source, zipfile.ZipFile(out, "w") as target:
        for name in source.namelist():
            payload = source.read(name)
            if name == "ppt/slides/slide1.xml":
                root = ElementTree.fromstring(payload)
                transition = ElementTree.Element(f"{{{PML}}}transition", {"spd": "slow"})
                ElementTree.SubElement(transition, f"{{{PML}}}fade")
                extension = root.find(f"{{{PML}}}extLst")
                index = list(root).index(extension) if extension is not None else len(root)
                root.insert(index, transition)
                payload = ElementTree.tostring(root, encoding="utf-8", xml_declaration=True)
            target.writestr(name, payload)
    return out.getvalue()


def uploaded_feature_workbook(data: bytes) -> bytes:
    """Build feature-bearing input outside CaberOS's structured create handler."""
    book = load_workbook(BytesIO(data))
    sheet = book["Weekly"]
    table = Table(displayName="WeeklyMetrics", ref="A1:D7")
    table.tableStyleInfo = TableStyleInfo(name="TableStyleMedium9", showRowStripes=True)
    sheet.add_table(table)
    chart = BarChart()
    chart.title = "Weekly p99 latency"
    chart.add_data(Reference(sheet, min_col=2, min_row=1, max_row=7), titles_from_data=True)
    chart.set_categories(Reference(sheet, min_col=1, min_row=2, max_row=7))
    sheet.add_chart(chart, "F2")
    validation = DataValidation(type="whole", operator="between", formula1=0, formula2=1000)
    sheet.add_data_validation(validation)
    validation.add("B2:B7")
    sheet.conditional_formatting.add(
        "B2:B7",
        CellIsRule(
            operator="greaterThan",
            formula=["350"],
            fill=PatternFill("solid", fgColor="FFCCCC"),
        ),
    )
    book["Notes"]["A3"] = "Synthetic protected sheet: preflight must report protection."
    book["Notes"].protection.sheet = True
    return _saved(book)


HOSTILE_HTML = """<!doctype html>
<html lang="en"><meta charset="utf-8"><title>DO NOT OPEN: isolation probe</title>
<body><h1>Opt-in isolated testing only</h1><script>
// The reserved .invalid domain carries no real endpoint or sensitive data.
const attempts = [
  () => parent.document.body.dataset.fixtureProbe = 'attempted',
  () => localStorage.setItem('fixture-probe', 'attempted'),
  () => fetch('/api/auth/me'),
  () => fetch('https://caberos-fixture.invalid/probe'),
  () => new WebSocket('wss://caberos-fixture.invalid/probe'),
  () => parent.postMessage({type:'fixture-forged-command', command:'terminal'}, '*'),
  () => window.__TAURI_INTERNALS__.invoke('fixture_probe'),
  () => window.open('https://caberos-fixture.invalid/popup', '_blank'),
];
for (const attempt of attempts) {
  try { Promise.resolve(attempt()).catch(() => {}); } catch {}
}
</script></body></html>
"""

LOOP_HTML = """<!doctype html>
<html lang="en"><meta charset="utf-8"><title>DO NOT OPEN: watchdog probe</title>
<body><h1>Opt-in isolated testing only</h1>
<script>while (true) { /* Deliberate infinite loop for watchdog testing. */ }</script>
</body></html>
"""
