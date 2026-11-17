# v0.2.2 Workstreams - Artifact Craft & Preview

Status: planning in progress. The shipped XLSX styling surface is accepted
retroactively; the rest of W0 is not complete. Initial fixtures and a renderer
shortlist exist, but fixture coverage, native Office checks, renderer execution,
isolation tests, and operator decisions remain outstanding. No percentage of
completion is claimed.
Current W0 findings: [baseline and recommendations](w0-baseline-and-decisions.md).
Local fixture/test evidence: [W0 evidence](w0-local-evidence.md).
LibreOffice is excluded. Uploaded and generated Office files keep best-effort
previews with visible, non-blocking limitations; no full Office layout engine is
required. Other supported formats remain previewable. See [preview contract](preview-contract.md).
Release boundary: [release plan](../v0.2.2-release-plan.md).
Verification: [acceptance matrix](acceptance-matrix.md).

## How To Read The Workstreams

`W` means workstream, not week. The labels group related work; they do not
promise a duration or require every stream to run strictly in numeric order.
The sections below summarize scope; the linked plans give implementation
slices, failure behavior, test scenarios, and completion checklists.

| Workstream | In plain language | Detailed plan | Current state |
|---|---|---|---|
| W0 | Decide supported features, safety rules, and what good output looks like | [Contracts and fixtures](00-contracts-fixtures.md) | In progress; initial drafts are not approval |
| W1 | Preview exact revisions with honest modes/limitations | [Preview foundation](01-rendering-foundation.md) | Existing Office extraction is baseline; metadata/capture work planned |
| W2 (includes former W2H) | Author and edit one presentation spec; render HTML, native PPTX and planned PDF | [Unified presentation plan](02-presentations.md) | Direction accepted; implementation sequence and editing scope proposed for review; provisional code is not completion evidence |
| W3 | Make styled, editable Word reports and targeted document edits | [DOCX craft](03-docx-craft.md) | Basic handler exists; richer styles/templates planned |
| W3X | Make styled Excel files and safely edit uploaded workbooks | [XLSX craft and editing](03x-xlsx-craft.md) | First styling/layout slice shipped; remaining scope planned |
| W4 | Let the operator comfortably view and request changes to deliverables | [Shared preview UX](04-preview-experience.md) | Existing panel is baseline; richer UX planned |
| W5 | Let the agent see exact output and fix visual problems | [Visual inspection loop](05-visual-inspection.md) | Planned |
| W6 | Prove the whole workflow, document limitations, and release | [Acceptance and release](06-acceptance-release.md) | Planned; no release approval implied |

### One Presentation Source, Separate Renderer Evidence

The [unified W2 plan](02-presentations.md) supersedes the independent W2/W2H
authoring split. The renderer obligations below remain supporting tracks:

- W2's PPTX track produces native editable Office objects with a static, best-effort
  in-app preview. W1 identifies preview mode/limits; no Office layout engine is required.
- W2's HTML track (formerly W2H) produces live browser playback, supported motion,
  offline assets, and an isolated runtime. It does not need an Office engine.
- W3 produces `.docx`; W3X produces `.xlsx`. Neither is an HTML presentation.
- W4 brings these views into the shared panel; W5 lets agents inspect their
  revision-bound output. HTML screenshots do not prove motion works, and an
  HTML deck does not automatically become an editable PPTX.

### Dependency Order

```text
W0 shared identity / asset / safety contracts
  +-- Preview modes / limits ---> W1 ---------------------+
  +-- Presentation source ----> W2 (HTML/PPTX/PDF tracks) -+--> W4 --> W5
  +-- DOCX contract -----------> W3 ----------------------+          |
  +-- XLSX remaining scope ----> W3X ---------------------+          v
                                                                  W6
```

Relevant W0 decisions unblock each lane; limited Office preview fidelity does not
block HTML contract/authoring work. HTML capture and shared panel integration
still need W1's source/result conventions. This is a dependency map, not a
request to skip shared safety gates or approval.

The first vertical milestones are one editable designed PPTX slide, one live
HTML slide, one styled DOCX page, and one styled formula-bearing sheet. Expand
each catalog only after its create/inspect/revise/view path works end to end.

### Planning And Evidence Rules

- The release plan is the scope authority. A proposal cannot silently remove
  included templates, selected PPTX effects, or XLSX tables/charts.
