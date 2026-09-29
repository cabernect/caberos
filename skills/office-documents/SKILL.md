---
name: office-documents
description: Office deliverables through CaberOS artifacts — use when the user wants a Word document, Excel spreadsheet, PowerPoint deck, or PDF created, edited, or read.
license: MIT
compatibility: CaberOS >= 0.2 (Artifact Studio); PDF export of decks needs LibreOffice on the host
allowed-tools: artifact_create artifact_inspect artifact_revise artifact_adopt artifact_history artifact_restore artifact_export_pdf read_file skills_read_resource
---

# Office Documents

Every Office file you produce is an **artifact**: a tracked file with immutable revisions and provenance. You describe content as a structured **spec**; CaberOS writes the file. This keeps every version recoverable and every edit attributable — so each create, edit, and export goes through the `artifact_*` tools.

Before writing any spec or edit ops, read the exact shapes with `skills_read_resource` (skill `office-documents`, resource `references/specs.md`).

Pick the branch that matches the request.

## Create

1. **Plan the structure** — the headings (Word), sheets and columns (Excel), or slide titles (PowerPoint) — and confirm it with the user when the brief leaves it open.
2. Call `artifact_create` with `path` (relative to `artifacts/`, e.g. `q3-report.docx`), the `spec`, and a `change_summary`. Images come from workspace files — `attachments/…` inputs or files you saved earlier.
3. Call `artifact_inspect` on the returned id.

**Done when** inspect reports the file valid and every planned heading, sheet, or slide appears in its structure. Report the path to the user.

## Edit

1. **Find the artifact.** If the file is already tracked, use its id. If it's a user-supplied or downloaded file, call `artifact_adopt` on its workspace path first — its current bytes become revision 1.
2. Call `artifact_inspect` to get the structure and the current revision id.
3. Call `artifact_revise` with that id as `base_revision_id`, the edit `ops`, and a `change_summary`.
4. **On a conflict** (the file changed outside CaberOS since that revision), inspect again, re-base your ops on the new structure, and retry. The conflict protects someone else's edit.

**Done when** a fresh `artifact_inspect` shows every requested change. To undo a change, `artifact_history` lists the revisions and `artifact_restore` writes an old one back as a new revision.

## Read

For a document the user attached or names, use `read_file` — Word, Excel, and PowerPoint come back as text, and PDFs page by page (`start_page` / `end_page` for long ones). Use `artifact_inspect` when you need the outline of a tracked artifact.

**Done when** your answer cites where each fact came from (heading, sheet and cell, slide number, or page).

## PDF

- **Produce a PDF:** create or edit the Word (or Excel/PowerPoint) artifact first, then call `artifact_export_pdf`.
- Report the export status as returned: `exported` (with the renderer used), `renderer_unavailable` (PowerPoint export needs LibreOffice on the host — offer the `.pptx` instead), or `failed`.
- **Read a PDF:** see Read above.

**Done when** the user has either the exported PDF path or the honest reason there isn't one, plus the source artifact.

## Reference

- **Formulas:** write spreadsheet formulas as strings (`"=SUM(B2:B9)"`) so the sheet recalculates when inputs change. CaberOS stores formulas without evaluating them — inspect reports `formulas_recalculated: false` — so state that values appear when the file is opened in Excel or LibreOffice.
- **Unsupported formats:** legacy `.doc`/`.xls`/`.ppt` and macro-enabled `.docm`/`.xlsm`/`.pptm` have no read or edit path. Ask the user to save a `.docx`/`.xlsx`/`.pptx` copy, then continue from it.
- **Styling:** Word pages are US Letter with 1" margins and decks are 16:9 on the default Office theme. Specs control content and structure; spreadsheet cells also take bold, italic, color, and number formats. When the user asks for a specific font, theme, or template file, tell them the artifact uses the default styling and offer to deliver the content now.
