---
name: office-documents
description: Office deliverables through CaberOS artifacts — use to create, revise, or read presentations/slides (.deck.json and PPTX), Word documents, Excel spreadsheets, or PDFs.
license: MIT
compatibility: CaberOS >= 0.2 (Artifact Studio); direct PDF creation is supported, Office-to-PDF conversion is not
allowed-tools: artifact_create artifact_inspect artifact_revise artifact_adopt artifact_history artifact_restore read_file write_file skills_read_resource
---

# Office Documents

Every Office file you produce is an **artifact**: a tracked file with immutable revisions and provenance. You describe content as a structured **spec**; CaberOS writes the file. This keeps every version recoverable and every edit attributable — so each create and edit goes through the `artifact_*` tools.

Before writing any spec or edit ops, read the exact shapes with `skills_read_resource` (skill `office-documents`, resource `references/specs.md`).

Pick the branch that matches the request.

## Create

1. **Plan the structure** — the headings (Word), sheets and columns (Excel), or slide titles (PowerPoint) — and confirm it with the user when the brief leaves it open.
2. **Honor the requested output.** Slides/presentations follow the Presentation workflow below: `.deck.json` is the source; PPTX is a derived deliverable, not a replacement for that source. Ordinary HTML pages/reports are separate: use `write_file` for self-contained HTML with inline CSS and embedded raster images. HTML opens as a scrolling static page, with scripts, navigation, forms, and external/local assets disabled.
3. Call `artifact_create` with `path` (relative to `artifacts/`, e.g. `q3-report.docx`), the `spec`, and a `change_summary`. Images come from workspace files — `attachments/…` inputs or files you saved earlier.
4. Call `artifact_inspect` on the returned id.

**Done when** inspect reports the file valid and every planned heading, sheet, or slide appears in its structure. Report the path to the user.

## Presentation

1. **Choose a story.** Use a short title, one main point per slide, concise bullets, and small tables. Give slides and blocks stable, meaningful ids. Use only the layouts, blocks, and theme tokens in `references/specs.md`; do not mix the compatibility PPTX schema into a deck spec. For a live presentation, choose restrained motion in the source: a fade transition, a short rise/fade entrance, and `reveal: "items"` on bullets that should appear one at a time. Read the Motion reference for exact fields. Do not add motion when the user asks for static slides or no effects.
2. **Create the source.** Call `artifact_create` with `format: "deck"`, a path ending in `.deck.json`, and a spec with `kind: "deck"` and `version: 1`. For example, `launch-review.deck.json` becomes `artifacts/launch-review.deck.json`. Referenced raster images must already exist in the workspace; the build pins their bytes into the source. Never generate HTML and reverse-parse it into slides.
3. **Inspect before handing off.** Call `artifact_inspect`; verify validity, slide count, ids, layouts, and image assets against the brief. Inspect is a structure check, not visual proof that text fits or that PPTX export will succeed. Keep slides sparse; split dense text or tables rather than promising automatic shrink-to-fit.
4. **Deliver what was requested.** For "create slides", give the source path: it opens as rendered slides with **Slides / Source**, **Slideshow**, and **Export PPTX** controls. Slideshow plays spec-driven transitions, entrances, and click reveals in fullscreen (with a full-window fallback); autoplay is not implemented. The normal preview shows all content. Reduced-motion preferences disable effects and show all reveals immediately. If a `.pptx` file was requested, also create a `.pptx` artifact with `format: "pptx"` and the same `kind: "deck"` source spec, then inspect it. Use the canonical source's pinned assets when available; never reconstruct a spec from rendered HTML or extracted PPTX text. Do not use a truncated `read_file` result as a complete source spec; if the complete pinned source cannot be read, offer the revision-bound **Export PPTX** UI instead of claiming an exact export.
5. **Explain the boundary.** Native PPTX contains editable text, tables, and images, but uses a simpler layout than the deck preview. It does not promise matching columns, section positioning, or fonts. Unsupported or overfull exports fail; image fallback is not yet available. Inline editing, structure controls, portable HTML export, and deck-to-PDF export are not implemented. Editing the exported PPTX externally does not update `.deck.json`.

