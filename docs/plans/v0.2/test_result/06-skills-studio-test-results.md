# W6 Test Results — Skills Studio

**Initial run:** 2026-09-28  
**Full W6 rerun:** 2026-09-28
**Post-fix retest round 2 (B14/B15):** 2026-09-28
**Branch / tested code:** `feat/v0.2-skills`; initial baseline `5b16268`, post-fix commit tested `0a2ca9c` (`W6 test-run fixes: B7-B13 + regression tests`), plus uncommitted B14/B15 fixes on top.
**Environment:** macOS; backend `127.0.0.1:8081`; frontend `localhost:5173`; initial real-provider runs used `gpt-5.6-luna`. Round-2 UI verification used the Orca embedded browser plus Playwright MCP for the literal 680×900/1280×900 viewport cases.

## Post-fix retest round 2 — 2026-09-28

**Verdict: PASSING.** Both open defects verified fixed live; neighbouring cases and all gates re-run clean. UI was exercised through the Orca embedded browser (1078×845 CSS px) for overlay mechanics and Playwright MCP at the literal plan viewports (680×900 and 1280×900), authenticated with the app's existing session cookie.

| Case | Result | Evidence |
|---|---|---|
| B14 promote guard — global | PASS | `POST /promote` on freshly published global `w6-rt2-global` returned **400** `only agent-local skills can be promoted`. Detail unchanged: `scope=global`, `current_revision=1`, history `[1]`. |
| B14 promote guard — built-in | PASS | `POST /promote` on `algorithmic-art` returned **400** with the same message; detail unchanged at `scope=built-in`, `current_revision=1`, history `[1]`. |
| A22 positive path | PASS | `w6-rt2-local` published agent-local rev1 on scratch agent `a55dd839`, promoted → 200 `{promoted:true, revision:2}`, same id, history `[2,1]`, owner cleared; effective resolution `rev:e450938b…`, `shadows=[]`. |
| R2 repo import → promote | PASS | Imported 3 candidates from `vercel-labs/agent-skills`; `vercel-react-view-transitions` published global rev1, `deploy-to-vercel` published local then promoted rev2 — both resolve `rev:` with no shadows. (`vercel-composition-patterns` publish was correctly blocked with 422 `frontmatter 'description' missing` — upstream skill lacks the field; consistent with A20.) |
| B15 — 680×900, expanded, drawer 380 | PASS | Playwright literal viewport: drawer `position:absolute` overlay at 380px, main pane keeps 440px, search fills its row (376/376). |
| B15 — 680×900, expanded, drawer 560 | PASS | Playwright literal viewport: overlay capped at `min(560,440)=440px`, main pane 440px unchanged. |
| B15 — overlay when cramped (Orca) | PASS | At the Orca viewport (1078px, expanded sidebar): drawer `position:absolute`, main pane keeps full 838px content width. Search input fills its row (531/531px). |
| B15 — width cap (Orca) | PASS | Stored drawer width 1100 with content width 838: overlay renders at `min(1100,838)=838px`; main pane unchanged. |
| B15 — docked when roomy | PASS | Playwright 1280×900 + drawer 560: docked `position:relative`, main 480px, 1 column expanded; collapsed sidebar → main 672px, 2 columns. Orca: 380px drawer docked in both sidebar states. |
| B15 — clean switching | PASS | Real window resize with drawer open (Playwright): 680→1280 flips overlay→docked (`absolute`→`relative`, main 440→660); 1280→680 flips back (main 632 full width). Sidebar toggling at 1078 (Orca) switches the same way — no stuck layout. |
| B15 — overlay interactions | PASS | Drag handle resized 560→640 via real mouse events while overlay; close button dismissed the drawer; clicking an uncovered card (`claude-api`, x≈343 < overlay edge 438) switched the drawer's skill. |
| U15 resize + persistence | PASS | Drag persisted `caberos.skillDrawer.width=640`; value survived reload. |
| U17 grid reflow | PASS | 1 column at 458px main (expanded+docked), 2 columns at 650px (collapsed+docked); 3 columns under overlay at 838px. |
| U19 dark overlay | PASS | Dark theme: overlay keeps `shadow-xl` (real shadow layers `rgba(0,0,0,0.1) 0 20px 25px -5px` + `0 8px 10px -6px` render over `rgb(21,24,17)` surface) and `1px solid` left border. |
| U20 tab scroll at 380 | PASS | `clientWidth=379`, `scrollWidth=401`, `overflow-x=auto`; `scrollLeft=22` brings Usage fully visible (1066 ≤ 1078). |

