# W2 - Presentation Authoring, Editing And Outputs

Status: implementation started 2026-11-16 after operator approval.
Owner: CaberOS artifact/presentation workstream.
Direction accepted: consolidate W2 and W2H around one presentation spec.

Scope update: editing is agent-driven for the current W2 slice. Manual
click-to-type editing, thumbnail/structure toolbars, data grids, editor drafts,
and editor-specific undo/redo are deferred. Their design notes below are future
reference, not current acceptance gates; P5/P6 and manual-edit scenarios 3/4
must not block the agent-only slice. A separate proposal-review/approval
pipeline is also deferred. Agent edits use base-revision checks: stale changes
fail rather than overwrite newer content. Existing revision history and
restore-as-new-revision remain in scope.

Landed so far (foundation slice): `artifacts/deck_spec.py` shared
normalization, `formats/deck.py` canonical `.deck.json` handler
(build/inspect/validate/revise with pinned image snapshots),
`artifacts/deck_pptx.py` native renderer + `export_pptx` provenance,
`GET /workspace/deck-export.pptx` (revision-pinned, refuses unsupported
slides with 422 until image fallback lands), preview kind `deck` serving the
normalized spec, and a React slide renderer in PreviewPanel replacing the
iframe player. The old generated-HTML deck stack (formats/html.py,
deck_capture.py, deck_export.py, /workspace/deck* endpoints, capture strip,
DeckExportMenu) is removed. Still planned per the sequence below: designed
HTML track parity, per-slide image fallback, targeted agent block edits, PDF.
Manual editing and structure controls are deferred per the scope update above.

Playback slice (2026-11-17): `.deck.json` now validates deck-level motion
defaults, per-slide transitions, block entrance effects and click reveals
(including individual bullets). Slideshow executes fade/slide transitions
and fade/rise entrances, with reversible Next/Back steps, click-to-advance,
keyboard controls and reduced-motion support. Normal preview and native PPTX
show final content; browser motion is explicitly not exported to PowerPoint.
Autoplay, native PPTX motion and visual parity remain unimplemented.

This is the primary W2 plan. [Native PowerPoint requirements](02-native-pptx.md)
and [HTML playback requirements/history](02h-html-presentations.md) remain
supporting renderer tracks, not independent authoring architectures. Their
template, effects, safety and acceptance obligations are not removed.

## Product Contract

One presentation has one canonical, versioned JSON spec and pinned assets.
Agents and operators edit that source, not generated HTML or Office XML.
Content, identity and theme decisions are shared; each renderer owns its layout
implementation. The agent writes content and chooses supported layouts/theme
tokens, not arbitrary formatting or pixel coordinates.

```text
Agent operations / operator edits
                 |
       Validate + conflict/approval checks
                 |
       Immutable presentation revision
          (JSON spec + pinned assets)
                 |
     +-----------+------------------+
     |           |                  |
 HTML renderer   PPTX renderer      PDF renderer (planned)
     |           |                  |
 live preview    native objects     paged output
                 + declared image
                   fallback where required
```

- "Create slides" defaults to the HTML presentation experience.
- "Create a PPTX" requests a real PowerPoint output from the presentation
  source, not an HTML file renamed to `.pptx` or an undisclosed screenshot deck.
- "Create an HTML page/report" remains an ordinary scrolling document. It is
  not a presentation and does not acquire slide controls.
- HTML is not reverse-parsed to reconstruct native content. Reading a stored
  JSON companion from an old deck package is source recovery, not DOM inference.
- Native layout may differ from HTML. Shared content does not prove native
  Office layout, animation compatibility, or identical pagination.

## Workspace Files And Preview Panel

Accepted source-file direction: `quarterly-review.deck.json` is the main
workspace presentation file. Selecting it opens rendered slides in the shared
PreviewPanel, not raw JSON by default. The presentation renderer owns View/Edit
behavior; the shared shell keeps file identity, history, export and expansion.
Expanded editing uses the same source/draft, not a second editor implementation.

```text
Workspace/
  quarterly-review.deck.json   # canonical presentation source
  quarterly-review.pptx        # when explicitly requested/saved as an output
  quarterly-review.html        # optional portable HTML export
```

