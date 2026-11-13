# W3 - Styled DOCX Creation And Targeted Editing

Status: basic DOCX authoring exists; document design and richer editing planned.
Dependencies: [W0](00-contracts-fixtures.md); exact-source preview uses [W1](01-rendering-foundation.md).
Word pagination is checked natively; approximate preview does not promise page fidelity.

## Purpose And Example Workflow

Create a four-to-six-page report with a cover, executive summary, evidence,
readable tables, figures/captions, headers/footers and page numbers. Operator
asks to shorten the summary; agent changes that section while preserving other
content. The downloaded `.docx` stays editable in Word.

Current builder handles title, headings, paragraphs, lists, tables, images and
page breaks with Letter/one-inch defaults. Existing edits append blocks, replace
paragraph text, or change a table cell. Replacing paragraph text can discard run
formatting, so richer edits need an explicit style-preservation contract.

## Implementation Slices

1. **Style schema.** Define named title/heading/body/list/caption/table styles,
   font/size/color/spacing, page dimensions, margins, sections and supported
   overrides. Preserve old defaults; validate units, heading levels and bounds.
2. **One report page.** Implement consistent hierarchy and paragraph/run styling,
   an editable table and supplied figure. Inspect/revise and render this before
   expanding to multi-section documents.
3. **Pagination features.** Add cover treatment, section breaks, headers/footers,
   page-number fields, keep-with-next/page-break controls, table header repetition,
   column widths, image fit and captions. Explain renderer/Word field refresh and
   pagination differences; stored fields do not prove calculated page numbers.
4. **Inspection and addressing.** Expose supported section/block IDs, styles,
   tables and image references. Set stable IDs and imported fallback per W0;
   paragraph index is not a stable identity after insertion/reordering.
5. **Targeted revisions.** Add approved insert/replace/remove/style operations.
   Define table-cell changes, mixed-run formatting, section boundaries and list
   numbering behavior. Resolve targets against the admitted base revision and
   preserve unrelated XML/relationships/styles.
6. **Scoped templates/uploads.** Admit a named template/style subset with
   provenance and validation. Preflight fields, tracked changes, embedded objects,
   unsupported sections and custom parts; warn/refuse destructive edits before
   publishing. Library round-trip behavior is not a universal preservation promise.
7. **Quality guidance.** Teach audience-first summaries, evidence/sources,
   consistent tables and accessible contrast. Add wide-table, missing-asset,
   heading-hierarchy and density diagnostics with heuristic labels where needed.

## Failure And Preservation Rules

Invalid styles, escaping image paths, missing IDs and stale revisions fail
without mutating source bytes. Retain originals on upload/adoption. Never claim
the report has a verified page count from paragraph/page-break counts alone.
Word pagination depends on fonts/application settings; the content preview does
not establish Word page breaks or field calculation.
Explicitly report substitutions and limitations.

## Tests And Completion

Acceptance: A01, A03, A05-A07, A09, A11-A12 and DOCX portion of A34.
Include Vietnamese/long headings, split tables, section headers, page fields,
mixed-format paragraphs, and template/import feature samples.

- [ ] Report meets four-to-six-page target in the recorded reference environment.
- [ ] Native Word pages pass hierarchy/readability/table/pagination rubric;
      approximate in-app content has an explicit limitation alert.
- [ ] Word body/heading/table edits and save/reopen preserve expected styles.
- [ ] Summary replacement leaves unrelated sections/tables/images intact.
- [ ] Supported template subset and refusal paths are documented and tested.

Targets: `backend/src/agentos/artifacts/formats/docx.py`, schema/validation and
artifact tools, `skills/office-documents/`, artifact and renderer tests.
Direct PDF authoring remains a separate existing path.
