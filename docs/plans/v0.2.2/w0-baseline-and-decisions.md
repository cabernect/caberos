# W0 Baseline Findings And Contract Recommendations

Status: local source audit and fixture evidence; recommendations approved
2026-11-13 via [decision requests](w0-decision-requests.md). Source baseline:
`0d54984` plus the uncommitted W0 worktree. This is not a renderer benchmark,
native Office verification, or acceptance sign-off. Observed locally on
2026-11-12 UTC; no application launch/download/provider call.

Subsequent operator clarification excludes LibreOffice and accepts existing
best-effort Office previews with visible limitations for uploads and generated
files. See [preview contract](preview-contract.md). The observations below remain
historical evidence; neither missing soffice nor selecting another full Office
engine is a W0 blocker.

## 1. Baseline Inventory

These findings use repository source as the primary source. Paths are relative
to this document; function names identify the inspected implementation.

| Area | What exists | Consequence for W0/W1 |
|---|---|---|
| Lifecycle | [artifact service](../../../backend/src/agentos/artifacts/service.py): create/revise/adopt/capture_external/restore, managed bytes and hashes | Reuse one revision path; do not add a separate deck store |
| Exact revision | Same module: `revision_bytes`; [preview resolver](../../../backend/src/agentos/api/agent_files.py): `_resolve_source` | Operator routes already distinguish managed revisions/live files with ownership checks |
| Current inspection | `service.inspect` reads the live workspace file; [artifact tool](../../../backend/src/agentos/capabilities/tools/artifact.py) returns current inspection | Agent inspection is not yet an exact-revision render/review interface |
| Structured revise | `revise_structured` runs format ops on current bytes, then `revise` checks base/disk hash | Keep conflict checks; future expensive work should reject stale bases before dispatch as well |
| Source validation | `create_structured` builds then stores; handler validation is separate in inspection | Parser validation is not a complete spec/preflight/render safety gate |
| Formats | [dispatch](../../../backend/src/agentos/artifacts/formats/__init__.py): PPTX/DOCX/XLSX; PDF inspect-only | No HTML structured handler; raw HTML tracking is not deck support |
| Spec persistence | [revision model](../../../backend/src/agentos/models/artifact.py): bytes/provenance, no canonical authored spec field | Need an explicit persistence decision before spec-driven targeted regeneration |
| PPTX | [handler](../../../backend/src/agentos/artifacts/formats/pptx.py): native objects; index-based revise; inspect omits native IDs | Native slide/shape IDs are candidates, not a shipped ID-addressed tool contract |
| DOCX | [handler](../../../backend/src/agentos/artifacts/formats/docx.py): positional paragraphs/tables, default styles | Need stable authored block IDs and clear imported-index fallback |
| XLSX | [handler](../../../backend/src/agentos/artifacts/formats/xlsx.py): shipped styles/formulas; openpyxl round trips | Feature-bearing uploads need preflight and tested preservation; no formula evaluation |
| Preview | [previews module](../../../backend/src/agentos/previews.py): slide/content extraction, workbook rows/formula strings | No native Office layout renderer; formula state is `formulas_recalculated: false` |
| HTML today | Same module: `.html` classified as code | Preserve safe source preview; do not execute HTML just because extension matches |
| Vision | [read_file](../../../backend/src/agentos/capabilities/tools/file.py) checks `supports_vision`, bounds/downscales image input | Reuse supported model-content handling, not arbitrary renderer paths or silent model switching |
| Runtime readiness | [dependencies](../../../backend/src/agentos/dependencies.py), [recipes](../../../backend/src/agentos/defaults/runtime-recipes.json) | Existing consent pattern, but no LibreOffice recipe/readiness implementation found |

Limits are currently different by purpose: artifact byte storage accepts up to
100 MiB, preview parsing up to 64 MiB, and sheet preview up to 500 rows/64 columns.
These are not automatically appropriate renderer ZIP/decode/CPU/memory limits.
W1 must define its own budgets and show truncation/refusal explicitly.

