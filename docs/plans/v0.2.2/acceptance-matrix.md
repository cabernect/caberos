# v0.2.2 Acceptance Matrix

Status: planned scenarios, not passing results.
Scope: [release plan](../v0.2.2-release-plan.md).
Sequence: [workstreams](README.md).

## Evidence Rules

- Record commit, command/procedure, fixture, environment, expected/actual result,
  and pass/fail/blocked/skipped for each scenario. Never count a skip as a pass.
- Separate unit, browser, real-provider, packaged runtime, and native Office
  evidence. A parser reopen or screenshot is not evidence of native editability.
- Keep credentials/customer data out of fixtures, screenshots, and logs.
  Real-provider tests require consent with cost/egress expectations.
- Record renderer/version and fonts alongside visual evidence. Baseline image
  comparisons run under a pinned environment, with reviewable tolerances.
- Create dated result records during implementation; this plan contains none.

## Required Scenarios

| ID | Scenario | Acceptance evidence |
|---|---|---|
| A01 | Old PPTX/DOCX/XLSX specs and operations | Existing callers retain supported defaults and behavior |
| A02 | Designed analysis deck | Eight slides include varied layouts, native text/shapes/table/chart, notes, local images |
| A03 | Styled report | Four-to-six-page report includes cover, hierarchy, styled table, image/caption, header/footer, page numbers |
| A04 | Native PPTX editing | In Microsoft PowerPoint edit text, resize/recolor shape, change table cell and chart data, save/reopen |
| A05 | Native DOCX editing | In Microsoft Word edit body/heading/table, inspect styles and page numbering, save/reopen |
| A06 | Visual fidelity | Compare CaberOS renders with actual Office; record differences and unsupported features |
| A07 | Typography edge cases | Long text, Vietnamese diacritics, missing fonts, large labels: readable or explicit warnings; no silent clipping claims |
| A08 | Targeted deck revision | Simplify identified slide 4 after reorder; correct target changes, unrelated slides preserved |
| A09 | Targeted report revision | Replace summary/style without corrupting other sections, tables, sources, or supplied figures |
| A10 | Revision fidelity | Chat opens exact old revision; Workspace current bytes; newer-version banner does not auto-switch |
| A11 | External edit | PowerPoint/Word/Excel changes cause conflict; preserve/capture workflow retains external bytes |
| A12 | Restore | Restore creates a new revision; original versions and their render associations stay intact |
| A13 | Preview surfaces | Same renderer contract works from chat, Workspace, and Skill resources with correct available actions |
| A14 | Navigation | Thumbnails, position, keyboard, zoom/fit, expanded/presentation modes, and close/focus restoration |
| A15 | Narrow layout/accessibility | Full-width view, operable controls, labels, content alternative, no clipped essential actions |
| A16 | Revision-bound revise request | Panel action prefills editable draft with artifact/revision/slide, section or sheet/range; never auto-submits |
| A17 | Races/cache | Rapid file/revision changes, duplicate requests, changed font environment, eviction: no stale or cross-source output |
| A18 | Restart/cancel | Interrupted renders reconcile; timeout/cancel kills owned children and cleans temporary data |
| A19 | Absent/broken renderer | Honest readiness/error/retry and labeled content fallback; source/download remain usable |
| A20 | Hostile input | Malformed ZIP/XML, expansion bombs, huge images/pages, external links, embedded objects, traversal/symlinks |
| A21 | Office isolation | No macro/document-script execution, document-driven network requests, or unauthorized host reads/writes |
| A22 | Authorization | Cross-agent/revision/cache access rejected; unresolved legacy live root never guessed |
| A23 | Visual quality loop | Exact revision rendered and seen by supported vision model; injected layout problem fixed and rechecked |
| A24 | Unsupported model/limits | Non-vision model, render failure, context/cost/iteration limit stop honestly; no silent model/provider switch |
| A25 | Review provenance | Review coverage/status binds to revision; changed revisions do not inherit visual approval |
| A26 | Regression formats | XLSX, direct PDF, Markdown/code, SVG/images, audio/video, ordinary files retain existing behavior |
| A27 | Packaged macOS | Fresh install and v0.2.1 update preserve data; renderer readiness, renders, open/reveal, icon verified |
| A28 | Packaged Windows | Same workflow verified independently; native process/resource isolation recorded |
| A29 | Docker | Explicit runtime setup, mounted workspace, fonts, no-network rendering, limits, cleanup verified |
| A30 | Release/doc hygiene | EN/VI docs, skill schemas, changelog, bounded smoke tests, consistent manifests before tag |
| A31 | HTML creation and portability | Revisioned deck with local assets opens offline; supported motion/interaction and reduced-motion mode work |
| A32 | HTML isolation | Hostile scripts cannot access parent DOM, credentials, CaberOS APIs, Tauri IPC, host files or implicit network; looping deck cannot freeze app |
| A33 | HTML revision/capture | Asset bytes pinned per revision; stable slide captures and separate live-playback tests; targeted edits retain history |
| A34 | Scoped Office templates | Named PPTX masters/layouts and DOCX styles render/edit correctly; unsupported template features flagged before destructive writes |
| A35 | PPTX effects | Selected transitions/animations play in PowerPoint; CaberOS static preview warns it does not show playback |
| A36 | Effect preservation | Supported revisions preserve effect semantics; unsupported edits warn/refuse, never silently strip effects |
| A37 | Styled XLSX creation | Multi-sheet workbook with fills/borders/alignment/wrap/number formats, merges, widths, freeze/filter, native table/chart and supported validation/conditional formatting |
| A38 | Real formula authoring | SUM/IF/AVERAGE and cross-sheet formulas stored as formula cells; Excel recalculates known expected values after save/reopen |
| A39 | Uploaded XLSX editing | Adopt original bytes as revision 1; target cells/ranges/formulas/styles without losing supported charts, tables, names, validations or unaffected sheets |
| A40 | Workbook preservation guards | Unsupported features, protection, external links and reference-changing edits detected; warn/refuse rather than silently discard content or break formulas |
| A41 | Formula-result honesty | Formula expression distinct from unevaluated/cached/fresh result; edits invalidate freshness; no fabricated zero; unapproved engine never claimed |
| A42 | XLSX preview/editability | Styled bounded sheet/range/chart preview, explicit truncation and result provenance; native Excel table/chart/formula editing verified |