- [Authoring contract](authoring-contract.md) records shipped versus proposed
  surface; [preview contract](preview-contract.md) records accepted preview scope.
  The [historical renderer shortlist](renderer-comparison.md) is not a required
  engine-selection gate or completed benchmark.
- API/tool names and numeric limits in the detailed plans are design tasks,
  not existing interfaces. Set and test concrete limits before implementation
  is called complete.
- Completion requires the linked acceptance IDs and environment-specific
  evidence. A fixture test, parser reopen, or draft document alone is not enough.

File targets below are existing integration points, not instructions to build
a second artifact framework. New API/tool/schema names must be settled against
repository conventions during W0. Each numbered unit is a candidate small,
coherent change; commit/push only with operator approval.

## W0 - Contracts, Quality Fixtures, And Rendering Decision

Outcome: resolve the design gates before choosing dependencies or writing UI
against an unproven renderer.

1. Inventory artifact specs/ops, validation, workspace provenance, exact-revision
   reads, preview APIs, optional dependencies, and model image-input support.
   Keep v0.2.1 fixture and compatibility tests as the regression baseline.
2. Create deterministic PPTX/DOCX fixtures: an eight-slide analysis deck and a
   four-to-six-page report with supplied figures and licensed local assets.
   Include title/section/data/comparison/image slides and cover/body/table pages.
   Keep long titles, Vietnamese text, missing fonts, and external edits as
   deliberate adversarial variants.
3. Define a bounded, versioned extension to the structured spec: themes, text
   styles, layout regions, supported shapes, image crop rules, and document
   styles. Validate units, colors, dimensions, asset paths, counts, and text.
   Existing specs retain existing defaults. Invalid options fail explicitly.
4. Decide stable slide/block addressing and inspect output before expanding
   revise operations. Identifiers must survive reordering and normal revisions;
   legacy/imported files need a documented fallback, not guessed identity.
   Decide whether canonical specs need persistence for CaberOS-authored files;
   if so, version and pin them with the bytes without claiming arbitrary imports
   can be reconstructed losslessly.
5. Test existing best-effort Office preview coverage, omissions, bounds and errors
   using the fixtures. Document non-blocking format-specific limitation alerts.
   Native Office checks verify authored files, not the need for an in-app engine.
6. Record preview mode/limitation semantics, authored font policy, HTML runtime
   safety and reference designs. No LibreOffice or replacement full-engine gate.
   Add an ADR only for a chosen consequential trade-off.

Also settle a named template/effect support matrix, HTML packaging/playback
isolation and revisioned asset contract, and XLSX style/chart/table/edit scope.
Add an HTML deck and styled formula-bearing workbook to the fixture set,
including uploaded files with unsupported features. Decide formula calculation
separately from authoring; record whether results are unevaluated, cached, or
freshly calculated, and which engine/security policy would justify the latter.

Targets: `backend/src/agentos/artifacts/`, `backend/src/agentos/previews.py`,
`backend/src/agentos/capabilities/tools/artifact.py`, existing dependency
management, and `skills/office-documents/references/specs.md`.

Exit: approved authoring/preview contracts and review rubric.
No renderer selected or downloaded merely because it appears in this plan.

## W1 - Revision-Bound Preview Foundation

Outcome: panel and agent inspect supported content for the same exact revision,
with clear mode/limitations, rather than assume perfect Office layout.

1. Extend existing authenticated previews and mediated agent inspection with
   exact-source identity, preview mode, limits and bounded content/image references.
2. Reuse PPTX slide-grouped extraction, DOCX document content and XLSX rows for
   uploaded and generated files. No LibreOffice/full Office renderer gate.
3. Distinguish ready/partial/failed/unsupported and any asynchronous capture
   lifecycle. A limitation notice is not a parse error or proof of corruption.
4. Bound parsing/decode/capture work; deny macro/script/remote-resource execution.
   Use isolated workers when needed, not a new mandatory Office-conversion daemon.
5. Cache/deduplicate by source hash, implementation/version and relevant options;
   prevent stale or unauthorized output even on cache hits.
6. Supply W4's persistent, non-blocking format-specific alerts. Preserve existing
   preview types; optional HTML capture failure must not disable Office extraction.

HTML live playback/capture remains W2H's isolated path. A future authored-design
preview must be pinned/labeled as a design representation, not Office-byte layout.
XLSX keeps a bounded sheet view/formula metadata; paginated printing is not required.