**Viewport note:** the literal 680×900 and 1280×900 scenarios above were verified in Playwright MCP after the initial Orca pass; the Orca rows are retained as corroborating evidence at a different viewport. The 420px threshold constant was independently bracketed in Orca (overlay at gaps of 278px and 390px; docked at 458px/470px/650px).

| Gate | Result |
|---|---|
| `test_skills_studio.py` + `test_skills_api.py` + `test_skills_loader.py` | PASS — **40 passed** (19.35s) |
| Full backend suite | PASS — **702 passed, 21 warnings** |
| `ruff check` + `ruff format --check` | PASS — clean; 216 files formatted |
| `npx tsc -b` | PASS |
| `npm run lint` | PASS — 0 errors, 9 warnings |
| `npm test` | PASS — **33/33** |
| `npm run build` | PASS — dynamic-import/chunk-size warnings only |
| Browser console | PASS — 0 errors after restore |

**Cleanup:** all round-2 test skills purged (archive → delete, HTTP 200 each); no `w6-rt2`/vercel test dirs remain in `data/`. Scratch agent `a55dd839` (`w6-rt2-test`) was deleted from the DB after a backup (1 agent row + 1 AgentVersion; no home/workspace dirs were ever created) — `integrity_check` ok, zero remaining references. UI restored: theme light, drawer width 560, drawer closed, sidebar expanded.

## Full W6 rerun — 2026-09-28

**Verdict: NOT FULLY PASSING.** I exercised the full operator API set (A1–A32), repository gates, UI cases (U1–U21), and lifecycle journeys (R1–R8) against the current working tree.

| Area | Result | Current evidence |
|---|---|---|
| A1–A21, A23–A32 | PASS | Live assertions passed, including imports, validation/publish, lifecycle, archive/purge, shadowing, auth, and export. A22's negative guard is separated below. |
| A22 local promotion | PASS | Same skill ID/history preserved; owner changed from `live:` to global `rev:` with no local shadow. |
| A22 global/built-in guard | FAIL → resolved in round 2 (B14) | `/promote` on a global test skill returned 200. I also mistakenly called `/promote` on built-in `algorithmic-art` despite the plan warning; it returned 200 and changed DB scope/current revision. I restored it to built-in rev 1 and removed only the test-created rev-2 row/store copy; shipped bytes and rev-1 hash match. |
| U1–U15, U17–U21 | PASS | Views, search, agent filter, drawer/tabs, resources/previews, lifecycle dialogs, imports, builder launch, resizing, grid reflow, dark theme, narrow tab scrolling, and error dismissal were exercised. |
| U16 narrow viewport with drawer open | FAIL → resolved in round 2 (B15) | At 680×900 with a 380px drawer, main pane was 60px, toolbar 64px, and search 160px. Search fills 376px with drawer closed at 680px and 416px when drawer is open at 1280px. |
| R1–R8 | PASS | Fresh live-provider runs, promotion, edited revision/restore, builder flow, active-run purge guard, session deletion, and ZIP byte round-trip are detailed below. |
| Repository gates | PASS | Targeted W6 40/40; full backend 702 passed (21 warnings); Ruff check/format; TypeScript; lint (0 errors/9 warnings); Vitest 33/33; production build. |

**Cleanup:** test-created skills, drafts, runs/sessions, approvals, notification rows, workspace files, and W6 Playwright captures were removed. With explicit user approval, the scratch agent `skills-test` (`d26b139d`) was deleted directly from the DB (the API has no agent-delete endpoint): 1 agent row, 1 AgentVersion, 1 chat Contact, 5 memory triples, and 6 session-summary FTS rows, in one transaction after a DB backup. A full-table scan then found no references and `integrity_check` returned `ok`. Its home directory (only a test-extracted `MEMORY.md`) was moved to `/tmp`. `GET /api/agents/d26b139d` now returns 404. The app is healthy; theme is light and drawer preference is restored to 560px.

## Earlier focused post-fix retest — 2026-09-28 (historical)