If a release-critical target or native Office check is unavailable, mark it
blocked and explicitly revise the release promise before shipping. Do not
substitute LibreOffice or a browser viewer for the actual Microsoft Office gate.

## Visual Quality Rubric

Review the agreed reference Office/HTML decks, report, and workbook before and after the changes. Keep
example renders in the result evidence; use a human rubric as well as automated
geometry checks. The operator signs off the reference designs during W0.

| Dimension | Required outcome |
|---|---|
| Narrative | Clear audience/purpose, sensible progression, supported conclusions, concise summary |
| Hierarchy | Titles, body, captions, and data labels have consistent readable roles |
| Composition | Intentional alignment, spacing, whitespace, and varied appropriate slide layouts |
| Legibility | No unintended overlap, clipping, tiny text, distorted images, or unreadable tables |
| Data integrity | Charts/tables match supplied figures; real formulas use correct references; calculated results need separate evidence; no invented values, sources, or citations |
| Consistency | Coherent palette, fonts, numbering, table styles, and image treatment |
| Editability | Native objects retain their roles after save/reopen and targeted revisions |
| Preview honesty | Renderer/font limitations, static PPTX playback limitation and formula-result provenance visible; content view not mislabeled as layout preview |

Blockers include lost content/data, unreadable content, rasterized editable
elements, wrong-revision display, overwritten external edits, unbounded render
work, unauthorized access/egress, and falsely claimed validation/review.
Cosmetic preferences are reviewed against the agreed designs, not claimed to
be objectively solved by a model's self-assessment.

## Integrated Story

1. Attach synthetic market data and licensed brand/image assets to a pinned
   workspace; request an eight-slide PPTX, companion DOCX, HTML deck, and styled
   analysis workbook based on an uploaded XLSX.
2. Agent chooses a coherent visual direction, creates native editable files,
   validates them, renders them, and reviews the full reference outputs.
3. Inspect in chat; switch slides/pages/sheets, zoom, expand, and open old
   revisions. Compare static PPTX previews with HTML live playback.
4. Request "simplify slide 4" from the selected slide; inspect the prefilled
   request, submit it, and verify the resulting revision and its visual check.
5. Revise the report summary while preserving figures and source references.
6. Open Office outputs in PowerPoint/Word/Excel, make native edits, verify PPTX
   effects and Excel formula results, save/reopen, then confirm
   CaberOS detects those external changes before another agent revision.
7. Restore an older version as a new revision and retrieve the original again.
8. Repeat preview/failure checks with the optional renderer unavailable.
9. Revise uploaded workbook formulas/styles/chart data while retaining original
   bytes and unaffected supported features. Verify cached/unevaluated values are
   not presented as freshly calculated.
10. Download the HTML deck, play it offline, and verify isolated in-app playback
    cannot access CaberOS authority or make implicit network requests.

## Automated Gates

```sh
cd backend
uv run ruff check src/ tests/
uv run ruff format --check src/ tests/
uv run pytest -q
```

```sh
cd frontend
npm run lint
npm run test
npm run build
```

Add focused artifact/render/preview tests near `backend/tests/test_artifacts.py`,
`backend/tests/test_previews.py`, and frontend preview components as implemented.
Use real-browser verification with isolated QA data; never replace
`backend/data/agentos.db`. Website changes additionally require locale checks,
Astro checks/build, and EN/VI navigation verification using existing commands.