Targets: `backend/src/agentos/previews.py`, artifact service/model as required,
existing workspace/skill preview routes, dependency management and packaging.

Exit: exact-source best-effort previews, truthful limits, auth/race/bounds checks
and supported captures. See [detailed W1](01-rendering-foundation.md).

## W2 - Native Editable Presentation Craft

Supporting native-renderer requirements, not a separate authoring architecture.
The primary sequence, spec editing and conflict policy are in
[Unified W2](02-presentations.md). Preserve the requirements below as its native
track; they are not satisfied merely by adding a shared JSON type.

Outcome: designed PPTX slides made of editable objects, not slide screenshots.

1. Add a small theme vocabulary: palette, heading/body fonts, type scale,
   background, spacing, and slide size. Use explicit licensed font defaults
   and report substitutions. Resolve all image assets within the pinned workspace.
2. Implement a focused layout catalog: cover, section divider, two-column,
   image/caption, comparison, key metric, chart/table, and closing slide.
   Use reusable placement rules plus supported explicit positioning, not one
   fixed bounding box for every visual block.
3. Support native text runs, shapes, tables, and existing chart types with
   style controls. Keep chart data editable. Provide predictable image fit/crop
   and aspect ratio behavior; do not imply raster image contents are editable.
4. Add diagnostics for off-slide elements, invalid geometry, likely text
   overflow, and suspicious overlaps with intentional layering supported.
   Heuristic checks must be labeled; do not promise perfect font measurement.
5. Extend inspect/revise for identified slide/element changes, replacement,
   removal, reordering, style updates, and chart-data updates. Preserve unaffected
   objects and style; normal external-edit conflicts still block writes.
6. Update the Office skill with narrative, layout selection, whitespace,
   readable chart, and image-selection guidance. Explicitly discourage repeated
   bullet layouts and invented data. Never auto-generate paid images as a fallback.
7. Support a validated subset of imported PPTX templates/masters/layouts and
   selected native transitions/animations. Verify effects in actual PowerPoint,
   not the static preview. Preserve effects during supported revisions; if the
   edit path cannot preserve them, warn/refuse before writing or obtain explicit
   consent for a separately identified reduced-feature copy.

Targets: `artifacts/formats/pptx.py`, format dispatch/validation, artifact
capability schemas, and `skills/office-documents/`.

Exit: the reference deck passes the visual rubric and actual PowerPoint edits
to text, shape, table, and native chart data, followed by save/reopen.
Parser success alone cannot satisfy the editability gate.

## W2H - HTML Presentation Authoring And Playback

Historical label, now the HTML renderer track within
[Unified W2](02-presentations.md). Playback/isolation obligations remain;
this is no longer an independently mutable presentation source.

Outcome: a first-class portable HTML deck, not a screenshot-based PPTX substitute.

1. Add create/inspect/revise support through the artifact boundary, with slide
   identities, theme/layout controls, supported transitions/animations, notes,
   and bounded interactions such as chart toggles or stepwise reveals.
2. Choose self-contained HTML or a local asset bundle in W0. Pin all assets
   with each revision so history/downloads never read mutable workspace assets.
   Local fonts/images/scripts need licensing, byte/count limits, and containment.
   No CDN, remote font, or hidden network dependency is allowed by default.
3. Run deck code in an isolated untrusted surface, never the privileged app
   origin. Deny CaberOS APIs/credentials, Tauri IPC, parent DOM, host filesystem,
   uncontrolled navigation/popups/downloads, and implicit network access.
   Any message bridge is narrow, validated, and grants no platform authority.
4. Support slide navigation, live motion, reduced-motion mode, stable capture
   states, and cleanup on close. Bound script/render work; use process-level
   isolation where needed so a looping deck cannot freeze the main application.
5. Capture revision-bound thumbnails/review images from stable slide states.
   Test live playback separately. Preserve revisions and targeted edits through
   the same provenance/conflict contracts as other artifacts.
6. Download a portable file/bundle that opens in a supported browser offline.
   Share content/themes with PPTX only where faithful; no lossless HTML-to-PPTX
   conversion or arbitrary executable HTML import is promised.

Targets: artifact format dispatch/service/capabilities, shared preview APIs,
isolated frontend playback surface, and presentation skill guidance.