| Finding / gate | Result | Retest evidence |
|---|---|---|
| B7 — ownerless duplicate | PASS | Authenticated live `POST /api/skills/{id}/duplicate` omitted `owner_agent_id`: HTTP 200, returned `status=draft`, and appeared in Drafts. Test skill `7bccf272-58ea-45bb-aef3-07221e9d12f4` (`w6-retest-1790577662066`) was deleted with HTTP 200. |
| B8 — archived listing | PASS | That live test skill archived with HTTP 200; it disappeared from `view=all`, appeared in `view=archived`, and detail remained HTTP 200. A separate test skill appeared in the UI Archived tab and disappeared after cleanup. Both test skills were purged with HTTP 200. |
| B9 — local promotion shadow | PASS | Live promotion for scratch agent `d26b139d` returned HTTP 200/revision 2. Effective resolution changed from `agent-local` with `live:` to `global` with `rev:4ca795cc-3d5d-4444-8206-ee8064a93344`, `shadows=[]`; detail retained revisions `[2, 1]`. Test skill purge returned HTTP 200. |
| B10 — global revision validation | PASS | Live global duplicate published as revision 1; `/validate` returned HTTP 200 with `errors=[]`; a second publish returned HTTP 200/revision 2. The test skill was purged with HTTP 200. |
| R3 — global restore leg | PASS (partial) | Live API published rev 1, republished rev 2, restored rev 1 as rev 3; history `[3, 2, 1]`, rev 3 content hash matched rev 1, and cleanup returned HTTP 200. No content edit was made between publishes. |
| B11 — narrow drawer tabs | PASS | Playwright at 1280×900 with drawer width 380px: tab scroller `clientWidth=379`, `scrollWidth=401`, `overflow-x=auto`; at `scrollLeft=22`, Usage was fully within the scroller bounds. |
| B12 — wrapped search width | PASS | Playwright at 680×900, sidebar expanded and drawer closed: toolbar inner row width was 376px and the wrapped search input measured 376px. |
| B13 — Markdown anchor references | PASS | Imported `vercel-react-view-transitions` from `vercel-labs/agent-skills`; `/validate` returned HTTP 200 with no errors, including no `#anchor` missing-file errors. The imported draft was deleted with HTTP 200. |
| Focused W6 backend tests | PASS | `test_skills_studio.py`, `test_skills_api.py`, `test_skills_loader.py`: **40 passed**; rerun after the additional R3 check: **40 passed in 8.05s**. |
| Full backend suite | PASS | `uv run pytest -q`: **702 passed, 21 warnings**. |
| Ruff | PASS | `ruff check src/ tests/` clean; `ruff format --check src/ tests/`: **215 files already formatted**. |
| Frontend gates | PASS | `npx tsc -b`; `npm run lint` (0 errors, 9 warnings); `npm test` (**33/33**); `npm run build` all passed. Build retained dynamic-import/chunk-size warnings. |
| Browser console | PASS | Fresh post-retest console check returned **0 errors**. |

**Cleanup / final state:** all test-created skills and drafts were deleted; authenticated searches for `w6-` returned zero rows in All, Global, Agent Skills, Drafts, and Archived. Scratch agent `d26b139d` remains disabled. Browser viewport is 1280×900, detail drawer is closed, and stored drawer width is restored to 560px. Backend health returned `{"status":"ok"}` and frontend returned HTTP 200. That focused retest made no product-source edits. The coding-agent fixes were subsequently committed as `0a2ca9c`.

## Detailed case results — full rerun, 2026-09-28

The result cells below reflect the full rerun; the earlier targeted retest section above is retained only as historical evidence.

## 1. Operator API