HTML playback is a derived view and need not create a visible workspace HTML
file. PDF is a planned derived export. Downloads need not create workspace
siblings; saving an output into the workspace must be explicit and must not
overwrite an externally edited output without the existing conflict checks.

"Create a PPTX" produces a real `.pptx` plus its `.deck.json` source companion.
The source remains authoritative for CaberOS editing. External PowerPoint edits
are an output fork, not a silent source update. A derived file records its source
artifact/revision/hash; it is not an independently authored presentation model.

Only validated `.deck.json` files enter the presentation renderer. Ordinary
JSON is still source/code; a JSON object containing `slides` is not sufficient
admission. Source assets are pinned with revisions, not dependent on mutable
workspace image files. Source view remains available for inspection.

Editing is available for the editable source at an authorized current revision.
Historical views and Skills resources stay read-only unless explicitly
restored/copied into an editable workspace source. Arbitrary uploaded HTML/PPTX
does not gain editability merely by opening it in the panel.

## Shared Source And Identity

The model covers deck identity, schema version, theme/template reference,
ordered slides, stable slide/block IDs, layout/region assignments, content,
notes and supported effects. Text, bullets, images, tables and charts have
typed content rather than arbitrary DOM or Office instructions.

Initial layouts: title, title plus content, two columns, and section divider.
The later layout catalog preserves the existing comparison, image/caption,
metric and chart requirements. Layouts define regions, spacing and capacity.
Changing layout preserves block identity and content; if regions cannot be
mapped without loss, show a proposed mapping instead of dropping blocks.

- Reordering preserves IDs. Duplication creates new slide and nested block IDs.
- Replacing a block preserves its addressed ID unless an explicit remove/add
  operation changes identity.
- Titles have an addressable field/identity; block IDs do not encode a mutable
  slide position. Deleted IDs are not silently reused.
- Table cells and chart series/categories have validated data models; edits do
  not become raw markup. Native chart data remains editable where supported.
- Assets are immutable content-addressed snapshots. Historical export never
  rereads today's workspace file, URL, CSS or theme.
- A theme/template version is pinned with the revision. A new renderer or
  template does not rewrite old source or pretend its output is the old output.

Reuse artifact revision/provenance machinery. The first implementation slice
must establish `.deck.json` as the source artifact, with its immutable spec and
asset manifest bound to each source revision and a single atomic publication
path. Derived outputs refer back to that source revision. Do not
maintain independently mutable HTML, PPTX and JSON sources of truth.

## Editing

### 1. Ask The Agent

The agent proposes narrow operations by stable identity: set slide layout,
set title/text, replace/add/remove/move a block, edit table/chart data, or
add/duplicate/remove/reorder slides. Whole-deck replacement is not the normal
revision mechanism. Global theme changes are explicit global operations.

Illustrative semantics, not a claim that these tool names are implemented:

```json
{
  "base_revision_id": "rev-12",
  "operations": [
    {"op": "set_slide_layout", "slide_id": "s3", "layout": "two_content"},
    {
      "op": "replace_block",
      "slide_id": "s3",
      "block_id": "b-revenue",
      "expected_block_hash": "hash-of-the-base-block",
      "value": {"type": "bullets", "items": ["Shortened point", "Next point"]}
    }
  ]
}
```

The writer validates the entire operation batch before committing it.
Unknown IDs, fields, layouts, blocks and ambiguous legacy identities fail
explicitly. Agent operations continue through syscall mediation and audit.
Operator edits use authenticated endpoints and the same validation, revision,
conflict and audit writer; the editor does not gain agent authority.

### 2. Click And Type (Deferred)

Selecting a supported text region enters plain-text editing. Enter/blur commits
an intentional edit transaction; Escape cancels it. Paste strips foreign HTML
and styling. IME composition, multiline text, keyboard focus and empty values
must work without premature commits.

Renderer-owned `data-block`/field IDs map the text region to the spec. DOM
changes are transient editing state, never the authoritative document. The
platform validates and saves the resulting spec operation, then renders the
committed value. Show saving/saved/conflict/error states and retain unsaved text
on network or validation failure.