Exit: reference deck plays offline and inside isolated CaberOS views, revision
assets stay stable, and hostile script/network/IPC fixtures cannot gain authority.

## W3 - Styled Document Craft

Outcome: an editable report with intentional hierarchy and page layout.

1. Add reusable document styles for titles/headings/body/lists/captions/tables,
   font/color/spacing controls, page dimensions, margins, and section breaks.
2. Support a cover treatment, headers/footers, page-number fields, table header
   styling/repetition, image sizing, and keep-with-next/page-break controls.
   Document field recalculation and pagination limitations explicitly.
3. Extend inspect with supported section/block identifiers and style details.
   Add bounded section/block replacement/insertion/removal and style operations;
   preserve unaffected sections and Office objects during targeted revisions.
4. Add checks for readable hierarchy, excessively wide tables, missing assets,
   and unsupported features. Validate rendered page breaks and density rather
   than asserting that structural inspection proves good pagination.
5. Extend skill guidance for audience, executive summary, evidence, sources,
   consistent tables, accessible contrast, and avoiding decorative filler.
6. Support a documented subset of uploaded DOCX templates/styles and targeted
   edits to uploaded documents. Preflight unsupported features, preserve
   unaffected supported content, and warn/refuse destructive round trips.

Targets: `artifacts/formats/docx.py`, artifact specs/ops, and Office skill.

Exit: the reference report passes the rubric, Word editing/save/reopen, and
rendered-page review. Existing direct PDF creation remains separate.

## W3X - Styled XLSX Creation And Uploaded-Workbook Editing

Outcome: attractive, natively editable workbooks with real formulas and safe
targeted edits, not reconstructed sheets that silently discard existing content.

1. Extend structured specs/ops for fonts, fills, borders, alignment/wrapping,
   number formats, row heights/column widths, merged cells, frozen panes,
   filters, and a defined subset of conditional formatting and data validation.
2. Add native Excel tables and a named chart subset, with consistent headers,
   totals, series, labels, and sizing. Keep tables/chart data editable in Excel.
   Validate ranges, sheet names, merged-cell conflicts, and object identifiers.
3. Author/edit real formula cells, including cross-sheet and range references.
   Inspect returns formula expressions separately from cached/results metadata.
   Formula authoring does not require an in-app calculation engine.
4. Adopt uploaded workspace XLSX bytes as revision 1 before modification.
   Inspect and preflight charts, named ranges, styles, validations, conditional
   formatting, external links, protection, and unsupported package parts.
   Preserve supported unaffected content; warn/refuse operations that could
   silently drop unsupported objects. Do not promise universal openpyxl fidelity.
5. Add targeted cell/range styling/value/formula and sheet/table/chart edits.
   Make row/column insertion/removal and formula-reference rewriting explicit:
   implement and test supported cases or reject them, never assume references
   auto-adjust. Keep external-edit conflict and append-only history contracts.
6. Enhance sheet preview with styled cells, merged ranges, widths/heights,
   formula-versus-value selection, bounded chart previews, and explicit limits.
   Cached values are labeled; missing results are not zero or a fresh calculation.
   Pass sheet/range identity into conversational revision requests.
7. Decide in W0 whether in-app calculation is included. If approved, name and
   bound the engine, function subset, circular-reference/error behavior, and
   freshness invalidation. Never execute macros, external data connections,
   network-capable formulas, or embedded commands implicitly. If no engine is
   selected, report unevaluated formulas honestly and verify calculation in Excel.
8. Extend the Office skill with workbook design, input/output separation, units,
   correct references, formula checks, and readable financial/date formats.
   Vault ingestion/querying is distinct from editing the original workbook.

Targets: `artifacts/formats/xlsx.py`, artifact specs/ops and inspection,
`previews.py`, workbook frontend renderer, and `skills/office-documents/`.

Exit: create a styled analysis workbook and revise an uploaded fixture without
losing supported content. In actual Excel edit formulas/table/chart data,
recalculate, save/reopen, and compare expected results to known fixture values.

## W4 - Shared Preview Experience

Outcome: reviewing slides/pages is comfortable without leaving the conversation.

1. Preserve the existing `PreviewBackend` seam across chat, Workspace, and
   Skill resources. Extend types for render lifecycle, warnings, exact-source
   identity, and explicit content-view versus rendered-view selection.