| Case | Result | Actual result / evidence |
|---|---|---|
| A1 | PASS | `GET /api/skills` returned 18 rows initially (17 built-ins plus one pre-existing agent-local skill); required fields present and no drafts in the live view. |
| A2 | PASS | Built-in 17, global 0, agent-local 1, drafts 0; unknown view returned 400. |
| A3 | PASS | `q=art` returned only `algorithmic-art` and `web-artifacts-builder`. |
| A4 | PASS | Scratch-agent filter returned only rows owned by `d26b139d`; initially zero rows. |
| A5 | PASS | Effective menu returned 17 built-ins with `rev:` pins. Later live local fixture pins were `live:` as expected. |
| A6 | PASS | `algorithmic-art` detail returned a non-empty body, revision metadata, validation, and usage; usage endpoint remained HTTP 200. |
| A7 | PASS | `SKILL.md` listed and previewed as Markdown; raw returned bytes; `../x` preview was blocked with 403. |
| A8 | PASS | Built-in validation returned `errors: []` and one warning. |
| A9 | PASS | Current and revision-1 exports were valid ZIPs containing `SKILL.md`; corrected case-insensitive header check confirmed `algorithmic-art-rev1.zip`. The first harness assertion falsely failed because it read response headers case-sensitively. |
| A10 | PASS | `api-test-draft` appeared in Drafts and not All. |
| A11 | PASS | Invalid name returned 400; duplicate draft name returned 409. |
| A12 | PASS | Test draft deletion returned 200 and subsequent detail returned 404. |
| A13 | PASS | ZIP import auto-imported `fpt-slide-generator-en` as a draft with no errors. |
| A14 | PASS | Imported draft contained `SKILL.md` and four PNG assets; PNG preview returned `kind: image`. |
| A15 | PASS | Repo shorthand produced 9 candidates and imported nothing automatically. |
| A16 | PASS | Exactly the selected `deploy-to-vercel` and `vercel-react-best-practices` candidates imported as drafts. |
| A16 validation follow-up | PASS | Initial run falsely reported existing reference files missing because `#anchor` fragments were treated as filenames (B13). Full rerun re-import/validate returned HTTP 200 with `errors=[]`. |
| A17 | PASS | GitHub URL and `/tree/main` forms returned the same 9 candidate names. Archive path prefixes differed appropriately (`HEAD` vs `main`). |
| A18 | PASS | FTP, junk URL, and valid ZIP without `SKILL.md` each returned 400; draft set was unchanged. |
| A19 | PASS | `deploy-to-vercel` published globally as rev 1 and appeared in effective resolution with a `rev:` pin. |
| A20 | PASS | Missing `description` blocked publish with 422 and a validation error. |
| A21 | PASS | Agent-local publish without owner returned 400; with the scratch owner it published and resolved with a `live:` pin. |
| A22 | FAIL → resolved in round 2 (B14) | Agent-local→global promotion succeeded with the same ID/history and owner `rev:`/no-shadow resolution. The negative guard failed: promoting a global test row returned HTTP 200. I mistakenly also tried the built-in probe despite the plan warning; it returned HTTP 200 and moved `algorithmic-art` to global rev 2. The row was restored to built-in rev 1; the test-created rev-2 row/store copy was removed, and the original hash was verified. See B14. |
| A23 | PASS | Initial run's ownerless duplicate returned HTTP 500 (B7); full rerun returned HTTP 200 with a draft, which was then deleted. |
| A24 | PASS | Full edit/restore cycle on a test-owned local skill: rev 1 was edited in the live workspace, published globally as rev 2 with a different hash, then revision 1 was restored as rev 3. History was `[3, 2, 1]`; rev 3 matched rev 1 and differed from rev 2. Test skill was purged. |
| A25 | PASS | Disabling the test global skill removed it from effective resolution; re-enabling restored `published`. |
| A26 | PASS | Initial run left archived skills in All (B8); full rerun hid the archived test skill from All, listed it in Archived, and kept detail accessible. The UI Archived tab showed it. |
| A27 | PASS | Purging a still-published global skill returned 409 with `archive or disable the skill before purging`. |
| A28 | PASS | After restoring `algorithmic-art` to built-in rev1, built-in purge returned 400 and detail remained 200 with scope `built-in`. |
| A29 | PASS | Test global and agent-local skills were archived and purged; store revision directories and the agent-local workspace directory were removed. |
| A30 | PASS | Attempting to disable a draft returned 400 with the draft lifecycle guard message. |
| A31 | PASS | `skills-test` resolved the test-local `algorithmic-art` with a `live:` pin and quoted `LOCAL-W6-SHADOW-MARKER`; `agent-builder` resolved built-in `rev:019c6e8c-fc06-4ef4-b647-233267c3a854` and said that marker was absent. Runs `df1f8b45-a68d-4b4c-8a16-42e712ce601c` and `dc1d2316-6102-4afc-81c8-16acc237600e`. |
| A32 | PASS | Unauthenticated skills request returned 401. |

## 2. Repository gates

