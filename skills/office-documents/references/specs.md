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
    {"type": "image", "path": "attachments/diagram.png", "fit": {"width": 6, "height": 3}},
    {"type": "caption", "text": "Figure 1: architecture overview"},
    {"type": "page_break"}
  ],
  "header": {"text": "Internal draft", "align": "center"},
  "footer": {"page_numbers": true, "total_pages": true, "align": "center"},
  "page": {"size": "a4", "margins": {"top": 0.8, "bottom": 0.8, "left": 1.0, "right": 1.0}},
  "styles": {
    "title": {"font": "Georgia", "size": 28, "color": "#1c1917"},
    "heading": {"font": "Georgia", "size": 18, "color": "#3f6212", "space_after": 8},
    "h1": {"size": 24},
    "body": {"font": "Aptos", "size": 11, "line_spacing": 1.25},
    "list": {"space_after": 4},
    "caption": {"size": 9, "color": "#666666", "italic": true},
    "table": {"size": 9, "color": "#333333"}
  }
}
```

- `list.style`: `"bullet"` (default) or `"number"`.
- `image.path` is workspace-relative. Sizing takes **at most one** of `width_inches` (default 4), `height_inches`, or `fit: {"width": w, "height": h}` which scales the image to fit the box preserving aspect ratio. Max 20 inches.
- `caption` is a small figure/table caption line; place it right after the `image` or `table` block it describes.
- `cover`: `{"type": "cover", "title": "...", "subtitle": "..."}` renders a title page and a following page break. When a cover block exists, the spec-level `title` is rendered on the cover instead of as a heading.
- `section_break`: `{"type": "section_break", "header": {...}, "footer": {...}, "page": {...}}` starts a new Word section (new page). Sections without overrides inherit the previous section's header/footer/page setup. `header`/`footer`/`page` accept the same shapes as the spec-level keys.
- `header`/`footer` (spec-level or per section): `text` (plain string), `align` (`left`/`center`/`right`), `page_numbers` and `total_pages` (booleans adding live PAGE/NUMPAGES fields — Word calculates real numbers on open; the stored value is a placeholder).
- `table` extras: `column_widths` (list of widths in inches, 0.2–10, disables autofit) and `repeat_header: true` (header row repeats on every printed page the table spans).
- Flow control on `heading`/`paragraph`/`caption`/`list`/`table`/`image`/`cover`: `keep_with_next: true` keeps the block on the same page as the following one; `page_break_before: true` forces a page break. On `list`, keep applies between items and page-break-before applies to the first item.
- `page` is optional. `size` is `"letter"` (default), `"legal"`, or `"a4"`; `margins` takes `top`/`bottom`/`left`/`right` in inches (0.3–2.5, default 1).
- `styles` is optional; omitted fields keep the document's built-in defaults. Roles: `title`, `heading` (all levels), `h1`–`h6` (per-level overrides), `body`, `list`, `caption`, `table`. Per style: `font` (name), `size` (points, 6–96), `color` (`#RRGGBB`), `bold`, `italic`, `space_before`/`space_after` (points, 0–72), `line_spacing` (0.8–3). `table` applies font/size/color to cells and always bolds the header row; it does not support spacing keys.
- Styles edit the document's named Word styles, so the output stays fully editable in Word.
- `template` (optional): `"memo"`, `"report"`, or `"letter"` — a named preset for page setup and core styles. Explicit `page`/`styles` keys override template values per-key. The template name is recorded in the file's subject property.
- Every content block accepts an optional `"id"` (1–36 chars, letter then letters/digits/`_`/`-`). Blocks without one get `b0`, `b1`, … in spec order. Ids are stored as Word bookmarks inside the `.docx`, so they survive save/reopen and revisions — use them for targeted edits instead of paragraph indexes.

**Revise ops**

```json
[
  {"op": "append_blocks", "blocks": [{"type": "paragraph", "text": "New closing paragraph."}]},
  {"op": "insert_blocks", "after": "summary", "blocks": [{"type": "paragraph", "text": "Inserted."}]},
  {"op": "replace_paragraph", "block": "summary", "text": "Replacement text."},
  {"op": "replace_paragraph", "index": 3, "text": "Replacement text."},
  {"op": "remove_block", "block": "b2"},
  {"op": "style_block", "block": "summary", "bold": true, "color": "#3f6212"},
  {"op": "set_cell", "table": "slo", "row": 1, "col": 2, "text": "Done"},
  {"op": "set_cell", "table": 0, "row": 1, "col": 2, "text": "Done"}
]
```