2. Add lazy slide/page thumbnails, current position and count, next/previous
   navigation, zoom/fit-width/fit-page, and expanded viewing. Use a presentation
   viewing mode for decks. PPTX stays static with "Static preview - animations
   and transitions aren't shown"; HTML uses W2H's isolated live playback.
   No canvas editing or PPTX animation playback is required.
3. Preserve navigation/zoom per source and selected revision. Retain the
   newer-revision banner, history, download/open/reveal, and restore contracts.
   Rapid navigation must not display another file's late render result.
4. Keep content view usable for text selection, search where supported, and
   accessibility. Rendered images need page/slide labels and an accessible
   extracted-content alternative; labels alone are not document accessibility.
5. Make Ask agent to revise carry artifact/revision and the chosen slide or
   section or workbook sheet/range into an editable chat draft. Do not auto-submit or mutate the artifact
   from the viewer. If that base is stale, make the conflict/rebase explicit.
6. Verify keyboard/focus behavior, Escape/Back, thumbnail scrolling, error/retry,
   loading/cancellation, and narrow full-width viewing. Preserve existing
   theme/layout conventions; no unrelated dashboard redesign.

Targets: `frontend/src/components/previews/`, API/types, Conversation, Workspace,
and Skills integrations.

Exit: real-browser checks pass on each entry surface, including failure,
revision switching, and narrow layouts. Large fixtures stay bounded.
Include XLSX style/formula-result states and HTML live/static mode distinctions.

## W5 - Agent Visual Inspection And Revision Loop

Outcome: agents can examine actual output and correct it before delivery.

1. Extend artifact capabilities with a minimal mediated way to request/read
   bounded render results for an exact authorized revision. Reuse W1; do not
   spawn ad hoc terminal renderers or return unrestricted server paths.
2. Feed page/slide images through the existing supported model image-input
   path. Preserve image size/context limits, request capture/redaction, and
   normal model-call accounting. A non-vision model does not gain vision or
   silently switch providers; report visual review as unavailable.
3. Teach the skill to plan content/design, create, structurally inspect, render,
   visually review, revise, and recheck changed output. Review the complete
   representative fixture; for larger artifacts, record coverage and any
   unreviewed pages instead of claiming the whole deliverable was checked.
4. Bound iteration count, context, render work, and cost under existing run
   limits. Stop on repeated failures and report actionable limitations rather
   than loop forever or invent a successful review.
5. Associate validation/render/review evidence with the exact revision and
   source run. Structural pass, render pass, model review, and operator approval
   remain separate. A new revision cannot inherit an old visual-review pass.

Cover HTML stable-state captures and XLSX bounded sheet/chart views, not only
Office pages/slides. Formula correctness needs formula/reference checks and,
when available, actual calculation evidence; visual review cannot establish it.
PPTX effect playback checks and HTML motion tests remain separate from screenshots.

Targets: artifact capabilities/registration, harness image-result handling as
needed, artifact provenance, and Office skill procedures.

Exit: a scripted failure fixture and a consented real-provider run demonstrate
inspection, one targeted fix, and review of the corrected revision.
Model self-review alone is not proof of design quality.

## W6 - Integrated Acceptance, Documentation, And Release

1. Run the [acceptance matrix](acceptance-matrix.md) against the integration
   commit. Record actual results and blocked environments, not aspirational
   checkmarks. Keep fixtures synthetic and assets appropriately licensed.
2. Exercise native Office editing and compare rendered appearance; record
   PowerPoint/Word/Excel versions, OS, font environment, and meaningful differences.
   Verify XLSX formula results and preservation, selected PPTX effects in native
   playback, scoped templates, and offline/isolated HTML live playback separately.
3. Verify install/update, supported/partial/failed previews, cache regeneration,
   resource cleanup, and the white-backed icon in packaged macOS/Windows.
   Test Docker runtime and filesystem isolation independently; no Office engine
   install is required. Missing HTML capture affects only that view.
4. Diagnose outstanding packaged-gateway smoke issues before changing release
   logic. Bound gateway/renderer smoke duration and upload useful failure logs.
5. Update official English/Vietnamese usage and limitations, skill resources,
   README, technical/product docs, and changelog before the version/tag step.
6. Run backend and frontend CI-equivalent gates, then the protected-main release
   process with explicit commit/push/release approval. Do not retag v0.2.1.

Exit: artifact craft and preview are verified as one workflow, not two
independent demos. The future Canva-like app remains outside this gate.
