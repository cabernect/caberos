# W3 Test Plan — Results

Executed 2026-09-22 on `feat/v0.2-previews` — backend :8081, frontend :5173, agent `test-agent`, Orca embedded browser for UI sections. Two cases failed on the first pass, were fixed the same day, and re-verified (see **Findings**). **Final verdict: all cases pass.**

## Backend API suite (§2)

| case | result | actual |
|---|---|---|
| A1 | PASS | `kind=markdown` |
| A2 | PASS | `truncated=true`, `total_rows=601`, 500-row cap |
| A3 | PASS | `truncated=true` (250k chars) |
| A4 | PASS | `kind=unknown` |
| A5 | PASS* | 200, `kind=image`, no 500. *Payload carries no `error` field — honesty is client-side (broken `<img>`); no explicit corrupt-image state |
| A6–A9 | PASS | 403 / 403 / 403 (symlink read) / 404 — re-verified post-fix |
| A10 | PASS | artifact meta embedded |
| A11 | PASS | serves rev-1 bytes, `viewing=1`, `newer_exists=true`, `current=2` |
| A12 | PASS | `content-type: text/markdown` |
| A13 | PASS | `image/png` |
| A14 | PASS | 400 non-PDF refused |
| A15 | PASS | dir + children gone on disk |
| A16 | PASS | 409 "tracked as an artifact … remove it from artifact tracking first" |
| A17 | PASS | 409 (dir containing tracked file) |
| A18 | PASS | untracked sibling deleted |
| A19 | PASS | 400 for `""` and `/` |
| A20 | PASS | `DELETE ?path=escape-link` → 200 `{"deleted":true}`; link unlinked, `/etc/hostname` intact. Fix: containment applies to the fully-resolved **parent**, never the leaf (first run: 403 — see Findings) |
| A21 | PASS | 403 — re-verified post-fix |
| A22 | PASS | adopt 200 → delete 409 |
| extra | PASS | bypass probe `DELETE ?path=x/../artifacts/tracked-note.md` → 409 (`..` normalization closed a hole where raw `rel` never matched `current_path`); norm positive `fixtures/../fixtures/probe.txt` → 200 deleted |

## Composer + send suite (§3, Orca browser)

| case | result | actual |
|---|---|---|
| U1 | PASS | AttachmentCard: TXT tile + `w3-sample.txt · 9 B` |
| U2 | PASS | `img[src^="blob:"]`, `naturalWidth=64` |
| U3 | PASS | duplicate skipped — one chip + tray note `"w3-real.png" already attached` |
| U4 | PASS | reorder swapped; removed card's `blob:` URL revoked (fetch fails) |
| U5 | PASS | `naturalWidth` never 0 across 4s poll; `src`: composer `blob:` → `data:` (optimistic) → `blob:` (persisted path) |
| U6 | PASS | new chat → reopen session: card still shows image, `blob:` nw=64 |
| U7 | PASS | PreviewPanel opens `attachments/w3-real.png` |
| U8 | PASS* | card shows `example.com`; click opened `https://example.com/` — via **new browser tab** (`<a target="_blank">`), not in-app panel |
| U9 | PASS | forced `fetch` failure → draft text + attachment retained |

## PreviewPanel + delete suite (§4, Orca browser)

| case | result | actual |
|---|---|---|
| P1 | PASS | rendered `<h1>Hello</h1>`, Rendered/Source tabs |
| P2 | PASS | workspace preview of `big.csv` shows "Showing 499 of 601 rows — download the file for the full contents." under the grid (first run: bare grid, no honesty line — see Findings) |
| P3 | PASS | `attachments/w3-real.png` identical image/blob render from Conversation card and Workspace; `SKILL.md` same MarkdownView in Skills surface |
| P4 | PASS | banner "Viewing revision 1 — revision 2 is current." + View latest; shows v1 bytes |
| P5 | PASS | row gone; `GET /workspace` confirms; disk confirms |
| P6 | PASS | toast `Delete failed: …tracked as an artifact… remove it from artifact tracking first` — no raw JSON |
| P7 | PASS | confirm copy "and everything inside it"; dir + children gone |
| P8 | PASS | deleting open file closed panel, listing refreshed |
| P9 | PASS | skills preview: Download/Rendered/Source only — no Delete/History/Track buttons |
| P10 | PASS | "File not found — It may have been moved or deleted" — no raw 404 |

## Gates (§6) — all pass

Post-fix re-run: `ruff check` clean · `ruff format` clean (197 files) · `pytest` **618/618** (55s — includes 4 new `test_previews.py` cases covering the fix) · `npm lint` 0 errors (9 warnings) · `npm run build` ✓ · `vitest` **33/33**

## Findings — both FIXED same day

1. **A20 — escaping symlink was undeletable (fixed).** First run: `DELETE ?path=escape-link` → 403 `Path outside workspace`; `resolve_within` realpathed the leaf symlink so the link could never be removed via API/UI. Fix in `delete_workspace_entry`: `normpath` the rel path, reject absolute/`..` norms, `validate_path` the parent only, then `parent / basename` — the leaf is unlinked without being followed. Same change closed a hidden bypass: `x/../<tracked-file>` previously skipped the tracked-artifact check; now 409s.
2. **P2 — table truncation was silent (fixed).** First run: 601-row CSV rendered 500 rows with no indication of truncation — `renderers.tsx` dropped `truncated`/`total_rows` for `kind === "table"`. Fix: new `TableView` wraps `GridTable` with "Showing N of M rows — download the file for the full contents."

## State left behind (test-agent)

- `fixtures/notes.md` is a **tracked artifact** (adopted in A22); `artifacts/tracked-note.md` tracked with 2 revisions; `escape-link` removed by the passing A20 re-run; `attachments/` emptied by P10's disk delete; two new chat sessions ("Reply with exactly: ok", "url attachment test").
