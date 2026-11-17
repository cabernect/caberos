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

For new presentations, first create the canonical `.deck.json` source described
below. When a real PowerPoint file is requested, also call `artifact_create`
with `format: "pptx"`, a `.pptx` path, and that same `kind: "deck"` spec.
The native renderer consumes the spec directly; it never parses HTML.
The two files are separate tracked artifacts, not an automatic sync pair.
PPTX creation can fail on content that passes deck validation.

## Presentation deck (`.deck.json`)

The canonical presentation source — one JSON spec drives the slide preview in
the panel and the native PowerPoint output. Use `format: "deck"` and a
`.deck.json` path for the source; the compound filename is required.

**Create spec**

```json
{
  "kind": "deck",
  "version": 1,
  "title": "Q3 Review",
  "theme": {"background": "#FBFAF7", "accent": "#3F6212", "text": "#1C1917", "font": "sans"},
  "slides": [
    {"id": "cover", "layout": "title", "title": "Q3 Review",
     "blocks": [{"type": "paragraph", "text": "What we shipped"}],
     "notes": "Open with the headline number."},
    {"id": "body", "layout": "content", "title": "Highlights", "blocks": [
      {"type": "bullets", "items": ["Two releases shipped", "Support handoff completed"]}
    ]},
    {"id": "owners", "layout": "content", "title": "Next steps", "blocks": [
      {"type": "table", "rows": [["Work", "Owner"], ["Launch checklist", "Platform team"]]}
    ]}
  ]
}
```

- `theme.font`: `sans` (default), `serif`, or `mono`. Colors are `#RRGGBB`.
- `slide.layout`: `content` (default), `title` or `section` (vertically centered cover/divider), `two_content` (blocks split into columns by `column: 0|1`, default left).
- `slide.id`: optional stable id (`s1`, `s2`… auto-assigned); duplicate ids rejected. Max 100 slides.
- Blocks: `heading` (`text`), `paragraph` (`text`), `bullets` (`items`), `table` (`rows` — first row is the header), `image` (`src` + `alt`), `divider`. Give blocks stable `id` values; missing ids are assigned per slide, duplicates are rejected.
- `notes`: presenter notes — preserved into the PPTX speaker notes.
- `image.src` is a **workspace-relative raster path** (png/jpg/gif/webp, ≤4MB each, ≤20 assets/25MB total); `alt` is descriptive text. For example: `{"type":"image","src":"attachments/diagram.png","alt":"System overview"}`. The file must exist before creation. Bytes are pinned into the source as embedded snapshots, so export of that source does not reread a changed image. The current revise implementation rebuilds snapshots from workspace assets: keep those files available and inspect asset hashes after revising.
- Author **content and structure**, not styling — theme tokens own the look.
- `two_content` assigns blocks with `column: 0` (left) or `column: 1` (right) in the preview. Native PPTX currently lays blocks out sequentially; it does not reproduce those columns or the preview's centered section layout.
- Charts, arbitrary HTML/CSS/JavaScript, free positioning, and custom font names are not supported. Use a small data table or an existing raster image instead of inventing a `chart` block.
- Keep titles short, bullets concise (roughly 3-5 short items), and tables small. Native tables allow 1-12 columns, but that is a parser limit, not a readability target. Avoid combining an image, table, and long text on one slide; split the story across slides. These are authoring guidelines, not a guarantee of fit.

**Revise ops**

```json
[
  {"op": "set_title", "title": "Q3 Review v2"},
  {"op": "set_theme", "theme": {"background": "#FBFAF7", "accent": "#B45309", "text": "#1C1917", "font": "sans"}},
  {"op": "set_slide", "slide": "body", "value": {"id": "body", "title": "Highlights (updated)", "blocks": []}},
  {"op": "add_slide", "slide": {"blocks": [{"type": "divider"}]}, "index": 1},
  {"op": "remove_slide", "slide": 2},
  {"op": "move_slide", "from": 0, "to": 2}
]
```

