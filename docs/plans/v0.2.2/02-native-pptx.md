# W2 - Native Editable PPTX Craft

Planning update 2026-11-16: this is the native-renderer requirements track of
[Unified W2: Presentation Authoring, Editing And Outputs](02-presentations.md).
That plan owns the implementation order, shared source, editing and conflict
semantics. Existing requirements below remain obligations, not completion claims.

Status: basic PPTX builder exists; richer craft, templates, effects, and edits planned.
Dependencies: [W0](00-contracts-fixtures.md); rendered quality checks use [W1](01-rendering-foundation.md).

## Purpose And Example Workflow

Operator asks for an eight-slide analysis deck. Agent chooses a narrative and
varied layouts, creates native editable objects, inspects/render-reviews them,
then changes one identified slide without rebuilding unrelated slides.
Operator downloads `.pptx` and edits text, shapes, tables, and chart data in
PowerPoint. Full-slide screenshots are not an acceptable editable deck.

This renderer shares a canonical presentation source with the
[HTML track](02h-html-presentations.md), but has separate native verification.
CaberOS may show static PPTX previews even when supported effects play in PowerPoint.

## Baseline And Scope

Current handler supports 16:9, title/title-content/title-only/blank layouts,
text/bullets/notes/images/tables and bar/line/pie charts. Visual blocks share a
default placement and revise operations are limited/index-based.

Included: coherent themes, designed layouts, native style/geometry controls,
image fit/crop, targeted object edits, a named template subset, selected effects,
and diagnostics. New chart types are optional proposals until their data model
and tests are specified; scatter data cannot reuse category data blindly.

## Implementation Slices

1. **Validate and normalize.** Preserve old specs/defaults; add approved versioned
   theme/style/geometry schema. Validate finite units, palette, fonts, counts,
   paths, text limits, IDs, and all unsupported choices before publishing bytes.
2. **One designed slide.** Implement theme tokens for heading/body fonts, type
   scale, color/background, margins and spacing. Build one native metric or
   comparison slide and verify create/inspect/revise plus native editing.
3. **Layout catalog.** Add cover, section divider, two-column, image/caption,
   comparison, key metric, chart/table, and closing layouts. Define region
   geometry and text budgets; allow intentional layering without blanket overlap
   failures. Images use explicit contain/crop behavior and preserved aspect ratio.
4. **Native objects.** Style runs, paragraphs, shapes, table cells, notes and
   supported charts. Preserve editable chart data. Inspect returns object kinds,
   IDs, bounds, styles, supported features, and heuristic diagnostics.
5. **Targeted revision.** Implement approved ID-based replace/remove/reorder/style/
   chart-data operations with legacy fallback. Missing/ambiguous IDs fail.
   Preserve IDs and unaffected objects across normal edits; duplicates get new
   identities. Keep base-revision/external-edit conflict checks.
6. **Templates and effects.** Validate a small licensed template/master/layout
   subset and named native effects. Investigate safe implementation/preservation
   even if the authoring library has no public effect API. Verify in PowerPoint.
   If infeasible, record a scope decision for operator approval, not silent removal.
7. **Diagnostics and skill.** Report off-canvas bounds, likely text overflow,
   missing fonts/assets and suspicious overlap as measured facts or labeled
   heuristics. Teach narrative/whitespace/data honesty and varied layouts.
   Never generate paid assets automatically to fill a missing image.

## Preservation Policy

Do not promise all imported effects survive because XML can round-trip.
Preflight feature presence, test supported edits including reorder/delete, and
verify references/relationships/playback. Warn/refuse destructive edits before
writing, or request consent for an explicitly reduced-feature copy. Retain original
revision bytes. Static preview never counts as animation verification.

## Tests And Completion

Acceptance: A01-A02, A04, A07-A08, A11-A12, A34-A36; rendered comparison A06.
Cover blank-layout titles, long/Vietnamese text, missing fonts, local image
containment, invalid geometry, ID changes after reorder, and effect-bearing imports.

- [ ] Eight-slide deck has varied designed layouts and passes the human rubric.
- [ ] PowerPoint edits to text/shape/table/chart data survive save/reopen.
- [ ] Targeted revision changes the correct object and preserves unrelated content.
- [ ] Named templates/effects have native evidence and unsupported paths refuse safely.
- [ ] Skill/schema examples match implemented options; static-preview label is explicit.

Targets: `backend/src/agentos/artifacts/formats/pptx.py`, format validation/dispatch,
artifact capability schemas, `skills/office-documents/`, and artifact tests.
