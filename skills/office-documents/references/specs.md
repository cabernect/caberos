# Artifact spec and op shapes

Exact shapes accepted by `artifact_create` (`spec`) and `artifact_revise` (`ops`). Unknown block types or ops are rejected with an error naming them.

## Word (`.docx`)

**Create spec**

```json
{
  "title": "Optional document title",
  "blocks": [
    {"type": "heading", "text": "Overview", "level": 1},
    {"type": "paragraph", "text": "Body text."},
    {"type": "list", "items": ["First", "Second"], "style": "bullet"},
    {"type": "table", "header": ["Name", "Owner"], "rows": [["API", "Ana"], ["UI", "Bo"]]},
    {"type": "image", "path": "attachments/diagram.png", "width_inches": 5},
    {"type": "page_break"}
  ]
}
```

- `list.style`: `"bullet"` (default) or `"number"`.
- `image.path` is workspace-relative; `width_inches` defaults to 4.

**Revise ops**

```json
[
  {"op": "append_blocks", "blocks": [{"type": "paragraph", "text": "New closing paragraph."}]},
  {"op": "replace_paragraph", "index": 3, "text": "Replacement text."},
  {"op": "set_cell", "table": 0, "row": 1, "col": 2, "text": "Done"}
]
```

- `index`, `table`, `row`, `col` are zero-based. Paragraph indexes count every paragraph, headings included — confirm positions with `artifact_inspect` (or `read_file`) before replacing.

## PDF (`.pdf`)

Use `artifact_create` with `format: "pdf"`, a `.pdf` path, and the same `title` and `blocks` shape shown in the Word create spec above. This creates a PDF directly; it does not convert an existing Office file. PDFs have no revise ops: create a new PDF for changed content.

## Excel (`.xlsx`)

**Create spec**

```json
{
  "sheets": [
    {
      "name": "Budget",
      "rows": [["Item", "Q1", "Q2", "Total"], ["Hosting", 120, 140, "=B2+C2"]],
      "cells": {"D4": {"formula": "=SUM(D2:D3)", "bold": true}},
      "freeze": "A2",
      "column_widths": {"A": 24, "B": 12},
      "formats": {"B2:D4": {"number_format": "#,##0.00"}}
    }
  ]
}
```

- `rows` are appended in order starting at row 1.
- `cells` maps a cell reference to a value (`5`, `"text"`) or an object with `value` or `formula`, plus the style keys below.
- `formats` maps a cell or range reference (e.g. `"B2"`, `"B2:D4"`) to the same style keys.
- `merges` lists range references to merge (e.g. `["A1:C1"]`).
- `auto_filter` is a range reference (e.g. `"A1:D20"`) or `true` for the used range.
- `row_heights` maps a 1-based row number to a height in points.
- Sheets are set to landscape and fit-to-width for printing in a spreadsheet application.

**Style keys** (cells, `formats`, and `style_range.style`):

| Key | Values |
|---|---|
| `bold`, `italic` | `true`/`false` |
| `color` | font color hex, `"RRGGBB"` or `"#RRGGBB"` |
| `font_size` | points, e.g. `12` |
| `fill` | solid background hex |
| `number_format` | Excel format string, e.g. `"#,##0.00"`, `"0.0%"` |
| `align` | `"left"`, `"center"`, `"right"`, `"justify"`, `"general"` |
| `valign` | `"top"`, `"center"`, `"bottom"` |
| `wrap_text` | `true`/`false` |
| `border` | `"thin"`, `"medium"`, `"thick"`, `"dashed"`, `"dotted"`, or `"double"`; or `{ "style": "thin", "color": "#RRGGBB" }` — applies to all four sides |

**Revise ops**

```json
[
  {"op": "set_cell", "sheet": "Budget", "cell": "B2", "value": 150},
  {"op": "set_cell", "sheet": "Budget", "cell": "D5", "formula": "=AVERAGE(D2:D3)"},
  {"op": "append_rows", "sheet": "Budget", "rows": [["Support", 40, 45, "=B5+C5"]]},
  {"op": "add_sheet", "name": "Notes", "rows": [["Assumptions"]]},
  {"op": "remove_sheet", "sheet": "Old"},
  {"op": "style_range", "sheet": "Budget", "range": "A1:D1",
   "style": {"bold": true, "fill": "#1F4E79", "color": "FFFFFF", "border": "thin"}},
  {"op": "merge_cells", "sheet": "Budget", "range": "A1:C1"},
  {"op": "set_column_width", "sheet": "Budget", "col": "A", "width": 28},
  {"op": "set_row_height", "sheet": "Budget", "row": 1, "height": 24},
  {"op": "set_auto_filter", "sheet": "Budget", "ref": "A1:D20"},
  {"op": "set_freeze", "sheet": "Budget", "ref": "A2"}
]
```

`add_sheet` accepts the same keys as a sheet in the create spec. `set_auto_filter`
and `set_freeze` accept `null` to clear.

## PowerPoint (`.pptx`)

**Create spec**

```json
{
  "slides": [
    {"layout": "title", "title": "Q3 Review", "subtitle": "Platform team"},
    {"layout": "title_content", "title": "Highlights", "blocks": [
      {"type": "bullets", "items": ["Latency down 30%", "Two launches"]},
      {"type": "notes", "text": "Speaker notes for this slide."}
    ]},
    {"layout": "title_only", "title": "Spend", "blocks": [
      {"type": "chart", "chart_type": "bar", "categories": ["Jul", "Aug", "Sep"],
       "series": [{"name": "Cloud", "values": [12, 14, 11]}]}
    ]},
    {"layout": "title_only", "title": "Owners", "blocks": [
      {"type": "table", "header": ["Area", "Owner"], "rows": [["API", "Ana"]]}
    ]},
    {"layout": "blank", "blocks": [
      {"type": "image", "path": "attachments/screenshot.png", "width_inches": 8},
      {"type": "text", "text": "Caption"}
    ]}
  ]
}
```

- `layout`: `title`, `title_content` (default), `title_only`, `blank`.
- `chart_type`: `bar` (default), `line`, `pie`.
- One visual block (table, chart, or image) per slide keeps the layout clean — blocks are placed at the same position below the title.

**Revise ops**

```json
[
  {"op": "add_slide", "slide": {"layout": "title_content", "title": "Next steps", "blocks": [{"type": "bullets", "items": ["Ship v2"]}]}},
  {"op": "move_slide", "from": 4, "to": 1},
  {"op": "set_title", "slide": 0, "text": "Q3 Review (final)"},
  {"op": "append_bullets", "slide": 1, "items": ["Hired two engineers"]}
]
```

Slide indexes are zero-based. `append_bullets` needs a slide with a content placeholder (the `title_content` layout).
