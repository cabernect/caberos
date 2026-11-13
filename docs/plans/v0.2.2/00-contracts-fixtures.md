# W0 - Contracts, Fixtures, And Design Gates

Status: in progress — operator decisions recorded 2026-11-13
([decision requests](w0-decision-requests.md)); fixture-corpus gaps,
isolation proofs, and native-verification evidence remain open.
Parent: [workstreams](README.md). Scope authority: [release plan](../v0.2.2-release-plan.md).

## Purpose And Visible Outcome

W0 decides what we will build and how we will know it works. It does not ship
the HTML viewer or redesign Office creation. Its deliverables are concrete
examples, tested contracts, comparison evidence, and recorded decisions that
prevent later work from relying on unsupported behavior.

The shipped XLSX styling slice remains in place. Ratifying that surface does
not approve the unimplemented PPTX/DOCX/HTML proposals or finish W0.

## Current Evidence And Gaps

Initial files live in `backend/tests/fixtures/artifacts/`; fixture smoke tests
are in `backend/tests/test_artifacts.py`. They cover an eight-slide deck, report,
formula workbook, HTML deck, long titles, Vietnamese text, and an external-edit
variant. Inspection/hash checks do not establish visual quality or preservation.

The continued W0 pass expands the corpus to 14 fixtures: missing-font variants,
a synthetic fade probe, feature-bearing uploaded workbook, hostile/looping HTML,
formula test oracles, and pinned synthetic asset metadata. Regeneration tests
check byte stability; scripts are not executed.
See [baseline and recommendations](w0-baseline-and-decisions.md) and
[local test evidence](w0-local-evidence.md).

Still needed: actual Office-authored template/animation samples, broader
unsupported imported features, hostile ZIP/decode samples, native Office
comparisons for native authoring, preview coverage/bounds measurements, font license review,
and approved design references. The
report's actual page count must be measured, not inferred from page breaks.
Fixture-only normalization covers package/core timestamps and embedded Office
packages; byte stability is checked in the recorded dependency environment, not
promised across arbitrary versions/platforms.

## Implementation Slices

1. **Baseline inventory.** Map create/inspect/revise/adopt/restore and preview
   paths to current handlers. List shipped options versus gaps. Check workspace
   provenance, exact revision selection, dependency readiness, and vision input.
2. **Fixture corpus.** Add a manifest with purpose, expected structure, assets,
   license/source, and expected warnings. Include editable native charts/tables,
   DOCX pagination, SUM/IF/AVERAGE and cross-sheet XLSX formulas with known
   expected values, and HTML motion/reduced-motion/stable-state examples.
3. **Authoring schema.** Specify versioning/default behavior, themes/fonts,
   layout regions, styles, units, crop behavior, and resource/text/count limits.
   Define invalid/unknown-key behavior. Keep existing supported specs working.
4. **Identity and revision contract.** Decide persistent slide/block/section
   identifiers, ambiguous/missing-target errors, import fallback, and identity
   after duplicate/delete/reorder. Decide whether authored canonical specs are
   revision-pinned; do not reconstruct imported specs as if lossless.
5. **Feature matrices.** Name supported templates, PPTX effects, DOCX styles,
   XLSX charts/tables/conditional formats/validation and upload restrictions.
   Library limitations are evidence to investigate, not permission to drop scope.
6. **Preview coverage and limits.** Exercise existing preview paths against
   uploaded/generated Office fixtures. Record supported/omitted content, truthful
   alerts, truncation/bounds and errors. Full Office layout reproduction is not a
   gate; additional libraries need evidence, not automatic adoption. Keep native
   Office checks separate for creation/editability/effects.
7. **Decisions and rubric.** Record recommendation, alternatives, trade-offs,
   approval state, and evidence. Define readable typography, contrast, whitespace,
   chart labels, data accuracy, pagination, and intentional layout criteria.

## Required Decisions

LibreOffice is excluded. The [preview contract](preview-contract.md) records
accepted best-effort Office scope and required non-blocking limitation alerts.
Do not block W0 on finding a replacement Office engine. HTML live playback is separate.

| Decision | Record before dependent implementation |
|---|---|
| Office previews | Existing best-effort modes, uploaded/generated coverage, format-specific alerts and bounds |
| Runtime/fonts | Consent, distribution/update policy, licenses, substitutions, absent-runtime behavior |
| Authoring identity | Schema version, stable IDs, imported fallback, canonical-spec persistence |
| HTML | File versus bundle, asset pinning, script policy, isolation/capture model, bounded execution |
| Templates/effects | Named supported subset, preservation checks, native verification method |
| XLSX | Remaining feature subset, upload preflight, formula-result provenance; calculation separately |
| Quality | Reference examples and human review rubric approved for each output type |

## Safety And Verification

Do not install renderers/fonts, fetch licensed assets, or use paid providers
without operator consent. Headless mode is not a network or filesystem sandbox.
Include timeout, malformed ZIP/XML, external links, missing assets, unsupported
features, and font substitution in the comparison procedure.

Tests must distinguish format validity, structure, rendering, human visual
review, native editing, and playback. Record blocked native/platform checks.
Use [acceptance matrix](acceptance-matrix.md) A01-A07, A20-A22, A31-A42 as
contract inputs, not as already passing evidence.

## Done When

- [ ] Fixture coverage, expected outcomes, licenses, and reproducibility documented.
- [ ] Authoring/identity/assets and supported-feature matrices are unambiguous.
- [ ] Preview coverage/limits recorded; alert contract settled without requiring an Office engine.
- [x] Operator decisions recorded; unresolved decisions remain visibly open.
- [ ] Every downstream lane has explicit inputs, testable limits, and a quality rubric.

Outputs: [authoring contract](authoring-contract.md), [renderer comparison](renderer-comparison.md),
[decision requests](w0-decision-requests.md), fixture corpus, and dated
evidence records created when tests actually run.