| Gate | Result | Evidence |
|---|---|---|
| B1 targeted skills suite | PASS | `test_skills_studio.py`, `test_skills_api.py`, `test_skills_loader.py`: **40 passed**. |
| B2 full backend suite | PASS | `uv run pytest -q`: **702 passed, 21 warnings**. |
| B3 TypeScript | PASS | `npx tsc -b` completed cleanly. |
| Ruff check | PASS | Full rerun `uv run ruff check src/ tests/`: clean. |
| Ruff format check | PASS | Full rerun `uv run ruff format --check src/ tests/`: 215 files already formatted. |
| Frontend build | PASS | `npm run build` passed; Vite emitted dynamic-import and large-chunk warnings. |
| Frontend lint | PASS | Exit 0, 0 errors, 9 warnings. |
| Frontend unit tests | PASS | Full rerun: **33/33 passed**; the prior error-message case now uses an `ApiError` mock. |

## 3. Skills Studio UI

UI cases were exercised with Playwright MCP after the user authorized closing the process holding its isolated MCP profile. No personal browser profile was touched.

| Case | Result | Actual result / evidence |
|---|---|---|
| U1 | PASS | All/Built-in/Global/Agent Skills/Drafts/Archived refiltered. Full-run baseline showed 17 built-ins, 1 global, and 3 agent-local cards; Drafts and Archived filtered separately. Cards showed scope/revision/resource counts. |
| U2 | PASS | Search filtered live to zero results for a missing name; clearing restored the draft list. |
| U3 | PASS | Agent Skills dropdown filtered to `skills-test`; the two test-owned live local rows appeared. |
| U4 | PASS | Built-in detail drawer opened with `built-in · rev 1` and Overview/Instructions/Resources/History/Usage tabs. |
| U5 | PASS | Overview showed description, scope, status, revision, license, and validation warnings with warning-tinted styling. |
| U6 | PASS | Markdown rendered headings, bold, inline code, and five code blocks. Copy buttons appeared on hover; code block background used the tool surface. |
| U7 | PASS | FPT resource tree showed 5 files, including four PNGs; `fpt_logo.png` opened as an image preview. |
| U8 | PASS | `w6-full-builder-r5-20260928` History listed rev 3 current, rev 2, then rev 1, with Restore actions on prior revisions. |
| U9 | PASS | Built-in `algorithmic-art` Usage displayed 13 completed runs; no 500. |
| U10 | PASS | Built-in showed Export/Disable/Archive and no Purge; published local showed Promote to global plus status actions; archived local showed Export/Purge; valid draft showed Publish/Delete, and invalid draft Publish was disabled. |
| U11 | PASS | Publish dialog exposed global/agent-local scope, owner picker, all/selected availability, selected-agent checkboxes, and change summary. Validation errors were shown and blocked publish. |
| U12 | PASS | UI ZIP upload created `fpt-slide-generator-en` as a draft and showed an import notice. |
| U13 | PASS | UI repo picker showed 9 candidates; selecting only `deploy-to-vercel` and `vercel-react-best-practices` imported exactly two drafts, used in R2. B13's selected candidate also imported and validated without anchor-fragment errors. |
| U14 | PASS | Create Skill UI created `w6-full-builder-r5-20260928` on `skills-test`, opened builder session `dea6a0a2-d024-4ad9-bdc6-bab23cb7a400`, and navigated to chat; the builder session was flagged on the skill row. |
| U15 | PASS | Real drag events resized the drawer to 380px and 1100px at 1600px; 1100px persisted after reload. Original 560px preference was restored. |
| U16 | FAIL → resolved in round 2 (B15) | Search filled the row at 680px with drawer closed (376px) and at 1280px with drawer open (416px). At 680×900 with drawer 380px and sidebar expanded, the main pane collapsed to 60px, toolbar to 64px, and search stayed 160px; see B15. |
| U17 | PASS | At 1280px: 4 columns with drawer closed, 1 column with expanded sidebar + drawer, and 2 columns (294px each) after collapsing sidebar with drawer open; no squeezed 3-column layout. |
| U18 | PASS | `viewer.html` preview matched `--sidebar` and inner code matched `--surface` in light and dark modes (dark: `rgb(29,33,25)` / `rgb(21,24,17)`). |
| U19 | PASS | Dark mode was swept across list, Overview/Instructions/Resources/History/Usage, code preview, and Create/Publish dialogs; zero white-background nodes in drawer. Theme was restored to light. |
| U20 | PASS | At the 380px drawer minimum, tab scroller `clientWidth=379`, `scrollWidth=401`, `overflow-x=auto`; scrolling 22px brought Usage fully inside the visible scroller. |
| U21 | PASS | Importing ZIP without `SKILL.md` displayed the exact API detail `Import failed: no SKILL.md found in the archive`; dismiss button worked, no draft was created, and the expected HTTP 400 was the only fresh console error. |