- `slide` refs and `move_slide.from` are a 0-based index or slide id. `move_slide.to` as an integer is the final insertion index (clamped to bounds); as an id, inserts before that slide after the source is removed. Do not use the source id as its own destination.
- Prefer targeted block operations, for example `{"op":"set_text","slide_id":"body","block_id":"summary","value":"Shorter wording"}`. `set_bullets` takes an items array; `set_table` takes a rows array. `set_block` takes an allowlisted field patch, including chart categories/series. Optional `expected_block_hash` uses the hash from inspect as a precondition.
- `add_block`, `remove_block`, `replace_block`, and `move_block` use stable slide/block IDs. `duplicate_slide`, `set_slide_title`, `set_slide_layout`, and `set_notes` support slide-level changes. Every batch validates before publication; stale bases fail without a proposal-review workflow.
- `set_slide` replaces the entire slide via `value`, not `slide`. Read the current source first and preserve its id, notes, and all unrelated blocks; the shortened example above intentionally replaces all blocks.
- `set_theme` replaces the entire theme; include unchanged tokens. `add_slide.index` inserts after the referenced slide (index or id); omit it to append. A deck must keep at least one slide.
- The file is plain canonical JSON. It opens as rendered slides with **Slides / Source** and **Slideshow** controls; Source is read-only and bounded, not an inline editor. Normal preview shows the complete slide; Slideshow plays the motion below. Autoplay is not implemented.
- **Export PPTX** downloads native text, tables, and images from the exact previewed source hash. Provenance and static-motion limitations live in file metadata; authored speaker notes remain unchanged. Native layouts support multiline titles and bounded fitting (body 20-16 pt, tables 14-12 pt). These are conservative layout estimates, not proof of identical rendering in every Office application. Content that still cannot fit reports its slide and reason; any offered image fallback needs explicit approval and loses per-object editability on those slides only. Broken assets are refused. Split or simplify the source if editability is required. Portable HTML is not shipped; deck-to-PDF acceptance remains separate.

### Motion (Slideshow Only)

```json
{
  "motion": {
    "transition": {"type": "fade", "duration_ms": 350},
    "entrance": {"type": "rise", "duration_ms": 250}
  }
}
```

This is a fragment to merge into the deck spec, not a complete deck.
`motion.transition` sets the deck default (`none`, `fade`, `slide`);
`slide.transition` overrides it. `motion.entrance` sets block entrances
(`none`, `fade`, `rise`); `block.animation` overrides it. Effects are objects
with only `type` and `duration_ms` (integer 0-2000, default 300).
Missing motion leaves older decks static.

`block.reveal: true` reserves one click for the entire block.
For bullets, `reveal: "items"` reserves one click per item.
Unflagged blocks enter on slide arrival. Reveals follow block source order
(including across columns), not object ids. Use stable ids and preserve them
when revising. A revealed block defaults to fade if no entrance was chosen.
Next reveals the next item before advancing slides; Back undoes reveals, then
returns to the prior slide fully revealed. Home resets the first slide;
End shows the last slide fully revealed. Users requesting reduced motion see
all content immediately with no effects. Motion uses fixed supported effects,
never executable code. PPTX currently exports the final state without any of
these transitions or animations; disclose this rather than promising native
PowerPoint motion.

## Existing PPTX Compatibility

Existing `.pptx` files can still be adopted, inspected, and revised directly.
This is not the canonical deck workflow and does not recover a `.deck.json`
source or import the original PowerPoint design into the deck renderer.

Compatibility-only ops (zero-based indexes):

```json
[
  {"op": "set_title", "slide": 0, "text": "Updated title"},
  {"op": "append_bullets", "slide": 1, "items": ["New item"]},
  {"op": "move_slide", "from": 2, "to": 1},
  {"op": "add_slide", "slide": {"layout": "title_content", "title": "Next steps", "blocks": [{"type": "bullets", "items": ["Confirm owners"]}]}}
]
```

`append_bullets` needs a content placeholder. Compatibility layouts
(`title`, `title_content`, `title_only`, `blank`) and blocks (`text`, `bullets`,
`table` with `header`/`rows`, `chart`, `image` with `path`, `notes`) belong only
to this direct-PPTX path. Do not mix them with deck layouts or blocks, and do
not apply deck ops such as `set_slide` or `set_theme` to PPTX bytes.