## 2. Recommendations To Make Contracts Implementable

The following were concrete proposals; the operator approved them as
recommended on 2026-11-13 ([decision requests](w0-decision-requests.md)).
They are approved scope, not implemented schemas. Keep the external
interface small: create/inspect/revise plus bounded render/read behavior,
with format-specific work hidden inside artifact modules.

### Versioning And Validation

- Existing unversioned Office specs remain legacy v1 with supported defaults.
  New craft specs explicitly declare a version; reject unknown versions.
- Normalize and validate v2 before any file write: known keys, unique IDs,
  finite units, allowed enums, assets, count/text/geometry budgets. Do not silently
  ignore unsupported v2 effects/styles. Do not silently tighten legacy defaults.
- Return stable diagnostic codes plus target IDs and useful messages. Distinguish
  invalid spec, unsupported feature, conflict, unavailable runtime and render failure.
- Proposed authoring budgets for review: 100 slides/deck, 100 visible blocks/slide,
  1,000 DOCX blocks, 100,000 characters/text block, and 20 MiB of packaged deck
  assets. These are starting caps, not demonstrated safe limits or renderer budgets.

### Addressing And Spec Persistence

- PPTX: expose native `slide_id` and slide-scoped `shape_id`; use a composite
  address, never shape ID alone across slides. Preserve on supported edits,
  assign fresh identity on duplication. Reject ambiguous/missing targets.
  Reorder/title-edit preservation is tested locally; delete/duplicate/import
  behavior still needs tests.
- DOCX: add explicit IDs for authored blocks/sections, stored in a documented
  persistent marker such as bounded bookmarks. Prove Office round-trip retention
  before relying on it. Legacy imports use a revision-bound positional address,
  clearly labeled; never carry a paragraph index across a changed revision.
- XLSX: sheet name plus A1 range scoped to base revision is the initial address.
  Rename/reference-changing operations need preflight; names are not immutable IDs.
- HTML: explicit unique slide/block IDs in the authored spec and exported DOM.
  A revision-specific target is never inferred from title text.
- Persist a normalized authored-spec snapshot and pinned asset inventory with
  each new authored craft revision. Keep file bytes authoritative for download/
  history. Only regenerate parts whose supported mapping is proven; do not rebuild
  arbitrary imported Office content from a lossy extraction.
- Do not fabricate a canonical spec for imported Office/HTML. An external edit
  makes old spec mappings untrusted; capture original bytes and reconcile/adopt
  explicitly rather than silently overwrite or reuse stale mappings.

### HTML Packaging And Execution

- Recommend a single self-contained HTML download for the first admitted deck
  runtime: inline approved CSS/JS, embedded local raster assets, no CDN/remote font.
  Keep bundle support a separate decision if real asset sizes make one file costly.
- Prefer a structured deck with platform-owned navigation/effect runtime over
  arbitrary agent JavaScript initially. Named effects/reveals/toggles cover the
  intended interaction; raw HTML remains source-only until explicitly admitted.
- This choice does not by itself establish safety. Enforce no-egress/navigation/
  origin/IPC policy in browser and Tauri, validate any bridge, and prove bounded
  execution. Infinite-loop probes remain disabled until containment exists.
- Candidate effect subset: fade/slide transition, one stepwise reveal and one
  data-series toggle; honor reduced motion and explicit stable capture states.
  Do not claim this set has been implemented or browser-tested.

### Templates, Effects And Workbook Feature Matrix

| Surface | Initial candidate subset | Required gate |
|---|---|---|
| PPTX templates | One synthetic owned 16:9 master with a named layout catalog | Actual PowerPoint layout/style/edit checks; do not label the baseline deck a designed template |
| PPTX effects | Fade transition plus an appear-style reveal candidate | Native playback and targeted-edit preservation, including reorder/delete; current probe tests XML presence only |
| DOCX templates | One owned report style set, sections/header/footer/page fields | Word style/field/pagination/save/reopen checks |
| XLSX tables/charts | Headered rectangular tables; bar/line charts referencing worksheet ranges | Excel editing plus unaffected-feature preservation |
| XLSX conditional formats | Numeric comparison rules initially | Rule priority/range correctness and native visual check |
| XLSX validation | Bounded whole/decimal/list rules initially | Input/error behavior in Excel, no implicit external resolution |
| Imported advanced features | Detect protection, macros, external links, pivots, drawings and unsupported parts | Feature-specific preserve/refuse policy; original bytes retained |

