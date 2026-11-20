# v0.2.2 Preview Approach And Historical Renderer Shortlist

Status: existing best-effort Office previews are the accepted baseline, with
non-blocking format-specific alerts. No new Office engine is required. This
document retains the earlier shortlist for context, not as an active selection gate.
The expanded 14-file corpus and current source/runtime discovery are recorded
in [W0 findings](w0-baseline-and-decisions.md) and [local evidence](w0-local-evidence.md).

Operator clarification: LibreOffice is out of scope. The earlier optional
LibreOffice recommendation is withdrawn; do not install, integrate, or wait on
it as a W0 gate. Subsequent clarification accepts limited Office previews for
uploaded and generated files; do not replace that gate with mandatory selection of
another faithful Office engine. See [preview contract](preview-contract.md).

See [W0](00-contracts-fixtures.md) for the comparison procedure and
[W1](01-rendering-foundation.md) for implementation gates. Preview-only scope:
conversion does not authorize a public PDF export or Office editing engine.

## Historical Candidates - Not Required Dependencies

### A. LibreOffice - Excluded

Previously considered, now excluded by operator direction. Its absence is not a
blocker and there is no optional-install or conversion path to approve here.

### B. Client-side JS renderers (browser, zero server deps)

| Library | Formats | Evaluation focus | Fidelity evidence |
|---|---|---|---|
| `docx-preview` | DOCX→HTML | HTML layout limits, pagination, feature coverage | Not benchmarked here |
| `pptxjs` | PPTX→HTML slides | Legacy dependencies and maintenance/security review | Not benchmarked here |
| SheetJS (`xlsx`) | XLSX→HTML/table | Exact edition/version, style support and bounds | Not benchmarked here |
| `jsw-teams/document-viewer` | Multiple Office formats/PDF | Provenance, maturity, dependency/security review | Not benchmarked here |

- **Isolation:** local JS avoids a conversion server but still needs safe parsing,
  content sanitization/isolation and work bounds. Bundled assets alone do not
  establish no network or protect the app origin.
- **Cost:** npm deps only; lazy-load per format.
- **Honesty fit:** good — we can label "approximate preview" per format.
- **License:** verify exact package/edition/version and transitive dependencies.

### C. Document servers (OnlyOffice Docs, Collabora Online)

- Viewer/conversion and collaborative editing suites introduce a larger service/
  integration/distribution surface. Evaluate official license/deployment guidance
  if considered. Proposed exclusion for v0.2.2, not a completed resource benchmark.

### D. Python rasterizers (python-pptx/docx/openpyxl → image)

- These are the authoring libs we already use; they expose structure, not
  rendered layout. No faithful page/slides output without re-implementing
  layout ourselves. Not a native layout-rendering solution. Existing extraction/
  reflow can remain as a labeled content view, never a native-fidelity claim.

## Recommendation

Reuse and test existing PPTX slide-grouped extraction, DOCX content views and
XLSX worksheet grids for uploaded and generated files. Add persistent, non-blocking
limitation alerts through W1/W4. Improve styles/coverage within the supported subset;
new libraries are optional future improvements, not prerequisites for W0.

HTML decks use isolated browser playback and stable captures independently of
Office rendering. Native editable Office authoring remains a separate requirement.
Bind preview/capture results to exact revisions, renderer/version, fonts and options.

Approximate extraction is an accepted preview mode, not native layout verification.
Missing fidelity is explained by the alert; it does not disable uploaded previews
or require another Office engine. HTML playback does not promise arbitrary PPTX
conversion, and a design companion is labeled separately if added.

## Decision State And Remaining Work

- Accepted: LibreOffice excluded; no replacement Office engine gate.
- Accepted: best-effort uploaded/generated Office previews with limitation alerts.
- [ ] Implement/test format-specific limitation metadata and visible alerts in W1/W4.
- [ ] Measure supported content/omissions, bounds and parser failures using fixtures.
- [ ] Set authored font/license policy and HTML capture/runtime safety independently.
- [ ] Verify native Office editing/effects/formulas separately from preview fidelity.

## Primary References For Evaluation

These are documentation pointers, not evidence that tests ran:

- [docxjs / docx-preview](https://github.com/volodymyrbaydalka/docxjs)
- [PPTXjs documentation](https://pptx.js.org/pages/docs.html)
- [ONLYOFFICE DocumentServer](https://github.com/ONLYOFFICE/DocumentServer)
