# v0.2.2 Authoring Contract

Status: XLSX section ratified retroactively (shipped in `a288a31`); PPTX,
DOCX, and HTML sections approved as scope on 2026-11-13 via
[decision requests](w0-decision-requests.md) D1–D4/D7 — implementation and
per-item evidence remain outstanding.

This document records the bounded, versioned structured-spec surface agents
use to author Office deliverables. It extends — never replaces — the specs
documented in `skills/office-documents/references/specs.md`, which remains
the agent-facing reference. Raw Office XML is never the authoring
interface.

Planning authority: [release plan](../v0.2.2-release-plan.md) and the
[detailed workstreams](README.md). The additions below are approved scope as
of 2026-11-13 ([decision requests](w0-decision-requests.md)) — schema
versioning, block/section identities, canonical-spec persistence,
template/effect matrices, numeric limits, and the remaining XLSX subset are
settled as direction. They are still not shipped APIs; feasibility caveats
per section (DOCX bookmark durability, HTML isolation proofs, native
verification) remain open evidence obligations recorded in the
[W0 findings](w0-baseline-and-decisions.md) §5.
Preview scope is now settled separately in the [preview contract](preview-contract.md):
existing best-effort uploaded/generated Office previews remain available with
visible limitation alerts. Native layout fidelity and a new Office engine are not
requirements for in-app preview. Alert implementation remains W1/W4 work.

## Universal authoring model (operator-ratified 2026-11-13)

Every artifact type follows the same top-level shape:

```
content spec (JSON) → format renderer → file bytes → verify step
```

The agent writes **content**, never formatting. Style comes from a
template, theme tokens, or platform CSS — not per-element instructions in
the spec. What differs per type is the renderer and where style lives:

| Type | Renderer | Style source | Preview |
|---|---|---|---|
| docx | python-docx | reference .docx named styles | extracted content (approximate) |
| xlsx | openpyxl | named styles + number formats | workbook extraction (approximate) |
| pptx editable | python-pptx | template master/layouts/theme | extracted slides (approximate) |
| pptx design-first | HTML/CSS → export | CSS design tokens | the HTML itself |
| pdf | HTML/CSS → printToPDF (future) | CSS + @page | PDF.js |
| csv / md | direct write | — | table / markdown renderer |
| html deck | deck spec → self-contained .html | theme tokens + platform CSS | isolated player (W2H) |

Consequences recorded here:

- **Verify means render-verify where a renderer exists.** Structural
  `validate()`/`inspect()` is the floor; deck capture (W2H slice 6) and
  rendered comparisons (A06) are the honest ceiling. A spec that builds
  cleanly but overflows a slide is a verify failure, not a pass.
- **pptx has two legitimate modes.** Editable deliverables fill template
  layouts with native objects; presented deliverables default to the HTML
  deck path (design-first). Deck → PPTX/PDF export is a defined W2H slice
  (lossy, documented) — see `02h-html-presentations.md`.
- **Formulas are written as formulas; preview values are computed.** The
  agent keeps live formulas where recalculation matters and writes plain
  values elsewhere. In-app preview must never present a stored/cached
  value as a verified calculation (see XLSX formula policy + W3X).
- **HTML deck is the default for presented content.** Uploaded/generated
  Office files keep best-effort previews with visible limitation alerts;
  fidelity claims require native evidence.

## XLSX — ratified (shipped)

### Create spec

`sheets[]` accepts: `name`, `rows` (ordered values/formulas from row 1),
`cells` (per-cell `value`/`formula` plus style keys), `formats` (range →
style keys), `merges` (range refs), `auto_filter` (range ref or `true`),
`row_heights` (1-based row → points), `column_widths`, `freeze` (e.g.
`"A2"`).

### Style keys

`bold`, `italic`, `color` (`RRGGBB`/`#RRGGBB` font color), `font_size`,
`fill` (solid background hex), `number_format`, `align`, `valign`,
`wrap_text`, `border` (`thin|medium|thick|dashed|dotted|double` or
`{style, color}` — all four sides).

### Revise ops

`set_cell` (value or formula), `append_rows`, `add_sheet` (full sheet
spec), `remove_sheet`, `style_range`, `merge_cells`, `set_column_width`,
`set_row_height`, `set_auto_filter` (`null` clears), `set_freeze`
(`null` clears). `inspect` reports per-sheet merges, filters, freeze
panes.

### Formula policy

- **Authoring:** formulas are written as real, editable XLSX formulas
  (`=SUM(B2:B20)`), never stored as text.
- **Calculation:** CaberOS does not evaluate formulas. Previews must not
  present unevaluated or stale cached values as verified results.
  Recalculation in Excel/Numbers depends on the
  application and workbook settings; native checks must verify it.
- **Editing uploads:** `artifact_adopt` + `artifact_revise` work on
  uploaded workbooks via openpyxl round-trip. Supported cell/sheet/style
  ops apply; preservation of advanced features (charts, pivot tables,
  conditional formatting, macros) is NOT guaranteed. Preflight detection and
  warning/refusal are required remaining W3X work, not proven shipped behavior.

### Preview honesty

The current preview renders the workbook as a table of values. It does
not render fills, borders, charts, or formula results — those exist in
the file, not the preview. W4 must extend the sheet preview or label the
limitation explicitly.

## PPTX — approved scope (D1–D3, D5), pending implementation

Grounded in `python-pptx` capabilities; raw XML is never authored.

### Create spec v2 (extends shipped spec, backwards compatible)

Existing keys stay: `slides[]` with `layout` (`title`, `title_content`,
`title_only`, `blank`), `title`, `subtitle`, `blocks[]`, `notes` blocks.

Proposed additions:

- `theme` (deck-level, optional): `{background, accent, text}` — `RRGGBB`
  hex. Applied as slide background fill + title/body run colors. Bounded
  palette keys only; no gradients/images in v1.
- Block `style` (optional, text-bearing blocks): `{bold, italic, color,
  font_size, align}` — `align` ∈ `left|center|right`. Bullets items may
  be strings or `{text, style}` objects.
- New chart types: `doughnut`, `area`, `scatter` (python-pptx
  `XL_CHART_TYPE` subset). Existing `bar|line|pie` unchanged.
- New block `shape`: `{type: rect|rounded_rect|ellipse|line|arrow,
  text?, style?}` — decorative/annotation shapes via `MSO_SHAPE`.
- Optional explicit geometry per block: `x`, `y`, `width_inches`,
  `height_inches` (inches, `0 < v ≤ 13.33/7.5`, must fit canvas).
  Omitted = current auto-layout position below title.

### Effects & transitions

- **Selected native effects remain included** in the release scope. The lack
  of a public python-pptx transition/animation API is an implementation risk,
  not a decision to remove authoring. W0/W2 must choose a named tested subset
  and safe implementation/template path, or seek an explicit scope change.
- **Preserve on revise is a requirement, not a library guarantee.** Test effect
  references/relationships and actual playback across supported edits. Warn/refuse
  destructive edits before writing, or request consent for a reduced-feature copy.
- **Preview honesty:** static preview must label "animations and
  transitions aren't shown" whenever the file contains them (detectable
  via `p:transition` / `p:timing` in slide XML).

### Stable addressing

- Slides expose `slide_id` (python-pptx `slide.slide_id`, stable within a
  file across saves). `inspect`/`to_elements` report it.
- Revise ops accept `slide_id` (preferred) **or** zero-based index
  (legacy). Index ops remain valid; `slide_id` survives `move_slide` and
  `add_slide` reordering.
- **Imported/legacy fallback:** files authored outside our spec get
  `slide_id`s from python-pptx but no spec-side manifest; index addressing
  is the documented fallback. We do NOT persist canonical specs for
  foreign files as if lossless — the file itself is truth. A versioned
  canonical spec IS persisted for CaberOS-authored files (D1).

Slide IDs are settled; block-level `shape_id` composites and duplicate/
delete identity behavior are approved direction (D2) pending
implementation and Office round-trip evidence.

### Proposed new revise ops

`set_notes` (slide_id/index, text|null), `delete_slide`,
`duplicate_slide` (with `at` position), `set_background` (color hex),
`set_slide_layout` (change layout within the bounded set).

## DOCX — approved scope (D1–D3, D5), pending implementation

### Create spec v2 (extends shipped spec, backwards compatible)

Existing blocks stay: `heading`, `paragraph`, `list`, `table`, `image`,
`page_break`.

Proposed additions:

- Doc-level `page`: `{size: letter|a4, orientation: portrait|landscape,
  margins_inches}` — defaults unchanged (US Letter, 1").
- Block `style` (paragraph/heading/list): `{bold, italic, color,
  font_size, align}` — applied to runs/paragraph format.
- `header` / `footer`: plain-text strings rendered into the section.
- `table` block gains: `column_widths` (fractions or inches), `style`
  from a bounded named set (`grid` default, `light`, `plain`).

### Revise ops

Existing: `append_blocks`, `replace_paragraph`, `set_cell`. Proposed:
`insert_blocks` (at paragraph index), `delete_paragraph`,
`set_paragraph_style` (style keys above), `set_cell` extended with
optional style keys. Tables addressed by document order index — same
fallback rule as slides for foreign files.

### Preservation policy

python-docx can retain some foreign XML, but that is not a guarantee for all
features/operations. Preflight tracked changes, fields, embedded objects and
custom parts; verify supported round trips and warn/refuse unsupported destructive
edits. Feature reporting and preservation guards remain implementation work.
The detailed W3 scope also includes sections, captions, page fields, table header
repetition, pagination controls and a named template subset.

## HTML deck — approved scope (D4), pending implementation + isolation proof

### Authoring path

- `deck` artifact format: spec `{title, theme?, slides[]}` where each
  slide is `{html}` (sanitized fragment) or `{blocks}` reusing the PPTX
  block vocabulary for simple decks. Generated output is ONE
  self-contained `.html` file — inline CSS/JS, no external requests.
- Ordinary raw HTML retains a source view. Executable playback requires explicit
  admission to the isolated deck runtime; `.html` alone is not a trust signal.

### Playback isolation contract

- Preview/playback renders inside `<iframe sandbox="allow-scripts">`
  with NO `allow-same-origin` — deck JS runs but cannot touch the
  dashboard origin, cookies, or storage.
- CSP at the serving/playback boundary must restrict resources, connections,
  forms, framing and other relevant channels. A meta tag in generated content
  alone is insufficient, especially for imported content.
- No implicit network egress: combine validation with enforced runtime policy
  and adversarial tests. Define safe navigation/message handling as well.
- A sandboxed iframe alone is not a CPU/process isolation guarantee. W2H must
  prove that looping scripts cannot freeze the browser/Tauri application and
  supply bounded execution/recovery.
- Keyboard contract: ←/→ navigate slides; F for fullscreen. Decks that
  don't implement it still render statically slide-by-slide.

### Revisioned assets

- Single-file embedded assets are a proposal, not a packaging decision already
  made. Compare against a pinned local bundle in W0; choose tested size/count/
  decode limits before implementing. Mutable workspace assets must never change
  historical playback. Stable capture states and reduced motion are required.

## Remaining XLSX Scope

The shipped style surface does not complete W3X. Native tables/charts, a named
validation/conditional-format subset, upload preservation guards and formula
result provenance remain included in [W3X](03x-xlsx-craft.md).