**Done when** the canonical source is valid and its path is reported; if PPTX was explicitly requested, the actual validated `.pptx` is reported too, or the specific export blocker is stated. Do not equate successful JSON validation with a successful PPTX export or visual QA.

## Edit

1. **Find the artifact.** If the file is already tracked, use its id. If it's a user-supplied or downloaded file, call `artifact_adopt` on its workspace path first — its current bytes become revision 1.
2. Call `artifact_inspect` to get the structure and the current revision id.
3. Call `artifact_revise` with that id as `base_revision_id`, the edit `ops`, and a `change_summary`. For presentations, prefer stable slide/block IDs and targeted `set_text`, `set_bullets`, `set_table`, or `set_block` operations. Read the source first; preserve unrelated blocks and notes. `set_slide` replaces a whole slide and `set_theme` replaces the theme, so carry forward unchanged content/tokens. There is no separate proposal-review pipeline.
4. **On a conflict** (the file changed outside CaberOS since that revision), inspect and read the latest source again. Retry only if the intended change can preserve intervening edits; ask for review when both edits touch the same content. Never blindly replay an old whole-slide replacement.
5. A previously created `.pptx` companion is not automatically regenerated by a source revision. Update the requested output from the revised source or tell the user to export the latest source.

**Done when** a fresh `artifact_inspect` shows every requested change. To undo a change, `artifact_history` lists the revisions and `artifact_restore` writes an old one back as a new revision. Deck restores also require the current `base_revision_id`; stale restores fail.

## Read

For a document the user attached or names, use `read_file` — Word, Excel, and PowerPoint come back as text, and PDFs page by page (`start_page` / `end_page` for long ones). Use `artifact_inspect` when you need the outline of a tracked artifact.

PPTX reading extracts slide text, tables, and speaker notes; images become
`[image]` markers and charts currently become a series-count summary. It does
not provide a rendered slide or visual understanding of embedded images.
The operator's PPTX preview likewise shows extracted content, with a consistent
aspect-ratio frame and collapsed speaker notes, not the original Office layout.

**Done when** your answer cites where each fact came from (heading, sheet and cell, slide number, or page).

## PDF

- **Produce a PDF directly:** call `artifact_create` with `format: "pdf"`, a `.pdf` path, and a document-style spec containing `title` and `blocks`. Inspect the returned artifact before reporting success. PDFs are write-once: create a new PDF for changed content rather than calling `artifact_revise`.
- **Convert an existing Office file:** Office-to-PDF conversion is not available in CaberOS. Explain the limitation and offer the original Office file or, with the user's agreement, a new PDF based on its content. A newly created PDF does not preserve the Office file's original layout.
- **Read a PDF:** see Read above.

**Done when** the user has the validated PDF path, or an honest explanation of the unavailable conversion.

## Reference

- **Formulas:** write spreadsheet formulas as strings (`"=SUM(B2:B9)"`) so the sheet recalculates when inputs change. CaberOS stores formulas without evaluating them — inspect reports `formulas_recalculated: false` — so state that recalculated values require a spreadsheet application that evaluates formulas.
- **Unsupported formats:** legacy `.doc`/`.xls`/`.ppt` and macro-enabled `.docm`/`.xlsm`/`.pptm` have no read or edit path. Ask the user to save a `.docx`/`.xlsx`/`.pptx` copy, then continue from it.
- **Styling:** deck specs take `theme.background`, `theme.accent`, `theme.text` (`#RRGGBB`), and `theme.font` (`sans`/`serif`/`mono`). Use a high-contrast palette and deliberate layout choices, not arbitrary CSS, coordinates, or font names. Slides are 16:9; the native renderer maps font tokens to its own fonts. Exact template-file or pixel-level matching is not supported. Word pages are US Letter with 1" margins; spreadsheet cells also take bold, italic, color, and number formats.