## 4. Real-world lifecycle journeys

| Journey | Result | Actual result / evidence |
|---|---|---|
| R1 ZIP → publish-local → use | PASS | Run `0fe4ed7d-eaee-4e2a-a8b6-95e8519dca06` completed; assistant listed `fpt-slide-generator-en`, manifest pinned it `live:299fe07e…`, and `/traces/d26b139d/0fe4ed7d-eaee-4e2a-a8b6-95e8519dca06` rendered the run detail. Session was deleted after verification. |
| R2 repo import → promote | PASS | UI imported exactly `deploy-to-vercel` and `vercel-react-best-practices`; first published global rev1, second published local then promoted as rev2 on the same ID. Owner and AgentBuilder both resolved the promoted skill with `rev:`; owner had no shadows. Both skills were purged. |
| R3 edit → republish → restore | PASS | Test skill `w6-full-r3-1790580156548` published local rev1, its live SKILL.md was edited, then published globally as rev2 with a different hash. Restoring rev1 created rev3; history `[3, 2, 1]`, rev3 hash matched rev1 and differed from rev2. Skill was purged. |
| R4 shadowing | PASS | Run `df1f8b45-a68d-4b4c-8a16-42e712ce601c` on `skills-test` returned `LOCAL-W6-SHADOW-MARKER` with a `live:` pin. Run `dc1d2316-6102-4afc-81c8-16acc237600e` on AgentBuilder said the marker was absent and pinned built-in `algorithmic-art` as `rev:019c6e8c…`. Test sessions were deleted. |
| R5 builder flow | PASS | UI created skill `w6-full-builder-r5-20260928` and builder session `dea6a0a2-d024-4ad9-bdc6-bab23cb7a400`. Runs `845a9e12-…` and `5a4a92fe-…` force-loaded `skill-creator`; the corrected root SKILL.md validated and publishing created rev1 linked to the builder session. Test skill/session were removed. |
| R6 disable/purge honesty | PASS | Run `354bd0b9-a590-484c-affc-25704cf1c6bb` pinned `w6-full-r6-1790580008929` as `rev:dcc7affd…`. Archive returned 200; while the exact `d26b139d`/run approval for terminal `sleep 25` was pending, purge returned 409. Only that approval (`41e73192-…`) was approved; after completion purge returned 200. |
| R7 session delete cleanup | PASS | Deleting R1 session `fb1158ba-de68-4450-85aa-c3f03d04afd7` returned 200; the session disappeared and run detail returned 404. Unrelated R4 run detail `dc1d2316-6102-4afc-81c8-16acc237600e` returned 200 at the check. |
| R8 export → re-import | PASS | FPT rev1 export was re-imported through the API; all 5 source/draft file paths and byte sequences matched. Round-trip draft deletion returned 200. |

## 5. Findings and cleanup

B7–B15 are recorded in `docs/plans/v0.2/11-bug-fixes.md`:

- B7–B13: fixed defects; all passed the post-fix checks.
- B14: `/promote` accepts already-global and built-in skills — FIXED; verified in retest round 2 (400 + unchanged scope/revision/history; positive path and R2 re-verified).
- B15: narrow viewport plus open drawer collapses the Skills main pane — FIXED; verified in retest round 2 (overlay mode keeps the main pane at full content width; see viewport caveat above).

Cleanup removed test-created skills/drafts/runs/sessions, test notifications, W6 Playwright captures, and generated workspace files. API checks show no W6 skills/drafts, no `d26b139d` sessions or approvals, and no test notification rows. The scratch workspace is gone. The `skills-test` agent and all its residual DB data (1 agent, 1 AgentVersion, 1 Contact, 5 memory triples, 6 session-summary FTS rows) were then deleted directly from the DB with explicit user approval, since the application has no agent-delete endpoint. No references remain, and the agent's API lookup returns 404. The built-in `algorithmic-art` row remains built-in rev1 with its original bytes/hash. Pre-existing skills and other agents were preserved. Backend health is `ok`, frontend returns HTTP 200, theme is `light`, and drawer width is 560px.

The W6 test-plan file is tracked and unmodified. This verification changed no product source and created no commit. The W6 report and W11 findings are modified by this run; `docs/plans/v0.2/07-rag-v2.md` is also modified in the worktree and was left untouched.
