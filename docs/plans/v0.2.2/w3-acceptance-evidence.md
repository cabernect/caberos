# W3 DOCX Acceptance Evidence

Date: 2026-11-18
Commit: `5ec8e5f` (feat/v0.2.2)
Status vocabulary follows `acceptance-matrix.md`: pass = evidence below;
partial = shipped subset, gap named.

## Scenario Results

| ID | Status | Evidence |
|---|---|---|
| A03 | pass | `tests/test_docx_craft.py` — 41 passed, 1 skipped (2026-11-18): named styles reach Word styles (`test_named_styles_apply_to_docx_styles`), cover block (`test_cover_block_renders_title_page`), styled tables with repeat header + column widths, image height/fit aspect, headers/footers with page-number fields, section breaks, flow-control flags (keep-with-next, page-break-before). |
| A05 | pass (operator-verified) | Operator confirms generated DOCX opens and edits correctly in Microsoft Word — body/heading/table editing, styles intact, save/reopen clean (2026-11-18, desktop-app testing session). |
| A09 | pass | `test_revise_append_blocks_validates_and_preserves`, `test_insert_blocks_after_and_start`, `test_remove_block_paragraph_list_and_table`, `test_set_cell_by_table_block_id`, `test_style_block_formats_runs_and_flags` — targeted ops by stable block id (`test_stable_block_ids_in_inspect_and_revise`), invalid anchors/ids rejected atomically (`test_duplicate_and_invalid_block_ids_rejected`). |
| A07 (DOCX portion) | pass | `test_vietnamese_and_long_text_builds` — Vietnamese diacritics and long text build without silent clipping. |
| A34 (DOCX portion) | pass | `test_named_template_applies_preset_and_records_provenance`, `test_template_override_wins_per_key` — named templates apply with provenance; unsupported spec fields rejected (`test_invalid_specs_rejected`). |

## Automated Gates Run

- `uv run pytest tests/test_docx_craft.py` → 41 passed, 1 skipped (10.9s)

## Notes / Limitations

- Word pagination depends on fonts/application — preview is extracted content,
  labeled approximate; no invented pagination (contract in `03-docx-craft.md`).
- No LibreOffice used anywhere; checks are python-docx byte/structure level plus
  operator-verified Microsoft Word opening.
