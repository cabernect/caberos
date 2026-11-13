"""Generate deterministic Office/HTML fixtures for the v0.2.2 renderer
bake-off and preview tests (W0).

Run from backend/: ``uv run python tests/fixtures/artifacts/generate.py``

Outputs land next to this script; ``manifest.json`` records sha256 + the
exact spec JSON used, so fixtures stay reproducible and diffable. Binary
outputs are generated locally; regenerate only when the spec or generator changes.
"""

import argparse
import hashlib
import json
from functools import partial
from importlib.metadata import version
from pathlib import Path

from fixture_variants import (
    HOSTILE_HTML,
    LOOP_HTML,
    canonical_office,
    externally_edited_deck,
    missing_font_deck,
    missing_font_report,
    transition_deck,
    uploaded_feature_workbook,
)
from PIL import Image, ImageDraw

from agentos.artifacts.formats import docx as docx_fmt
from agentos.artifacts.formats import pptx as pptx_fmt
from agentos.artifacts.formats import xlsx as xlsx_fmt

HERE = Path(__file__).parent
CORPUS_VERSION = 2


def _figure_png(path: Path) -> None:
    """Deterministic bar-chart figure — the 'supplied figure' for decks/docs.

    Fixed geometry and Pillow's bundled default font; no system font lookup.
    """
    W, H = 960, 540
    img = Image.new("RGB", (W, H), "#F7F5F0")
    d = ImageDraw.Draw(img)
    d.rectangle([40, 40, W - 40, H - 60], outline="#1F4E79", width=3)
    title = "Quarterly revenue index (fixture)"
    d.text((60, 60), title, fill="#1F4E79")
    cats = ["Q1", "Q2", "Q3", "Q4"]
    vals = [42, 58, 51, 67]
    base_y, top_y = H - 90, 110
    bar_w, gap = 90, 60
    x0 = 120
    max_v = 80
    for i, (c, v) in enumerate(zip(cats, vals)):
        x = x0 + i * (bar_w + gap)
        bh = int((v / max_v) * (base_y - top_y))
        d.rectangle([x, base_y - bh, x + bar_w, base_y], fill="#4A7C59")
        d.text((x + bar_w // 2 - 6, base_y + 10), c, fill="#222")
        d.text((x + bar_w // 2 - 10, base_y - bh - 22), str(v), fill="#222")
    d.line([60, base_y, W - 60, base_y], fill="#333", width=2)
    img.save(path, "PNG")


ANALYSIS_DECK_SPEC = {
    "slides": [
        {
            "layout": "title",
            "title": "Q3 Platform Review",
            "subtitle": "Reliability · Cost · Velocity — fixture deck",
        },
        {
            "layout": "title_content",
            "title": "Executive summary",
            "blocks": [
                {
                    "type": "bullets",
                    "items": [
                        "P99 latency down 31% quarter over quarter",
                        "Two launches shipped; one slipped to Q4",
                        "Infra spend held flat despite 22% traffic growth",
                    ],
                },
                {
                    "type": "notes",
                    "text": "Open with the latency win; it funds the rest of the narrative.",
                },
            ],
        },
        {
            "layout": "title_only",
            "title": "Revenue index by quarter",
            "blocks": [
                {
                    "type": "chart",
                    "chart_type": "bar",
                    "categories": ["Q1", "Q2", "Q3", "Q4"],
                    "series": [{"name": "Index", "values": [42, 58, 51, 67]}],
                }
            ],
        },
        {
            "layout": "title_only",
            "title": "Latency trend (ms, weekly p99)",
            "blocks": [
                {
                    "type": "chart",
                    "chart_type": "line",
                    "categories": ["W1", "W2", "W3", "W4", "W5", "W6"],
                    "series": [{"name": "p99", "values": [410, 388, 301, 290, 285, 279]}],
                }
            ],
        },
        {
            "layout": "title_content",
            "title": "Ownership map",
            "blocks": [
                {
                    "type": "table",
                    "header": ["Area", "Owner", "Status"],
                    "rows": [
                        ["API gateway", "Ana", "Healthy"],
                        ["Worker fleet", "Bo", "At risk"],
                        ["Data pipeline", "Cy", "Healthy"],
                    ],
                }
            ],
        },
        {
            "layout": "blank",
            "blocks": [
                {"type": "image", "path": "figure.png", "width_inches": 8},
                {
                    "type": "text",
                    "text": "Figure: quarterly revenue index — source: finance export, fixture data.",
                },
            ],
        },
        {
            "layout": "title_content",
            "title": "Trade-off analysis",
            "blocks": [
                {
                    "type": "bullets",
                    "items": [
                        "Caching layer: −28% p99, +$1.2k/mo — adopt",
                        "Queue rewrite: −40% tail, 3-week cost — defer to Q4",
                        "Regional failover: availability win, ops burden — pilot only",
                    ],
                }
            ],
        },
        {
            "layout": "title",
            "title": "Next quarter",
            "subtitle": "Ship queue pilot · hire two SREs · revisit pricing",
        },
    ]
}

LONG_TITLE_DECK_SPEC = {
    "slides": [
        {
            "layout": "title",
            "title": (
                "An Extremely Long Presentation Title That Will Not Fit on One Line "
                "And Is Designed to Exercise Title Wrapping, Overflow, and Truncation "
                "Behavior Across Every Candidate Renderer in the Bake-off Matrix"
            ),
            "subtitle": "Adversarial fixture — do not ship",
        },
        {
            "layout": "title_content",
            "title": "Body copy with an unusually long bullet that keeps going and going",
            "blocks": [
                {
                    "type": "bullets",
                    "items": [
                        "This bullet intentionally exceeds a comfortable line count so renderers "
                        "must decide between shrinking, clipping, or overflowing the slide.",
                        "Short bullet.",
                    ],
                }
            ],
        },
    ]
}

VIETNAMESE_DECK_SPEC = {
    "slides": [
        {
            "layout": "title",
            "title": "Báo cáo hiệu suất hệ thống quý ba",
            "subtitle": "Độ trễ · Chi phí · Tốc độ phát hành",
        },
        {
            "layout": "title_content",
            "title": "Tóm tắt điều hành",
            "blocks": [
                {
                    "type": "bullets",
                    "items": [
                        "Độ trễ p99 giảm 31% so với quý trước",
                        "Hai tính năng đã phát hành, một bị lùi sang quý bốn",
                        "Chi phí hạ tầng giữ nguyên dù lưu lượng tăng 22%",
                    ],
                }
            ],
        },
    ]
}

REPORT_DOCX_SPEC = {
    "title": "Q3 Platform Reliability Report",
    "blocks": [
        {
            "type": "paragraph",
            "text": "This report summarizes platform reliability, cost, and delivery performance for the third quarter. It is a fixture document for renderer evaluation.",
        },
        {"type": "heading", "text": "1. Reliability", "level": 1},
        {
            "type": "paragraph",
            "text": "P99 latency fell 31% quarter over quarter following the caching rollout and worker pool right-sizing. The tail improved most on read paths; write paths remain dominated by downstream queueing.",
        },
        {
            "type": "list",
            "items": [
                "Cache hit ratio rose from 61% to 78%",
                "Queue depth p99 down 44%",
                "One regional outage, 14 minutes, auto-failed-over",
            ],
            "style": "bullet",
        },
        {"type": "page_break"},
        {"type": "heading", "text": "2. Cost", "level": 1},
        {
            "type": "paragraph",
            "text": "Infrastructure spend was flat at $48.2k despite 22% traffic growth, driven by reserved-capacity renegotiation and spot-instance adoption for batch workloads.",
        },
        {
            "type": "table",
            "header": ["Service", "Q2", "Q3", "Delta"],
            "rows": [
                ["Compute", "$21.4k", "$20.9k", "-2.3%"],
                ["Storage", "$9.1k", "$9.4k", "+3.3%"],
                ["Network", "$17.7k", "$18.0k", "+1.7%"],
            ],
        },
        {"type": "page_break"},
        {"type": "heading", "text": "3. Delivery", "level": 1},
        {
            "type": "paragraph",
            "text": "Two launches shipped on schedule; the queue-rewrite project slipped to Q4 after a scope review. Incident count fell to 3 from 7, with median time-to-detect under 4 minutes.",
        },
        {"type": "image", "path": "figure.png", "width_inches": 5.5},
        {"type": "paragraph", "text": "Figure 1 — quarterly revenue index (fixture data)."},
        {"type": "page_break"},
        {"type": "heading", "text": "4. Recommendations", "level": 1},
        {
            "type": "list",
            "items": [
                "Adopt the caching layer org-wide",
                "Pilot regional failover in one cell",
                "Renegotiate reserved capacity before Q4 renewal",
            ],
            "style": "number",
        },
        {"type": "heading", "text": "Appendix A — Methodology", "level": 2},
        {
            "type": "paragraph",
            "text": "Metrics are derived from the observability warehouse, fixture-sampled for determinism. Percentiles use nearest-rank over 5-minute windows.",
        },
    ],
}

VIETNAMESE_DOCX_SPEC = {
    "title": "Báo cáo độ tin cậy nền tảng quý ba",
    "blocks": [
        {
            "type": "paragraph",
            "text": "Báo cáo này tóm tắt hiệu suất độ tin cậy, chi phí và tiến độ phát triển của nền tảng trong quý ba. Đây là tài liệu mẫu để đánh giá bộ kết xuất.",
        },
        {"type": "heading", "text": "1. Độ tin cậy", "level": 1},
        {
            "type": "paragraph",
            "text": "Độ trễ p99 giảm 31% so với quý trước sau khi triển khai lớp bộ nhớ đệm và điều chỉnh quy mô nhóm worker. Đuôi độ trễ cải thiện rõ nhất ở các đường đọc.",
        },
        {
            "type": "list",
            "items": [
                "Tỷ lệ trúng bộ nhớ đệm tăng từ 61% lên 78%",
                "Độ sâu hàng đợi p99 giảm 44%",
                "Một sự cố khu vực, 14 phút, tự động chuyển dự phòng",
            ],
            "style": "bullet",
        },
        {"type": "page_break"},
        {"type": "heading", "text": "2. Khuyến nghị", "level": 1},
        {
            "type": "list",
            "items": [
                "Áp dụng lớp bộ nhớ đệm trên toàn tổ chức",
                "Thử nghiệm chuyển dự phòng khu vực ở một cụm",
            ],
            "style": "number",
        },
    ],
}

WORKBOOK_XLSX_SPEC = {
    "sheets": [
        {
            "name": "Summary",
            "rows": [
                ["Metric", "Q2", "Q3", "Delta"],
                ["Revenue index", 58, 67, "=C2-B2"],
                ["P99 latency (ms)", 410, 279, "=C3-B3"],
                ["Infra spend ($k)", 48.2, 48.2, "=C4-B4"],
            ],
            "cells": {"D2": {"formula": "=C2-B2", "bold": True}},
            "formats": {
                "A1:D1": {"bold": True, "fill": "#1F4E79", "color": "FFFFFF", "border": "thin"},
                "B2:D4": {"number_format": "#,##0.0"},
                "D2:D4": {"number_format": "+#,##0.0;-#,##0.0;0"},
            },
            "merges": ["A6:C6"],
            "freeze": "A2",
            "auto_filter": "A1:D4",
            "column_widths": {"A": 22, "B": 12, "C": 12, "D": 12},
            "row_heights": {1: 24},
        },
        {
            "name": "Weekly",
            "rows": [
                ["Week", "p99 ms", "Requests", "Error rate"],
                ["W1", 410, 182000, 0.012],
                ["W2", 388, 191000, 0.011],
                ["W3", 301, 205000, 0.009],
                ["W4", 290, 214000, 0.008],
                ["W5", 285, 220000, 0.007],
                ["W6", 279, 231000, 0.006],
                ["Avg", "=AVERAGE(B2:B7)", "=SUM(C2:C7)", "=AVERAGE(D2:D7)"],
            ],
            "formats": {
                "A1:D1": {"bold": True, "fill": "#4A7C59", "color": "FFFFFF"},
                "D2:D8": {"number_format": "0.0%"},
                "C2:C8": {"number_format": "#,##0"},
            },
            "freeze": "A2",
            "auto_filter": True,
        },
        {
            "name": "Notes",
            "rows": [
                ["Fixture workbook — deterministic content for renderer tests."],
                ["Formulas are authored, not evaluated by CaberOS."],
                ["Cross-sheet sum", "=SUM(Summary!B2:C2)"],
                ["Conditional result", '=IF(Summary!C2>Summary!B2,"growth","flat")'],
            ],
            "formats": {"A1:A2": {"italic": True, "color": "666666"}},
        },
    ]
}

DECK_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Q3 Platform Review — HTML deck fixture</title>
<style>
  body { margin: 0; font-family: -apple-system, "Helvetica Neue", sans-serif; background: #111; color: #eee; }
  .slide { display: none; min-height: 100vh; padding: 8vh 10vw; box-sizing: border-box; }
  .slide.active { display: flex; flex-direction: column; justify-content: center; }
  .slide.active { animation: enter 240ms ease-out; }
  @keyframes enter { from { opacity: 0; transform: translateY(12px); } to { opacity: 1; transform: none; } }
  @media (prefers-reduced-motion: reduce) { .slide.active { animation: none; } }
  body[data-capture="stable"] .slide.active { animation: none; }
  h1 { font-size: 3.4rem; margin: 0 0 .4em; }
  h2 { font-size: 2.2rem; color: #9ecbff; margin: 0 0 .6em; }
  ul { font-size: 1.5rem; line-height: 1.7; padding-left: 1.2em; }
  .nav { position: fixed; bottom: 18px; right: 22px; font-size: .9rem; color: #888; }
  table { border-collapse: collapse; font-size: 1.3rem; }
  td, th { border: 1px solid #444; padding: .45em .9em; }
</style>
</head>
<body>
<section class="slide active" data-slide-id="cover"><h1>Q3 Platform Review</h1><p>HTML deck fixture — keyboard: ←/→ to navigate.</p></section>
<section class="slide" data-slide-id="summary"><h2>Executive summary</h2><ul><li>P99 latency down 31%</li><li>Two launches shipped</li><li>Spend flat despite 22% growth</li></ul></section>
<section class="slide" data-slide-id="owners"><h2>Ownership</h2><table><tr><th>Area</th><th>Owner</th></tr><tr><td>API gateway</td><td>Ana</td></tr><tr><td>Worker fleet</td><td>Bo</td></tr></table></section>
<section class="slide" data-slide-id="next"><h2>Next quarter</h2><ul><li>Ship queue pilot</li><li>Hire two SREs</li></ul></section>
<div class="nav"><span id="pos">1</span> / 4</div>
<script>
const s=[...document.querySelectorAll('.slide')],p=document.getElementById('pos');let i=0;
function go(n){i=(n+s.length)%s.length;s.forEach((e,j)=>e.classList.toggle('active',j===i));p.textContent=i+1;}
addEventListener('keydown',e=>{if(e.key==='ArrowRight')go(i+1);if(e.key==='ArrowLeft')go(i-1);});
// Fixture-only capture hook; not a proposed privileged application bridge.
window.fixtureShowSlide=id=>{const n=s.findIndex(e=>e.dataset.slideId===id);if(n<0)throw Error('Unknown slide');document.body.dataset.capture='stable';go(n);};
</script>
</body>
</html>
"""


def _write(
    name: str,
    data: bytes,
    spec: dict | None,
    manifest: list,
    *,
    output_dir: Path,
    expected: dict | None = None,
    execution_policy: str = "parse-only",
) -> None:
    if Path(name).suffix in {".pptx", ".docx", ".xlsx"}:
        data = canonical_office(data)
    out = output_dir / name
    out.write_bytes(data)
    manifest.append(
        {
            "file": name,
            "sha256": hashlib.sha256(data).hexdigest(),
            "bytes": len(data),
            "spec": spec,
            "expected": expected or {},
            "execution_policy": execution_policy,
        }
    )


def main(output_dir: Path = HERE) -> None:
    workspace = output_dir / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    _figure_png(workspace / "figure.png")
    write = partial(_write, output_dir=output_dir)

    manifest: list = []

    deck = pptx_fmt.build(ANALYSIS_DECK_SPEC, workspace)
    write(
        "analysis-deck.pptx",
        deck,
        {"spec": ANALYSIS_DECK_SPEC},
        manifest,
        expected={"slides": 8, "charts": 2, "tables": 1, "images": 1},
    )

    write(
        "analysis-deck-longtitle.pptx",
        pptx_fmt.build(LONG_TITLE_DECK_SPEC, workspace),
        {"spec": LONG_TITLE_DECK_SPEC},
        manifest,
        expected={"slides": 2, "review": "Title wrapping/overflow must be measured by renderer."},
    )
    write(
        "deck-vietnamese.pptx",
        pptx_fmt.build(VIETNAMESE_DECK_SPEC, workspace),
        {"spec": VIETNAMESE_DECK_SPEC},
        manifest,
        expected={"slides": 2, "review": "Vietnamese glyphs and diacritics."},
    )

    report = docx_fmt.build(REPORT_DOCX_SPEC, workspace)
    write(
        "report.docx",
        report,
        {"spec": REPORT_DOCX_SPEC},
        manifest,
        expected={"tables": 1, "images": 1, "target_pages": [4, 6], "page_count_verified": False},
    )
    write(
        "report-vietnamese.docx",
        docx_fmt.build(VIETNAMESE_DOCX_SPEC, workspace),
        {"spec": VIETNAMESE_DOCX_SPEC},
        manifest,
        expected={"review": "Vietnamese glyphs and diacritics."},
    )

    workbook = xlsx_fmt.build(WORKBOOK_XLSX_SPEC, workspace)
    formula_results = {
        "Summary!D2": 9,
        "Summary!D3": -131,
        "Summary!D4": 0,
        "Weekly!B8": 325.5,
        "Weekly!C8": 1243000,
        "Weekly!D8": 0.008833333333333334,
        "Notes!B3": 125,
        "Notes!B4": "growth",
    }
    write(
        "workbook.xlsx",
        workbook,
        {"spec": WORKBOOK_XLSX_SPEC},
        manifest,
        expected={
            "sheets": ["Summary", "Weekly", "Notes"],
            "formulas": 8,
            "formula_results_after_native_recalculation": formula_results,
            "formula_results_verified": False,
        },
    )

    html_bytes = DECK_HTML.encode("utf-8")
    write(
        "deck.html",
        html_bytes,
        {"note": "HTML deck with keyboard navigation"},
        manifest,
        expected={"slides": 4, "playback_verified": False},
    )

    write(
        "analysis-deck-external-edit.pptx",
        externally_edited_deck(deck),
        {"note": "Synthetic external title and editor metadata change"},
        manifest,
        expected={"slides": 8, "first_title": "External edit: Q3 Platform Review"},
    )

    for name, data, expected in (
        (
            "deck-missing-font.pptx",
            missing_font_deck(deck),
            {"review": "Missing font substitution"},
        ),
        (
            "report-missing-font.docx",
            missing_font_report(report),
            {"review": "Missing font substitution"},
        ),
        (
            "deck-transition.pptx",
            transition_deck(deck),
            {"transition": "fade", "native_playback_verified": False},
        ),
        (
            "uploaded-features.xlsx",
            uploaded_feature_workbook(workbook),
            {
                "tables": 1,
                "charts": 1,
                "data_validations": 1,
                "conditional_formats": 1,
                "protected_sheet": "Notes",
                "preservation_verified": False,
            },
        ),
    ):
        write(
            name,
            data,
            {"note": "Synthetic variant; not authored by the structured spec"},
            manifest,
            expected=expected,
        )
    for name, content in (
        ("hostile-isolation.html", HOSTILE_HTML),
        ("hostile-loop.html", LOOP_HTML),
    ):
        write(
            name,
            content.encode(),
            {"note": "Dangerous opt-in runtime probe; never auto-open"},
            manifest,
            execution_policy="isolated-opt-in-only",
            expected={"runtime_isolation_verified": False},
        )

    (output_dir / "manifest.json").write_text(
        json.dumps(
            {
                "generator": "tests/fixtures/artifacts/generate.py",
                "corpus_version": CORPUS_VERSION,
                "environment": {
                    name: version(name)
                    for name in ("python-pptx", "python-docx", "openpyxl", "pillow")
                },
                "purpose": "v0.2.2 W0 renderer bake-off + preview fixtures",
                "asset": {
                    "file": "workspace/figure.png",
                    "sha256": hashlib.sha256((workspace / "figure.png").read_bytes()).hexdigest(),
                    "source": "Synthetic geometry/text generated by generate.py; no downloaded media",
                    "font": "Pillow bundled default; font licensing follows the installed Pillow distribution",
                    "license": "Repository LICENSE for authored content; no font file embedded",
                },
                "files": manifest,
            },
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"wrote {len(manifest)} fixtures + manifest.json to {output_dir}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=HERE)
    main(parser.parse_args().output_dir)
