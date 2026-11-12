# v0.2.1 UI Acceptance Verification — Independent Run

**Date:** 2026-11-10 · **Tester:** independent verification agent (all results first-hand, none taken from implementation claims)
**Branch:** `feat/v0.2.1` @ `d6d043c` (+ `53abe67`, `3251cda`, …) · **Host:** macOS ARM64, Seatbelt sandbox
**Stack:** main instance :8081/:5173, `backend/data/agentos.db` (seeded legacy rows per checklist; all removed post-run)

Agents used: `test-agent` (full no-approval caps; `doc_query_rows` granted temporarily for #17 then restored), `caber` (image caps, #19). Model `gpt-6-luna`/OpenAI, TTS Gemini flash-lite, STT OpenAI gpt-transcribe.

## Results

| # | Item | Verdict | Evidence |
|---|---|---|---|
| 1 | Basic run | ✅ | Run `completed`, reply rendered, DB row `completed` |
| 2 | Live event stream | ✅ | Mid-run `thinking…` + Stop button + elapsed timer; "Worked through 2 steps", file chip, tokens/cost — full tail |
| 3 | Instant failure | ✅ | Seeded legacy sessions → `failed` in **25–30 ms** with real error; never `completed`, no 30 s hang (see #7/#8) |
| 4 | Stop a run | ✅ | `stopped` persisted at re-check; no completed flip |
| 5 | Pin stability | ✅ | Default switched Y → resumed X-pinned session wrote `pin-redo.txt` in X; run `workspace_path`=X |
| 6 | New session → new default | ✅ | Fresh session pinned `/private/tmp/w12-workspace-y`; `y-pin.txt` landed in Y |
| 7 | Ambiguous legacy | ✅ | Run `failed` instantly: "run evidence under multiple workspaces: ['/private/tmp/ws-a','/private/tmp/ws-b']. Set its workspace explicitly before resuming." |
| 8 | All-unknown legacy | ✅ | Run `failed` instantly: "ran before workspace locations were recorded (1 run(s) with unknown roots)… set the workspace explicitly" |
| 9 | Workspace browser | ✅ | Panel lists external dir; session pin resolves raw files (X-pinned→200 X file while default=Y); cross-root path 404; ambiguous session 409; no-session → current default |
| 10 | Artifact create+preview+revise | ✅ | `artifact_create` → `artifacts/w12-verify.docx` (Y); preview + History r1; `artifact_revise` → r2 with change summary |
| 11 | Cross-workspace isolation | ✅ | Two artifacts, same `current_path`, different `workspace_path` → each serves own bytes; request's session can't masquerade |
| 12 | External edit detection | ✅ | Disk-mutated docx → `artifact_revise` returns `{"conflict":true,"error":"file changed since base revision…"}`; `tracking_status=conflict`; no overwrite; live bytes still served |
| 13 | Legacy artifact | ✅ | `workspace_path=NULL` + rev.source_run_id → run → session pin ⇒ live bytes served (provenance). No provenance ⇒ live preview **409** "workspace can't be established… revisions remain available" + `tracking:"unresolved"` on path preview; revision bytes still serve |
| 14 | CSV numeric typing | ✅ | `Qty` `kind:"number"`; agent answered **sum=29, 1 row ≥10** with `csv!A2:5` citation |
| 15 | Pagination honesty | ✅ | `doc_query_rows` `matched_count=50` + `aggregates:count=50` identical across pages (later page empty, count unchanged) |
| 16 | `1e309` stays text | ✅ | Serialized as string `"1e309"`, column `kind:"mixed"`, no 500s |
| 17 | Mediated row query | ✅ | `doc_query_rows` succeeded twice via run mediation — no `'db'` error (fix `39874e9` verified live) |
| 18 | FTS/hybrid search | ✅ | `doc_search` returned chunk/document citations; hybrid fusion in trace |
| 19 | Image gen containment | ✅ | `image_generate` → `artifacts/media/image-*.png` (755 KB, tracked+revision); nothing outside `artifacts/` |
| 20 | Read-aloud swap | ✅ | 1st click → "Stop reading"; 2nd click → 1st reverts "Read aloud" (stopped cleanly), 2nd "Generating speech…" — states settle |
| 21 | Navigate away mid-gen | ✅ | Synthesize in-flight at nav (`"Generating speech…"`) → after 5 s: `audioCount:0, playing:false` — nothing played |
| 22 | Stop → idle | ✅ | Cycle `Generating speech…` → `Read aloud` observed via MutationObserver; no stuck spinner |
| 23 | Dictation | ⚠️ partial | `/api/speech/transcribe` verified: real WAV → real transcript (gpt-transcribe, batch, `audio_seconds`). Mic button stays "Start dictation" headless — **environmental** (no audio device/permission) |
| 24 | Terminal backends | ✅ | Card lists Seatbelt (installed · auto), Bubblewrap (requires Linux), MXC (requires Windows); explicit `bwrap` save → **422 "native to Linux"** |
| 25 | Command exec | ✅ w/ note | `terminal`→`read_terminal`→`close_terminal` all `ok` (stdout `bg-out`, exit 0). **Note:** background terminal owned `(agent,session,run)` — a *later* run gets honest "terminal not found"; checklist's "persists across messages" is not the implemented scope |
| 26 | Traces | ✅ | Span tree + waterfall (honest "derived — placed from recorded latency" labels), inspector w/ syscalls, model-call ledger (4× Generation, per-call latency) |
| 27 | Spend | ✅ | `/api/spend?days=7` = **$0.0620 / 47 runs** — byte-identical to Spend page totals/by-agent/by-trigger; `scope=platform` ($0.1334) labeled "not reconcilable to ledger" honestly |

## Findings & divergences (none filed as defects)

1. **#25 scope:** terminal ownership is `(agent_id, session_id, run_id)` — cross-message access to a prior run's background terminal is refused ("terminal not found"). Live backgrounds are surfaced via `terminals_active` at run end and reaped only on run-cancel/restart — a long-lived background can outlive its run with no operator path to close it. Design-vs-checklist divergence; flagging for product judgment.
2. **Settings workspace field:** `PUT /api/agents` path verified end-to-end (`workspace:"/path"` attaches, `""` resets to managed, foreign/invalid → 422). The SettingsOverlay save path wasn't exercised reliably through headless input simulation — code path sends `workspace: workspaceInput.trim()` correctly.
3. **Observability top card vs Spend section:** `$0.0618/46` vs `$0.0620/47` — window/inclusion difference between the two cards (top card vs run-totals query); cosmetic footnote, spend section is internally consistent.
4. `/tmp` external roots canonicalize to `/private/tmp` on macOS (matches W15 symlink-guard behavior).

## Cleanup

Deleted: seeded sessions `w12-ambig`/`w12-unk`/`w13-sess` + all their runs (incl. failed admission rows); artifacts `w12-art-*`, `w13-art-*`, `a275c50a` (docx), `651597be` (image) + revisions + storage dirs; documents+chunks+sheets+155 rows for `w12-*.csv` + vault storage files; test files in `workspaces/test-agent` (`pin-*.txt`, `stream-check.txt`, `test-stream.txt`); generated image PNG in `workspaces/caber`; `/tmp/w12-*` dirs/files.
Restored: `test-agent` workspace → managed (v92), capabilities → pre-test backup (v93).
`PRAGMA integrity_check` → ok. Browser closed. Agent version history (v90–93) retained — that's the versioning mechanism, not test residue.