The player remains opaque-origin and sandboxed. A platform-owned edit runtime
or shell-owned editing surface must be chosen and verified before implementation;
do not enable `allow-same-origin` to make `contenteditable` convenient.
Any edit bridge checks the active frame, source revision, editor generation,
slide/block identity, allowed operation and size. It conveys text operations,
not arbitrary HTML, commands, credentials, file paths or platform authority.
Historical revision views are read-only until explicitly restored or branched.

### 3. Layout-Based Controls (Deferred)

- Thumbnail list: select, reorder, duplicate and delete slides, with keyboard
  alternatives to drag-reordering and confirmation/undo for destructive edits.
- Per-slide layout picker and deck-level theme picker.
- Add/remove supported blocks and assign them to valid layout regions.
- Edit table/chart values in a grid with typed data validation, not free-form
  contenteditable cells embedded in the slide.
- Keep focus and selection by identity after local edits and reordering.

Free-position dragging, resizing, rotating and arbitrary CSS are out of scope.
Pixel-level finishing belongs in exported PowerPoint. This is a layout editor,
not a Google Slides/Canva implementation.

## Undo, History And Agent/User Conflicts

Every committed edit transaction creates an immutable source revision with its
base, actor, changed IDs/fields and source hashes. Draft keystrokes may be
coalesced; they are not a revision per character. Undo/redo and historical
restore create new commits representing the chosen state, not deletion or
rewriting of revision history. A new edit after undo clears that draft's redo
branch without deleting audit/history evidence.

Use compare-and-swap on the base revision. Stale edits fail safely; they do
not overwrite a newer edit. Optional block hashes add a content precondition.
There is no separate proposal store, approval gate, or automatic rebase in
the agent-only slice. Read/write-set tracking for reviewed rebases is deferred.

Deferred with proposal review: for a proposal targeting operator-edited
content, show the affected content and proposed diff before applying it. An old approval
cannot authorize a write after that content changes. Structural operations,
deletion, layout/region changes and global themes can overlap user work even
without changing the same text field; their affected set must include that work.
Being mediated or using targeted operations alone does not prevent lost edits.

Deferred with manual editing: unsaved operator text stays local and visible.
Do not replace the active editor
with an incoming agent revision. Offer retain/cancel/review/reapply choices;
reapplying requires a fresh base and validation.

## Rendering, Exports And Quality

All derived results identify presentation revision, spec hash, asset manifest,
renderer version, theme/template version and export mode.

- On commit, immediately invalidate affected derived results. Re-render the
  changed slide for feedback; a global theme/layout dependency may invalidate
  more. Use generations so late work cannot replace newer state.
- HTML updates after the source commit. PPTX/PDF may be generated on demand,
  but must be regenerated for that same revision before download. Cached older
  bytes are never labeled current. A renderer failure is visible and does not
  roll back the source or silently serve last-good output as new.
- Text/tables/charts/shapes/pictures use native PowerPoint objects where
  supported. For unsupported content, use the smallest safe declared fallback;
  the first supported unit may be a whole slide. Report exactly which slides
  or regions flatten and why, before download and in file metadata.
- Native layout version 3 supports multiline titles and bounded fitting before
  proposing raster fallback: body 20-16 pt, headings 24-20 pt, and tables 14-12 pt.
  Each column fits independently, with a reserved footer region and explicit
  paragraph leading. Text budgets remain conservative estimates, not native
  glyph measurements; PowerPoint appearance is a separate verification gate.
- Full-deck image export is an explicit alternative, never the editable default.
  Refuse unsafe or invalid output; fallback is not permission to export clipped,
  blank or broken-image slides as successful.
- HTML and PDF use the HTML layout track, but PDF needs a separate fixed-page,
  final-reveal print contract. PDF export is planned, not presently verified.
- Native effects require a named support matrix and PowerPoint evidence;
  unsupported effects flatten/omit only with disclosure. Do not claim HTML
  captures prove PPTX/PDF appearance or motion.