- `replace_paragraph` and `set_cell` accept either a stable `"block"`/`"table"` id (from `artifact_inspect` → `structure.blocks[].id`) or a zero-based index. Ids survive reorders and unrelated edits; indexes do not.
- `insert_blocks` positions with `"after": "<id>"`, `"before": "<id>"`, or `"position": "start"|"end"` (default end). `section_break` blocks cannot be inserted mid-document.
- `remove_block` deletes everything a block spans — a list removes all its items, a table removes the whole table.
- `style_block` applies run formatting (`bold`, `italic`, `size` 6–96pt, `color` #RRGGBB, `font`) plus `keep_with_next`/`page_break_before` to every paragraph in the block, including table cells.
- `index`, `table`, `row`, `col` are zero-based. Paragraph indexes count every paragraph, headings included — confirm positions with `artifact_inspect` (or `read_file`) before replacing.
- `replace_paragraph` replaces the whole paragraph as plain text: run-level formatting inside it is lost (paragraph style and block id are preserved). Use `style_block` afterwards if formatting is needed. `set_cell` likewise replaces cell text.

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
- `tables` creates real Excel tables: `{"name", "ref", "style"?}`. `name` is unique workbook-wide (`[A-Za-z_][A-Za-z0-9_.]{0,254}`); `style` is a built-in `TableStyleLight|Medium|DarkN` (default `TableStyleMedium2`). `ref` must include the header row.
- `charts` creates real charts: `{"type", "data", "categories"?, "title"?, "anchor"?}`. `type` is `bar`, `line`, or `pie` only; `data`/`categories` are same-sheet range refs; `anchor` is a cell like `"E2"` (default). Charts reference cell values — never copy them, so they stay editable.
- `data_validations` adds input rules: `{"range", "type", "formula1", "formula2"?, "allow_blank"?, "error"?, "error_title"?, "prompt"?, "prompt_title"?, "show_error"?}`. `type` is one of `list`, `whole`, `decimal`, `date`, `time`, `textLength`. For `list`, `formula1` is an inline list like `\"a,b,c\"` or a range ref. This is authoring support, not a claim that Excel will accept every operand combination.
- `conditional_formats` adds cellIs rules: `{"range", "operator", "formula", "fill"?, "bold"?}`. `operator` is `equal`, `notEqual`, `greaterThan`, `greaterThanOrEqual`, `lessThan`, `lessThanOrEqual`, `between`, `notBetween`; `formula` is a 1–2 item list (`between`/`notBetween` need two). `fill` is a `#RRGGBB` hex. Only this bounded subset is supported — no data bars, icon sets, or formula-based rules.
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
  {"op": "add_table", "sheet": "Budget", "name": "SalesTable",
   "ref": "A1:D10", "style": "TableStyleMedium9"},
  {"op": "remove_table", "sheet": "Budget", "name": "SalesTable"},
  {"op": "add_chart", "sheet": "Budget", "type": "bar", "title": "Revenue",
   "data": "C2:C10", "categories": "A2:A10", "anchor": "F2"},
  {"op": "add_data_validation", "sheet": "Budget", "range": "B2:B10",
   "type": "list", "formula1": "\"Low,Medium,High\""},
  {"op": "remove_data_validation", "sheet": "Budget", "range": "B2:B10"},
  {"op": "add_conditional_format", "sheet": "Budget", "range": "C2:C10",
   "operator": "greaterThan", "formula": ["1000"], "fill": "#FFCCCC"},
  {"op": "remove_conditional_format", "sheet": "Budget", "range": "C2:C10"},
  {"op": "set_auto_filter", "sheet": "Budget", "ref": "A1:D20"},
  {"op": "set_freeze", "sheet": "Budget", "ref": "A2"}
]
```

`add_sheet` accepts the same keys as a sheet in the create spec. `set_auto_filter`
and `set_freeze` accept `null` to clear.

**Preservation & formulas:**

- `artifact_inspect` reports a `features` inventory (charts, tables, images, external links, macros, data validations, conditional formatting, defined names) plus `edit_safety`.
- Some workbook parts cannot survive an openpyxl round-trip (pivot tables, slicers, ActiveX, embedded objects, threaded comments, custom XML). If `inspect` reports them in `dropped_without_acknowledgement`, `artifact_revise` refuses — pass `{"op": "accept_feature_loss"}` in the same batch to produce a reduced-feature copy, or leave the file alone.
- Charts, tables, images, defined names, data validations, and conditional formatting round-trip. External links are kept but never fetched; macro (`vbaProject.bin`) parts are preserved byte-for-byte when present — never executed.
- Formulas are stored as formulas. CaberOS has no calculation engine: results show as authored formulas, and `formulas_recalculated` is always `false` unless a named engine recalculated the file. A formula cell's cached value (if any) is whatever the producing app last computed — do not treat missing values as zero.

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
