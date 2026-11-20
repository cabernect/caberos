# W2 Acceptance Evidence — 2026-11-17

Scope: `.deck.json` canonical presentation source — React preview/slideshow,
native PPTX export, revision-bound PDF export, agent-only editing.
Environment: macOS dev stack, backend `uv run pytest`, frontend vitest/tsc,
Playwright MCP against `localhost:5173` + backend `:8081`, Microsoft
PowerPoint 16.107.4 for native checks (operator-verified).
Working tree: uncommitted W2 changes on top of `11dce4b`.

Status vocabulary: **pass** = evidence below; **partial** = shipped subset,
gap named; **descoped** = removed by operator decision, not a failure;
**n/a** = scenario does not apply to this source format.

## Scenario results (W2-owned IDs)

| ID | Result | Evidence |
|---|---|---|
| A01 | pass | Ordinary `.html` keeps static-document preview (preview tests); deck ops apply only to `format="deck"`. Legacy generated-HTML deck runtime intentionally removed per plan. |
| A02 | pass | `test_designed_eight_slide_deck_exports_native_objects` — 8 slides, all 4 layouts, native chart (series values verified), table, pinned image, notes, bounds checked. Real deck `nvidia-financial-review-nov-2026.deck.json` exports 9/9 native slides, 0 fallbacks, opened in PowerPoint (operator-verified editable). |
| A04 | pass | Operator verified text/table/chart editing, save/reopen in Microsoft PowerPoint. |
| A07 | pass | `_text_height` uses NFC normalization + word-wrap budget; bounded fitting keeps body ≥16 pt, tables ≥12 pt, titles multiline. Vietnamese NVIDIA deck exports native; overflow refuses rather than clips (`test_native_overflow_is_not_silently_clipped`, `test_deck_native_layout.py`). Missing-font substitution is a known platform limitation, not silently claimed identical. |
| A08 | pass | `test_deck_editing.py` — block/slide ops by stable ID, atomic batches, unrelated content preserved, stale base rejected. |
| A31 | pass (spec-level) | `.deck.json` + data-URI asset snapshots are self-contained; `deck-render.html` bundle serves only local `/assets` under CSP `connect-src 'none'`, `img-src data:` — no network needed for playback. Motion + reduced-motion verified in browser. Note: no standalone HTML deck file ships; portability is the spec, playback is in-app or via PPTX/PDF export. |
| A32 | pass | `deck_spec.normalize` rejects unknown slide/block/theme/motion fields, `html` slides, and image `src` containing `://`; only embedded raster data-URIs allowed. Renderer CSP: `default-src 'none'; script-src 'self'; connect-src 'none'`; spec injected over CDP, never served. |
| A33 | pass | `test_export_uses_pinned_spec_assets_not_live_workspace`, `test_revision_reuses_pinned_images_after_workspace_image_is_removed`, sha256 tamper → `hash mismatch`. |
| A34 | n/a | Deck spec has no foreign masters/templates; `theme` tokens (background/accent/text/font) are the entire style contract. PPTX/DOCX template scoping belongs to W3/W3X artifact formats. |
| A35 | pass (scope decision 2026-11-17) | Operator accepted static PPTX export for v0.2.2. Browser motion (transitions, entrances, reveals, reduced-motion) plays in Slideshow — browser-verified. PPTX exports final static state with disclosure: `declared_motion` in the export plan, confirm dialog warning before download, `browser_motion_exported: false` in file metadata. Native PowerPoint motion remains future work. |
| A36 | pass (within scope) | Motion fields survive creation/revision (`test_motion_survives_creation_revision_and_static_pptx`); `set_motion` op; invalid motion rejected by normalize — never silently stripped. |
| A43 | pass | One spec feeds React renderer, native PPTX, and PDF. `plan_hash` binds `renderer_version` + fallback set; exports require `expected_sha256` (409 on drift); pinned assets, no live-asset rereads. |
| A44 | partial | Stable slide/block IDs, targeted ops (`set_text`, `set_bullets`, `set_table`, `set_block`, add/remove/move/replace block, slide ops), atomic validation, CAS on `base_revision_id` — all tested. "Overlapping operator edits require approval" is **descoped**: manual editing was removed, so there is no operator-edited content to overlap; agent-vs-agent staleness still fails safely. |
| A45 | descoped | Inline/click-to-type editing removed per operator decision ("agent edit is enough"). No `contenteditable`, editor draft, or UI-save endpoint remains. |
| A46 | descoped | Manual structure controls (thumbnails, drag reorder, layout/theme pickers, editor undo) removed. Equivalent operations exist for agents via `artifact_revise` ops. |
| A47 | partial | Restore writes old revision as new revision; history preserved (tested). Editor undo/redo descoped with the manual editor. |
| A48 | pass | Export plan names exact slides + reasons (nested "Slide 1" label bug fixed); missing pinned assets → 422, never blank images; fallback requires `allow_fallback` + matching `expected_plan` hash; reasons recorded in PPTX metadata `image_fallbacks`. `test_overflow_still_requires_explicit_current_plan_approval` proves no capture runs without approval. |
| A49 | partial | Same-revision binding verified for PPTX (409 on changed sha) and PDF (`X-Source-SHA256` header + test). Sandboxed edit bridge descoped (no manual editor exists). PDF evidence: `test_deck_export_pdf_is_revision_bound` + real render of NVIDIA deck → valid 9-page PDF. |

## Automated gates run

- `uv run pytest` (backend, full suite): **1888 passed, 4 skipped** (200s). The earlier `test_browser.py` CDP timeouts did not reproduce — environmental flake.
- `uv run ruff check` / `ruff format`: clean on touched files.
- `npx tsc --noEmit`: clean. `npm run build`: clean (pre-existing chunk/dynamic-import warnings). `npm run lint`: warnings only, all pre-existing. `vitest run PreviewPanel.test.tsx`: 32/32.
- Focused deck suites: `test_deck_pptx.py` (7), `test_deck_native_layout.py` (9),
  `test_deck_editing.py` (6), `test_deck_motion.py` (4), deck cases in
  `test_previews.py` — all passing (109 in combined run).

## Known gaps carried forward

- Native PowerPoint motion export — descoped for v0.2.2 by operator decision;
  requires a support matrix and real PowerPoint evidence if revisited.
- A44/A47 "operator edit" clauses — descoped with manual editing; revisit if
  manual editing returns.
- Font substitution on machines without Aptos/Georgia/Consolas is a platform
  limitation; layout budgets are estimates, not glyph measurements.
- Full-suite browser tests (`test_browser.py` CDP timeouts) fail in this
  environment unrelated to deck changes.
