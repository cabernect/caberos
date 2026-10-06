# v0.2.0 Artifact Studio

## Outcome

Agents create valid professional DOCX, PPTX, and XLSX deliverables, export PDF, and preserve every meaningful revision without overwriting external edits.

## Included

- Structured generation and revision of DOCX/PPTX/XLSX
- PDF export/read-only PDF artifacts
- Artifact identity and immutable revisions
- Validation and preview-render status
- Templates, charts, images, tables, formulas, and themes
- Conflict detection and restore

## Deferred

- Arbitrary PDF editing
- Office macros
- Perfect Office-aware semantic diffs
- Unsupported embedded-object round trips

## Domain model

```text
Artifact
  id
  workspace_id
  current_path
  format
  current_revision_id
  tracking_status
  created_by
  created_at

ArtifactRevision
  id
  artifact_id
  revision_number
  content_hash
  storage_path
  preview_status
  source_run_id?
  source_message_id?
  source_plan_step_id?
  base_revision_id?
  change_summary
  created_at
```

The workspace contains the current file. Historical bytes/previews live in managed application data. Restore creates a new revision.

## Module interface

Expose structured create, inspect, revise, render, validate, and publish behavior. The model never writes Office XML directly. Skills provide design/writing guidance and templates; the Artifact module guarantees format validity, workspace containment, revisioning, and rendering.

## Format behavior

### DOCX

Headings, paragraphs, lists, tables, images, headers/footers, links, references, and page settings.

### PPTX

Layouts, themes, text, images, tables, charts, notes, and slide ordering.

### XLSX

Sheets, cells, formulas, formatting, tables, charts, filters, and frozen panes. Formula authorship and formula recalculation are reported separately.

### PDF

Export supported artifacts and retain imported PDFs read-only. Rendering/export failure is separate from source-artifact validity.

## Conflict and history

Every edit names a base revision. If the current file hash differs, do not overwrite. Offer preserve-both, capture external version, or discard draft. Messages remain linked to the exact produced revision even after newer revisions exist.

## Safety

- Macro-enabled and password-protected files are read-only/unsupported with clear status.
- Warn before editing files with unsupported features.
- Prefer revised copies where round-trip safety is uncertain.
- Bound file sizes, renderer resources, page/slide/sheet counts, and preview work.
- Validate paths and never execute embedded content.

## Tests first

- Each format reopens successfully in an independent parser/viewer.
- Successful generation creates one revision; failure creates none.
- External modification yields conflict instead of overwrite.
- Restoring v2 after v5 creates v6.
- Message/Plan Step links preserve exact revisions.
- Formula recalculation status is honest.
- Unsupported/macro/password cases degrade safely.
- Rename/move preserves Artifact identity.

## Done when

The integrated acceptance story can create, validate, revise, restore, and export all four target formats on clean desktop and Docker builds.

## Implementation status (feat/v0.2-artifacts)

- Core + all format handlers + mediated `artifact_*` capabilities: implemented and green (22 tests in `backend/tests/test_artifacts.py`, plus `scripts/smoke_artifacts.py` scripted/live pipeline verification).
- PDF export: LibreOffice headless when installed → pure-Python reportlab fallback for docx/xlsx → honest `renderer_unavailable` otherwise. pptx excluded from text-flow export (layout-bound). TODO(W4): Chromium render path via the managed browser — positioned HTML reproduces slide layout without LibreOffice.
- Direct `format: "pdf"` creation is supported (spec → reportlab, write-once).
- Open gaps: `preview_status` populated by W3; `artifact_base_revision_ids` run-start capture pending; templates/themes guidance deferred to W6 skills; LibreOffice availability in Docker image deferred to W10 packaging.
