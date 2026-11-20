# W1 - Revision-Bound Preview Foundation

Status: backend foundation implemented 2026-11-13; capture/lifecycle evidence
and platform coverage remain open. Existing approximate Office previews are
the baseline.
Dependencies: [W0](00-contracts-fixtures.md); HTML capture also uses [W2H](02h-html-presentations.md).
Scope: [preview contract](preview-contract.md). No LibreOffice or full Office
layout engine is required. Uploaded and generated files use supported preview paths.

## Purpose And Operator Outcome

Show supported content for the exact selected file revision, with explicit mode
and limitations. The operator and agent must inspect the same source identity;
an approximate Office content view is valid and must not be called native layout.
Keep the original editable Office bytes unchanged.

Reuse `previews.py` content extraction. It and `artifacts/pdf_render.py` do not
prove native Office layout fidelity; no such fidelity is required for the preview.
This work does not add a public Office-to-PDF export tool or a generic Tasks service.

## Contract To Settle

Input: authorized source identity (artifact/revision or proven live source),
source hash, supported position/range, and bounded options. Output: source
identity/hash, preview mode/version, format-specific limitation codes, warnings,
state, and bounded content/image references. Counts/dimensions must describe the
actual mode; DOCX extraction must not invent native Word page counts. Include
font/render metadata only where a layout or capture path actually uses it.

States must distinguish unavailable runtime, pending, rendering, ready, failed,
cancelled, and stale. Structural validation is independent from rendering.
Errors need safe diagnostics and retryability without exposing local secrets/paths.

## Implementation Slices

1. **Source resolver.** Reuse artifact service and workspace/skill provenance.
   Resolve exact immutable revision bytes; snapshot/hash live files before work.
   Missing/ambiguous legacy roots fail explicitly rather than use today's default.
2. **One preview seam.** Extend existing preview handling shared by operator
   and agent inspection, not a parallel Office engine. Reuse slide-grouped
   extraction, DOCX content and XLSX rows. Expose mode/limitation codes for W4
   alerts; missing native layout support must not disable usable previews.
3. **Safe parsing/capture.** Bound Office parsing/decode work and deny macros,
   links, remote resources and executables. Use isolated workers for expensive/
   untrusted parsing or HTML capture as needed; no Office conversion worker is
   required. Apply filesystem/network/process controls to actual worker paths.
4. **Bounds and lifecycle.** Specify input/ZIP expansion/image/page/output limits,
   wall time, concurrency, CPU/memory policy, cancel/timeout, child-process cleanup,
   and restart reconciliation. Keep backend event loop responsive during work.
5. **Cache.** Key by source hash plus preview implementation/version and options;
   include fonts/runtime when relevant to captures/design views.
   Deduplicate in-flight requests, publish completed output atomically, bound
   disk use, and regenerate after eviction without deleting active readers' data.
6. **Authenticated reads.** Extend existing preview APIs for lazy page/thumbnail
   access. Recheck source authorization even on cache hits. Do not return worker
   paths, arbitrary file URLs, or control ports.
7. **Readiness integration.** Existing Office content previews need no optional
   Office runtime. Capture/runtime absence affects only that optional view, not
   Office content access. A preview failure never marks valid source bytes corrupt.

## HTML And XLSX Boundaries

HTML live playback belongs to W2H; its stable captures reuse source/result
identity here. No Office dependency is required for browser HTML playback.
XLSX uses a bounded styled sheet view with formula metadata; paginated printing
is not a release requirement. Renderer recalculation must not silently modify
source workbooks or make preview values appear verified.

## Failure And Race Scenarios

- Request revision A, switch to B, then A completes: A remains associated only
  with A; the panel does not replace B's visible output.
- Simultaneous requests for the same key share work; one viewer closing does
  not corrupt another viewer's active read.
- Runtime crash/timeout/restart produces an explicit terminal/recoverable state,
  kills owned children, and cleans owned temporary data.
- Cached output for another agent/revision still requires authorization; content
  hash deduplication never grants access.

## Verification And Done When

Acceptance: A06, A10-A13, A17-A22, A27-A29; HTML capture portion of A33.
Test existing preview behavior with both uploaded and generated fixtures.
Check limitation metadata separately from the future visible W4 alert.
Measure resource bounds and no-egress behavior separately on supported platforms.

Implemented 2026-11-13 (backend, macOS evidence only):

- [x] Exact-revision content path identifies mode and applicable limits —
  every preview payload carries `preview_version`, `mode`/`limitations`
  (Office), and a `source` block `{kind: revision|live_file, artifact_id,
  revision_id, sha256}` over the exact bytes rendered. Agent paths
  (`read_file`, `artifact_inspect`) declare the same fidelity contract.
- [x] Cache/race/auth tests pass — bounded LRU keyed by content hash + name +
  `PREVIEW_VERSION`, per-key single-flight, extraction off the event loop,
  resolution (ownership/root checks) always precedes cache lookup. ZIP
  expansion guard bounds Office parsing on preview/inspect/revise/read_file.
- [ ] Timeout/restart/cleanup tests — the synchronous extraction path has no
  subprocess or durable jobs; worker lifecycle belongs to the async capture
  path (W2H/W5) and stays open there.
- [x] Uploaded/generated Office remains previewable without an Office
  runtime — by construction; fixture corpus covers both.
- [ ] macOS, Windows, Docker evidence or explicit blockers recorded —
  implemented and tested on macOS only; Windows/Docker runs outstanding.

Primary targets: `backend/src/agentos/previews.py`, `artifacts/service.py`,
`models/artifact.py` only if needed, existing preview routes, `dependencies.py`,
`runtime_support.py`, installer recipes, and packaging.
