# W3X - XLSX Craft, Formulas, And Uploaded-Workbook Editing

Status: first styling/layout slice shipped in `a288a31`; not all W3X is complete.
Dependencies: shipped surface accepted through W0; remaining scope/preservation
decisions in [W0](00-contracts-fixtures.md). Sheet UX integrates through [W4](04-preview-experience.md).

## Purpose And Existing Value

Agents can already create styled Excel files and apply cell/sheet/layout edits.
The prior XLSX work was real implementation, not a fixture-only exercise, and
will not be undone or implemented again.

Shipped surface includes font styling, fills, borders, number formats,
alignment/wrapping, merges, row/column sizing, freeze/filter, formula strings,
and style/layout revise operations. [Authoring contract](authoring-contract.md)
and `skills/office-documents/references/specs.md` record the surface.

Remaining work makes the result more capable and safer: native tables/charts,
defined validation/conditional-format subsets, uploaded-feature preflight,
preservation evidence, and styled previews with honest formula states.

## Example Workflows

- Create a multi-sheet budget workbook with styled headings, native summary
  chart, filterable table, currency/percentage formats and cross-sheet formulas.
- Adopt an uploaded workbook, change a named sheet/range against a base revision,
  preserve unrelated supported formulas/styles/charts, and retain the original.
- Open the download in Excel, change inputs, recalculate, save and reopen.
  CaberOS does not claim it calculated values merely because Excel can.

## Implementation Slices

1. **Regression baseline.** Lock shipped create/revise behavior with fixtures,
   real formula cell types, current style defaults and invalid-option failures.
   Distinguish existing formula counts from calculation/feature detection.
2. **Upload preflight.** Inventory workbook parts and features before round-trip:
   charts, tables, external links, macros, pivots, drawings, named ranges,
   conditional formatting, data validation and relationships. Define supported,
   opaque-preserved/tested, warning, and refuse categories with evidence.
3. **Native tables/charts.** Select bounded table styles, unique naming/range
   rules and chart types/data references. Add creation and targeted updates;
   keep charts/tables editable. Test sheet rename/removal and reference handling.
4. **Validation/conditional formatting.** Name allowed rule types and their
   bounded operands/formulas. Validate ranges, priorities and unsupported forms.
   No claim of universal Excel rule compatibility.
5. **Safe targeted editing.** Keep original revision bytes, base-revision
   conflicts and provenance. Apply supported operations without reconstructing
   unrelated sheets from extracted values. Unsupported destructive round-trips
   refuse, or require consent for an explicit reduced-feature copy.
6. **Formula semantics.** Store formulas as formulas, test SUM/IF/AVERAGE and
   cross-sheet references, and keep expected fixture values for native checks.
   Label results unevaluated, cached, or freshly calculated by a named engine.
   Missing results are not zero. Source-changing edits invalidate freshness.
7. **Sheet preview and guidance.** Expose bounded style/merge/sizing metadata,
   selected cell/range formulas and result provenance to W4. Teach useful formats,
   input/formula separation and preservation caveats in the Office skill.

## Calculation And Security Boundary

No in-app calculation engine is approved by this plan. Formula authoring does
not require one. If proposed later, specify supported functions, limits,
freshness/invalidation, local runtime and safety policy before implementation.
No external link resolution, macros, network formulas or executable behavior
may run implicitly during inspect, preview or revision.

Operator guidance (2026-11-13, authoring contract): keep data/calculation
separate from presentation — formulas only where live recalculation matters,
plain values elsewhere. Where preview/verification needs numbers for formula
cells, compute them in Python at preview time and label the provenance
("computed by <named evaluator>") — never present Excel's absent cached
value or a stale one as verified. Any such evaluator still needs the bounded
spec this section requires (supported functions, limits, freshness).

Current openpyxl-based edits do not establish that every unsupported uploaded
feature is detected or preserved; safe preflight is remaining work, not shipped.

## Verification And Done When

Acceptance: A37-A42 plus A01, A11-A12, A16, A20-A22 and A26.
Include known formula expectations, rich uploaded features, broken references,
large sparse dimensions, merged-range conflicts and stale caches.

- [ ] Shipped styling regression tests stay green.
- [ ] Named table/chart/validation/conditional-format subset works natively in Excel.
- [ ] Targeted uploaded edits preserve tested supported features or refuse safely.
- [ ] Formula authoring, Excel recalculate/save/reopen, and preview provenance verified separately.
- [ ] Sheet preview is bounded and never invents verified values.

Targets: `backend/src/agentos/artifacts/formats/xlsx.py`, upload/adopt/revise
boundary, preview metadata, artifact tests, Office skill and W4 sheet view.