No candidate matrix silently removes the release's selected animations/templates.
If the candidate cannot be safely delivered, seek an explicit scope decision.

## 3. Fixture Evidence And Limits

[Corpus README](../../../backend/tests/fixtures/artifacts/README.md) documents
14 fixtures, synthetic asset provenance, execution policies and regeneration.
The manifest includes exact hashes, dependency versions and expected structure.

- Test-only ZIP/core timestamp normalization also covers embedded chart workbooks.
  Two independent generations must match each other and the local corpus bytes.
- External-edit variant now changes a visible slide title and valid editor metadata,
  rather than adding an arbitrary unnamespaced core-properties element.
- Missing-font variants request a fictional family without installing anything.
- Workbook has eight real formulas, including IF and cross-sheet references.
  Hand-derived expected values are test oracles; cached values remain absent.
- Synthetic upload includes chart/table/validation/conditional formatting/protection.
  One targeted edit/adoption test is not universal Excel feature preservation.
- Fade probe establishes input XML shape only, not Office playback/effect support.
- HTML has navigation/motion/reduced-motion/stable-state hooks. Tests parse text
  only; no live playback or security enforcement is claimed.
- Hostile/looping HTML are clearly marked isolated-opt-in-only and never executed.

Outstanding corpus gaps: actual Office-authored template/effect files, animation
timing/references, DOCX tracked changes/embedded objects, XLSX pivot/external-link/
macro samples, hostile ZIP/decode cases, native visual references and reviewed
font licenses. The baseline deck/report are structure fixtures, not approved
design references.

## 4. Renderer And Native-Verification Blockers

Local discovery only:

- `soffice` was not found on PATH or at the standard LibreOffice application path.
- PowerPoint application metadata reports 16.107.4 (16.107.26040410). Application
  presence is not proof of launch, activation, native editing or playback.
- Word and Excel were not found at their standard `/Applications` paths.
  This does not prove no installation exists elsewhere.
- No conversion, Office automation, native application launch, external research
  fetch, software/font install, or real-provider call was performed in this pass.

Next preview checks exercise the existing supported extraction paths, limitation
semantics and parser bounds; no faithful Office-layout engine needs selection.
Additional libraries are optional improvements requiring their own evaluation.
Native Microsoft editing/effects/formula gates remain separate authoring checks,
not reasons to disable uploaded previews or install an Office runtime.

## 5. Decision State

| Item | State |
|---|---|
| Shipped XLSX style/layout contract | Accepted retroactively; unchanged |
| Local fixture/source audit | Evidence added; tests recorded separately |
| v2 identity/persistence/limits | Approved 2026-11-13 (D1–D3); edge-case tests outstanding |
| HTML file/runtime/effect subset | Approved 2026-11-13 (D4); isolation feasibility and bounded-execution proof outstanding |
| Office preview approach | Accepted: existing best-effort uploaded/generated views with visible limitations; implementation pending |
| Font/HTML capture runtime policy | Approved 2026-11-13 (D6): no licensed fonts shipped; capture runtime is consent-gated managed install only |
| Templates/native effects/advanced upload coverage | Approved scope 2026-11-13 (D5); native evidence outstanding — PowerPoint 16.107 installed, Word/Excel absent |
| Quality rubric/reference designs | Rubric approved 2026-11-13 (D8); rendered-output review remains operator evidence |
| W0 overall | Decisions approved and recorded; fixture-corpus gaps, isolation proofs, and native-verification evidence remain open before W0 closes |
