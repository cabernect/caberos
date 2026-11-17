# W4 (+W3X preview surface) Acceptance Evidence — 2026-11-17

Scope: shared preview experience — revision fidelity, surfaces, navigation,
zoom, revise drafts, races, limitations, regression formats; plus the W3X
XLSX scenarios (A37–A42) verified against the new craft + grid preview.
Environment: macOS dev stack (`backend :8081`, `frontend :5173`),
`uv run pytest`, vitest/tsc/eslint, agent-browser CLI against the real app
(workspace `caber`, artifact `artifacts/w3x-xlsx-smoke.xlsx`,
`artifacts/w3-docx-smoke.docx`).
Working tree: uncommitted W4 changes on top of `d539d4a` (W3X commit).

Status vocabulary: **pass** = evidence below; **partial** = shipped subset,
gap named; **descoped** = removed by operator decision; **n/a** = not
applicable.

## W4 scenario results

| ID | Result | Evidence |
|---|---|---|
| A10 | pass | `test_preview_revision_uses_stored_bytes_and_flags_newer` — chat/revision view renders stored revision bytes and flags a newer workspace version without auto-switching. History endpoint lists revisions newest-first (`test_revisions_endpoint_lists_newest_first`); History button present in panel (browser-verified). |
| A11 | pass (existing) | External-edit conflict path unchanged: `revise` CAS on `base_revision_id` + content-hash check; W3X adds the preflight gate on top (`test_pivot_parts_block_revise_until_acknowledged`). External bytes preserved as their own revision via adopt/restore paths (existing artifact tests). |
| A12 | pass | `test_restore_endpoint_appends_new_revision` — restore creates a new revision; originals and render associations intact. |
| A13 | pass | One `PreviewBackend`/payload contract feeds chat, Workspace, and Skills surfaces; same `PreviewBody` dispatch for all kinds. Browser-verified from the agent Workspace panel (file list → preview). Skill-resource previews share the same renderer path. |
| A14 | pass | Slides: prev/next, arrow keys, position counter, zoom 50–200% + Fit, per-source view-state keyed by rendered-bytes identity (`viewState.ts`). Workbook: sheet tabs, cell click → formula bar, drag/shift range selection with Count/Sum/Avg, zoom controls, status bar dims. Document: zoom controls re-added this session (operator request). No invented Word pagination anywhere — docx preview is extracted content, labeled approximate. |
| A15 | pass (checked surface) | agent-browser at 420×800 viewport: `documentElement.scrollWidth === innerWidth` (no page-level horizontal overflow), Download/History/Revise/Zoom controls all reachable, grid scrolls inside its own container. Content alternative: workbook cells are real table semantics (columnheader/rowheader/cell roles in the a11y tree); approximate-mode limitation note is persistent text, not icon-only. Full keyboard-only traversal of every surface not exhaustively re-run — partial on depth, pass on the checked surface. |
| A16 | pass | `PreviewPanel.test.tsx` "prefills an editable revise draft with artifact, revision, and focus" — draft contains artifact id + base revision + focus label, editable, never auto-submitted. Revise button browser-verified present on tracked artifacts only. |
| A17 | pass | Late-response race guard shipped earlier (source-identity keyed state; `viewStateKey` re-keys on rendered-bytes hash). Workbook/document zoom state follows the same per-source persistence contract as slides. Rapid revision switching covered by `test_preview_revision_uses_stored_bytes_and_flags_newer` + view-state keying; duplicate-request dedup is backend-cached per source. |
| A18 | pass (existing) | Render timeout/cancel and orphan reconciliation are W1/backend concerns covered by existing tests; no new render jobs introduced by W4 UI work. |
| A19 | pass | Persistent "Limited preview" Office note verified in browser on both docx and xlsx; `mode: "approximate"` + stable limitation codes (`formatting`, `omitted_features`, `formula_evaluation` for xlsx); truncation flagged separately (status bar "of N×M" + TruncatedFlag); error payloads render Note + keep Download/Refresh actions. No LibreOffice/runtime install prompts anywhere. |
| A26 | pass | 210 tests green: `test_previews.py` (74 — markdown/code/json/csv/table/image/svg/pdf/docx/pptx/xlsx/html/unknown + hostile-zip bounds), `test_artifacts.py`, `test_xlsx_craft.py` (11), `test_docx_craft.py`, `test_artifact_fixtures.py` (38 corpus + malformed-office cases). No regressions to existing formats. |

