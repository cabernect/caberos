# W6 Integrated Acceptance Evidence

Date: 2026-11-18
Commit: `5ec8e5f` (feat/v0.2.2)
Status vocabulary follows `acceptance-matrix.md`.

This file collects cross-cutting scenarios whose coverage already exists as
automated tests plus the packaging/platform items still outstanding. W1–W4
scenario evidence lives in `w2-acceptance-evidence.md`,
`w3-acceptance-evidence.md`, and `w4-acceptance-evidence.md`.

## Cross-Cutting Results

| ID | Status | Evidence |
|---|---|---|
| A06 | pass | Persistent "Limited preview" note on Office previews with `mode: "approximate"` and stable limitation codes (W4 evidence A19); generated artifacts open natively (A04/A05/A42 operator-verified). Differences documented, no layout engine promised. |
| A20 | pass | `tests/test_artifact_fixtures.py::test_malformed_office_preview_errors_are_separate_from_limited_supported_views` (parametrized malformed corpus), hostile-zip bounds in `test_previews.py` (74 preview tests green), symlink/traversal containment: `test_preview_containment_blocks_escape`, `test_workspace_delete_*symlink*`. Deck spec rejects `://` image sources and unknown fields (W2 A32). |
| A21 | pass | VBA preserved byte-for-byte via `keep_vba`, never executed; macro presence surfaced in inspect (`macros` feature flag). External workbook links kept (`keep_links`) without fetching. Deck renderer CSP `default-src 'none'; connect-src 'none'`; spec injected over CDP, never served (W2 A32). |
| A22 | pass | `test_preview_rejects_cross_agent_artifact`, `test_preview_moved_ambiguous_names_still_404`, `test_preview_containment_blocks_escape` — cross-agent/cross-workspace access rejected; unresolved legacy live root never guessed. |

## Platform / Release Items

| ID | Status | Evidence |
|---|---|---|
| A27 | partial | Packaged macOS app exercised continuously during v0.2.2 development (build 2026-11-18): gateway spawn, workspace previews, Reveal in Finder, window-state persistence, external-link routing. **Not yet verified:** fresh-install on a clean account and v0.2.1→v0.2.2 updater path preserving data. |
| A28 | descoped (operator decision 2026-11-18) | No Windows environment available; release notes state macOS Apple Silicon as the validated platform and Windows as unverified — not claimed as tested. |
| A29 | descoped (operator decision 2026-11-18) | Docker runs not exercised; disclosed as unverified in the changelog rather than claimed. |
| A30 | partial | Changelog updated with v0.2.2 entry including supported subsets and known gaps (2026-11-18). Release notes/tag await release approval. |

## Known Non-Gates

- A23–A25 deferred (W5, operator decision).
- A45–A46 descoped (manual editor removed); A44/A47/A49 partials are the
  descoped manual-editing clauses — see W2 evidence.

## Follow-Ups

- [ ] Fresh-install + v0.2.1-update data-preservation check on macOS (procedure below).
- [ ] Windows evidence or release-scope decision.
- [ ] Docker evidence or release-scope decision.
- [ ] Retire or keep ~14 legacy global skills in the packaged app's DB.
- [ ] Release notes naming supported subsets + known gaps (static PPTX,
      approximate Office previews, no in-app recalculation, scripts-disabled HTML).

### A27 verification procedure (macOS)

1. Move any existing `~/Library/Application Support/com.caberos.desktop/` aside (back it up — it holds the packaged DB, workspaces, skills).
2. Install a fresh `CaberOS.app` build, launch, create an artifact, quit.
3. Re-launch — confirm data persists.
4. If testing the updater path: install the previous signed build, let it update, confirm DB/workspaces/skills survive. Requires `TAURI_SIGNING_PRIVATE_KEY` to produce a signed updater bundle first.