Quality starts with reference slides, not runtime patch accumulation:
consistent grid, typography, margins, contrast and data hierarchy. Preserve a
16:9 canvas and a separate footer region. Text cannot overlap the footer.
Use explicit layout/text budgets and actionable overflow diagnostics. Do not
solve bad composition by silently shrinking everything to unreadable text.
The player scales the canvas to its container; it does not redefine the slide.

## Implementation Sequence And Exit Gates

| Slice | Deliverable | Required evidence before advancing |
|---|---|---|
| P0: plan and references | Review this plan and a curated sample spec/slide set | Operator agrees on scope, initial layouts and quality rubric; inventory speculative worktree code |
| P1: source and revisions | Shared schema, stable IDs, pinned assets, immutable spec/revision writer, migration policy | Validation/bounds tests, exact historical source/asset recovery, CAS failure without partial publication |
| P2: designed HTML track | Small layout/theme catalog, isolated playback, real overflow diagnostics | Human-reviewed reference slides at panel/fullscreen sizes, footer safety, narrow-layout checks, offline/isolation tests |
| P3: parallel native track | Same spec -> native PPTX, explicit per-slide fallback, export identity/cache contract | Native text/table/chart/image edits and save/reopen in PowerPoint; fallback disclosures and exact-revision tests |
| P4: targeted agent edits | ID-addressed operation batches, current-base checks, revision history/restore | Unrelated content unchanged, stale bases refused, mediated/audited writes; no separate proposal-approval pipeline |
| P5: inline text editing | Click/type, plain-text paste, commit/cancel/error states | IME/keyboard/blur tests, bridge isolation, lost-update and unsaved-draft scenarios |
| P6: structure and history UI | Thumbnails/reorder/duplicate/delete, layout/theme/block controls, table/chart grid, undo/redo | Stable identity, no dropped content, reversible transactions and agent/user conflict exercises |
| P7: PDF and release integration | Revision-bound PDF, cross-renderer verification, docs and sample corpus | Same-revision output matrix, separate HTML/PDF/PowerPoint evidence, W5/W6 acceptance |

Each slice is end-to-end and independently reviewable. Existing W0/W1 safety
contracts and W4 shared-panel requirements remain prerequisites, not things to
reimplement. W3/W3X remain separate document/workbook workstreams.

## Compatibility And Migration

Existing artifact bytes/revisions are immutable and remain downloadable.
Legacy embedded specs may be recovered through an explicit migration into a
new canonical-source revision; do not silently upgrade a previewed old file.
Missing block IDs/assets get explicit migration/provenance treatment. If the
source cannot be established, retain view/download and declare editing or
native regeneration unavailable.

Arbitrary uploaded HTML is not a reconstructable presentation source.
Uploaded or externally edited PPTX is not presumed to round-trip to the spec.
Native PowerPoint finishing can produce an external fork; importing it back
requires an explicit, separately bounded reconciliation workflow.

The current image-export implementation, provisional native renderer and
sample files are input to P0 review, not proof P1-P7 are done. Reconcile or
replace them only after the plan is reviewed; preserve unrelated worktree edits.

## Acceptance Scenarios

1. One spec produces an attractive live deck and a separately verified editable
   PPTX with the same content/IDs/assets; unsupported regions are labeled.
2. An agent shortens one block without changing another block, slide, or note;
   stale bases fail and external file edits are preserved, without a separate
   proposal-review workflow.
3. Deferred: an operator types/pastes plain text, commits, undoes and restores; exports
   follow the committed revision and failed saves preserve the draft.
4. Deferred manual controls: reorder/duplicate/delete/layout/theme/grid edits maintain valid identity and
   data; incompatible layouts ask for mapping instead of discarding content.
5. Old spec/assets/exports remain recoverable after live files or renderers
   change; no stale-output race mislabels bytes.
6. Long text, Vietnamese/IME input, missing fonts, dense tables, broken assets
   and unsupported effects produce honest outcomes, not silent visual damage.
7. Browser and Tauri isolation hold during playback and editing. No automatic
   dependency downloads, external egress or permission expansion occurs.

Map these scenarios to existing A01-A12/A31-A36 and proposed editing/source rows
A43-A49 in the [acceptance matrix](acceptance-matrix.md) during P0 review.
No percentage or release completion is claimed here.
