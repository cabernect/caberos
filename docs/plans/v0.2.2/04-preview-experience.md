# W4 - Shared Preview Experience

Status: first slices landed — late-response race guard, slide prev/next +
arrow-key navigation with position counter, zoom controls (50–200% + Fit)
with per-source view-state persistence keyed by rendered-bytes identity,
and revision-bound "Revise" drafts prefilled into the chat composer
(tracked artifacts only, never auto-submitted). Still open: zoom/fit for
non-slide kinds, XLSX range/cell selection (needs W3X metadata), HTML
player embed (needs W2H), browser QA across Chat/Workspace/Skills.
Dependencies: [W1](01-rendering-foundation.md) for exact-source previews and limits,
[W2H](02h-html-presentations.md) for HTML playback,
[W3X](03x-xlsx-craft.md) for workbook metadata.

## Purpose And Operator Outcome

Review a deliverable from chat, Workspace or Skills without leaving CaberOS.
Navigate slides/pages/sheets, inspect the selected revision, and prepare a precise
request for changes. This is a viewer, not a drag/drop editor or dashboard redesign.

Preserve the existing `PreviewBackend` seam and current theme. Chat opens the
referenced revision; Workspace resolves the proven current file. Skills resources
retain their own authorization and supported actions.

## View Modes

| Source | Main view | Alternative/limitation |
|---|---|---|
| PPTX, uploaded or generated | Best-effort slide-grouped content, richer supported views if added | Persistent limitation alert; no native layout/effect playback claim |
| DOCX, uploaded or generated | Best-effort document content, richer supported views if added | Persistent limitation alert; no native pagination/font fidelity claim |
| HTML deck | W2H isolated live player | Stable captures/source as supported; screenshots do not verify motion |
| XLSX | Bounded styled sheet/range view | Formula text and result provenance; not verified recalculation |
| Existing formats | Current PDF/image/media/text viewers | Keep established actions and bounds |

Follow the [preview contract](preview-contract.md): alerts are non-blocking and
apply to all approximate Office views. Do not disable uploaded files, route the
operator to install LibreOffice, or treat existing download actions as a replacement
for supported preview content.

## Implementation Slices

1. **Types/state.** Extend source identity, revision, lifecycle, warnings and
   renderer metadata through existing API/frontend types. Keep content and layout
   rendering distinct. Reject late results for a different selected source.
2. **One page end to end.** Show loading, ready, unavailable, failed and retry
   states. Retain download/open/reveal when allowed even if rendering fails.
   Show the format-specific limitation notice persistently, with errors and
   truncation separate. PDF/non-Office views must not receive Office-only warnings.
3. **Navigation.** Add lazy thumbnails, position/count, previous/next, page entry,
   zoom, fit width/page, expanded view and deck presentation mode. Preserve
   navigation/zoom by source plus revision, not globally across files.
4. **HTML and sheet integration.** Embed only W2H's admitted isolated player.
   Show live/static distinctions and reduced-motion controls. For XLSX provide
   sheet selection, bounded rows/columns, range/cell selection, styles and formula
   states; indicate omitted/truncated content instead of silently hiding it.
5. **Revision actions.** Retain history, explicit newer-version banner, original
   download and restore-as-new. Never replace an old revision being reviewed.
   Preserve external-edit conflict behavior.
6. **Ask agent to revise.** Prefill an editable chat draft containing artifact
   ID, base revision and slide/block/section or sheet/range. Do not auto-submit.
   For unsupported/untracked sources explain adoption/identity requirements;
   never invent a stable revision or silently rebase a stale request.
7. **Accessibility/responsiveness.** Keyboard and focus handling, Escape/Back,
   readable labels/targets, thumbnail scrolling and narrow full-width layout.
   Rendered images need an accessible extracted-content alternative, not only
   page-number labels. Avoid shortcuts stealing text input.

## Failure And Race Cases

Test switching files/revisions during loads, closing/reopening, late failures,
cache eviction, missing runtime, unsupported source and a source changed outside
CaberOS. Cancel obsolete reads where safe; do not cancel another consumer's job.
Clear owned object URLs/listeners/player resources and restore focus on close.

## Verification And Done When

Acceptance: A10, A12-A19, A26, A31-A33 and A41-A42 formula/preview states.
Use real-browser checks from chat, Workspace and Skills with isolated QA data.
Include narrow viewport, keyboard-only interaction, failure/retry and large files.

- [ ] Every surface resolves the intended source and exposes only allowed actions.
- [ ] Navigation, zoom, revision switching and source races pass browser checks.
- [ ] Office limitation alerts, HTML live/static and XLSX formula states are explicit.
- [ ] Revision request creates a correct editable draft without submission.
- [ ] Existing preview formats and desktop open/reveal behavior regressions covered.

Targets: `frontend/src/components/previews/PreviewPanel.tsx`, `renderers.tsx`,
API/types, Conversation/Workspace/Skills integration and preview routes.