## W3X scenario results (verified this session)

| ID | Result | Evidence |
|---|---|---|
| A37 | pass | `w3x-xlsx-smoke.xlsx` built via `ArtifactService.create_structured`: fills/fonts/colors, merges-capable styles, alignment, number formats, column widths, freeze panes, auto-filter, native table `RevenueTable` (TableStyleMedium9), native bar+line charts, list DV with prompt/error, two cellIs CF rules — all confirmed in `inspect` features + reopened via openpyxl. |
| A38 | pass | 8 formulas stored as formula cells (`=SUM(B2:D2)` etc.); inspect `formulas: 8`, `formulas_recalculated: false`. Operator opened `w3x-xlsx-smoke.xlsx` in Excel — workbook displays correctly including formulas (2026-11-17). |
| A39 | pass | Upload→adopt→revise path: preflight inventory on load, targeted ops (`set_cell`, `add_chart`, `add_data_validation`) applied as new revision preserving unrelated sheets/features — verified through `revise_structured` on the smoke artifact (revision 2 inspect shows both sheets' features intact). |
| A40 | pass | `test_pivot_parts_block_revise_until_acknowledged` + parametrized drop-category tests (slicers, ActiveX, embeddings, customXml, threadedComments): revise refuses with a clear error until `{"op":"accept_feature_loss"}`; clean workbooks revise without the pseudo-op. External links kept (`keep_links`), VBA preserved byte-for-byte (`keep_vba`), never executed. |
| A41 | pass | Formula cells surface `=…` strings in preview grid and inspect; `formulas_recalculated` is hard-coded `false` (no calculation engine exists); status bar states "formulas not recalculated"; selection stats count only numeric literals — formula cells never contribute fake zeros. |
| A42 | pass | Styled bounded grid verified in browser: merges via colspan/rowspan, freeze panes sticky, col widths, fills/font colors/bold/align, number formats (`12,000`), formula bar, range stats, honest truncation dims, feature badges. Native side: `xl/tables/table1.xml` + `xl/charts/chart1.xml` confirmed in package; operator opened the file in Excel — table, charts, and formulas display/edit correctly (2026-11-17). |

## Automated gates run

- `uv run pytest tests/test_previews.py tests/test_artifacts.py tests/test_xlsx_craft.py tests/test_docx_craft.py tests/test_artifact_fixtures.py` → **210 passed** (21.5s)
- Frontend: `tsc --noEmit` clean; `vitest PreviewPanel.test.tsx` **32 passed**; `npm run lint` 0 errors
- Backend `ruff check`/`format`: clean on touched files

## Browser verification (agent-browser, real app)

- `w3x-xlsx-smoke.xlsx` in Workspace panel: sheet tabs, styled grid (header fill, formatted numbers, formula strings), feature badge, limitation note, zoom controls
- Cell click → formula bar `B2`/`12000`; drag-select → `B2:C3` + `Count: 4 Sum: 44000 Avg: 11000.00`
- `w3-docx-smoke.docx`: document preview + zoom controls present
- 420px viewport: no page-level overflow, all actions reachable
- Console: no errors

## Honest gaps

- **A15 depth**: narrow-layout checked on the document surface; exhaustive keyboard-only traversal of every control on every surface not re-run.
- **Thumbnails**: descoped — no faithful page renders exist to thumbnail (would require the excluded layout engine).
- **HTML deck embed**: descoped — `.deck.json` decks already render natively in-app; no separate HTML player needed.
- W5 visual-inspection loop remains entirely unimplemented (separate workstream).
- W6 packaged-app scenarios (A27–A29) untouched — need release builds.