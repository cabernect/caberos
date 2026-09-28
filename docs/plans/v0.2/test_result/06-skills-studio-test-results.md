# W6 Test Results — Skills Studio

**Initial run:** 2026-09-28  
**Post-fix retest:** 2026-09-28  
**Branch / base commit:** `feat/v0.2-skills` / `5b16268`; the coding-agent fixes tested below were uncommitted working-tree changes.  
**Environment:** macOS; backend `127.0.0.1:8081`; frontend `localhost:5173`; initial real-provider runs used `gpt-5.6-luna`.

## Latest verdict

**Post-fix regression verdict: B7–B13 PASS.** The seven findings were rechecked against the current working tree using focused backend tests, authenticated live API calls, and Playwright layout checks. Relevant backend/frontend gates are now green.

**Scope limit:** this remains a focused retest, not a replay of every W6 case. A second live check exercised global revision history: test skill `3b24d117-72ed-47da-9b44-d686c98efb97` (`w6-r3-restore-retest-1790578322747`) published rev 1, republished rev 2, then restored rev 1 as rev 3; detail returned history `[3, 2, 1]` and rev 3's content hash matched rev 1. The test skill was deleted with HTTP 200. The bytes were unchanged between publishes, so this verifies the global restore leg but does not exercise the content-edit step of R3. The detailed case history below retains initial evidence while showing current disposition for rechecked findings; untouched PASS rows refer to the initial run only. Not every W6 case was independently repeated after the fixes.

## Post-fix regression results — 2026-09-28

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
| Focused W6 backend tests | PASS | `test_skills_v6.py`, `test_skills_api.py`, `test_skills_loader.py`: **40 passed**; rerun after the additional R3 check: **40 passed in 8.05s**. |
| Full backend suite | PASS | `uv run pytest -q`: **702 passed, 21 warnings**. |
| Ruff | PASS | `ruff check src/ tests/` clean; `ruff format --check src/ tests/`: **215 files already formatted**. |
| Frontend gates | PASS | `npx tsc -b`; `npm run lint` (0 errors, 9 warnings); `npm test` (**33/33**); `npm run build` all passed. Build retained dynamic-import/chunk-size warnings. |
| Browser console | PASS | Fresh post-retest console check returned **0 errors**. |

**Cleanup / final state:** all test-created skills and drafts were deleted; authenticated searches for `w6-` returned zero rows in All, Global, Agent Skills, Drafts, and Archived. Scratch agent `d26b139d` remains disabled. Browser viewport is 1280×900, detail drawer is closed, and stored drawer width is restored to 560px. Backend health returned `{"status":"ok"}` and frontend returned HTTP 200. This retest made no product-source edits; the fixes remain uncommitted working-tree changes.

## Detailed case history — initial evidence and current disposition

Entries marked `RESOLVED ON RETEST` passed the current post-fix checks summarized above; the evidence text on those rows describes the initial pre-fix observation. `PARTIAL` marks journeys not fully replayed. Other `PASS` rows are initial-run results and were not all independently repeated after the fixes.

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
| A16 validation follow-up | RESOLVED ON RETEST | Initial run: validation falsely reported the two existing reference files missing because their `#anchor` fragments were treated as filenames (B13). Post-fix live re-import/validate returned HTTP 200 with `errors=[]`. |
| A17 | PASS | GitHub URL and `/tree/main` forms returned the same 9 candidate names. Archive path prefixes differed appropriately (`HEAD` vs `main`). |
| A18 | PASS | FTP, junk URL, and valid ZIP without `SKILL.md` each returned 400; draft set was unchanged. |
| A19 | PASS | `deploy-to-vercel` published globally as rev 1 and appeared in effective resolution with a `rev:` pin. |
| A20 | PASS | Missing `description` blocked publish with 422 and a validation error. |
| A21 | PASS | Agent-local publish without owner returned 400; with the scratch owner it published and resolved with a `live:` pin. |
| A22 | RESOLVED ON RETEST | Initial run: promotion left a live local shadow and the global attempt hit the B10 validation bug. Post-fix live promotion verified the owner's effective skill becomes global with a `rev:` pin and no shadows; full repo journey R2 is marked partial below. Built-in promotion remained untested for safety. |
| A23 | RESOLVED ON RETEST | Initial run: the exact ownerless duplicate request returned HTTP 500 (Sev-1). Post-fix live request returned HTTP 200, created a draft, and was cleaned up (B7). |
| A24 | PASS | Local `restore-probe` published rev 1, republished rev 2, then restored rev 1 as rev 3. History contained 1/2/3 and rev-1 bytes exactly matched rev-3 bytes. |
| A25 | PASS | Disabling the test global skill removed it from effective resolution; re-enabling restored `published`. |
| A26 | RESOLVED ON RETEST | Initial run: archive left the skill in `view=all`. Post-fix, it was hidden from All, visible in Archived, detail remained accessible, and the UI Archived tab showed a test skill (B8). |
| A27 | PASS | Purging a still-published global skill returned 409 with `archive or disable the skill before purging`. |
| A28 | PASS | Built-in purge returned 400; the built-in row remained present. |
| A29 | PASS | Test global and agent-local skills were archived and purged; store revision directories and the agent-local workspace directory were removed. |
| A30 | PASS | Attempting to disable a draft returned 400 with the draft lifecycle guard message. |
| A31 | PASS | Scratch agent's local `algorithmic-art` shadow won over the built-in; `agent-builder` still saw the built-in. Real-agent chat checks confirmed both versions. |
| A32 | PASS | Unauthenticated skills request returned 401. |

## 2. Repository gates

| Gate | Result | Evidence |
|---|---|---|
| B1 targeted skills suite | PASS | `test_skills_v6.py`, `test_skills_api.py`, `test_skills_loader.py`: **34 passed**. |
| B2 full backend suite | PASS | `uv run pytest`: **696 passed, 21 warnings**. |
| B3 TypeScript | PASS | `npx tsc -b` completed cleanly. |
| Ruff check | RESOLVED ON RETEST | Initial run found UP035 at `backend/src/agentos/services/data_lifecycle.py:5`; the post-fix Ruff check now passes cleanly. |
| Ruff format check | RESOLVED ON RETEST | Initial run requested formatting in `test_skills_v6.py`; the post-fix format check passes, with 215 files already formatted. |
| Frontend build | PASS | `npm run build` passed; Vite emitted dynamic-import and large-chunk warnings. |
| Frontend lint | PASS | Exit 0, 0 errors, 9 warnings. |
| Frontend unit tests | RESOLVED ON RETEST | Initial run 32/33; post-fix run 33/33 passed. `SettingsOverlay.test.tsx` expected `database is busy`, but the UI displayed `Could not save capability settings; please retry.` |

## 3. Skills Studio UI

UI cases were exercised with Playwright MCP after the user authorized closing the process holding its isolated MCP profile. No personal browser profile was touched.

| Case | Result | Actual result / evidence |
|---|---|---|
| U1 | PASS | All/Built-in/Global/Agent Skills/Drafts refiltered; observed 17 built-ins, 2 globals, 5 agent-local rows before filtering, and draft-only cards. Cards showed scope/revision/resource counts. |
| U2 | PASS | Search filtered live to zero results for a missing name; clearing restored the draft list. |
| U3 | PASS | Agent Skills dropdown filtered to `skills-test`; only its four live/published local rows appeared. |
| U4 | PASS | Built-in detail drawer opened with `built-in · rev 1` and Overview/Instructions/Resources/History/Usage tabs. |
| U5 | PASS | Overview showed description, scope, status, revision, license, and validation warnings with warning-tinted styling. |
| U6 | PASS | Markdown rendered headings, bold, inline code, and five code blocks. Copy buttons appeared on hover; code block background used the tool surface. |
| U7 | PASS | FPT resource tree showed 5 files, including four PNGs; `fpt_logo.png` opened as an image preview. |
| U8 | PASS | `restore-probe` History listed rev 3 current, rev 2, then rev 1 with Restore actions. |
| U9 | PASS | Built-in Usage displayed 12 completed runs without a 500. |
| U10 | PASS | Built-in showed Export/Disable/Archive and no Purge; local showed Promote and status actions, with Purge after Archive; draft showed Publish/Delete, with Publish disabled on validation errors. |
| U11 | PASS | Publish dialog exposed global/agent-local scope, owner picker, all/selected availability, selected-agent checkboxes, and change summary. Validation errors were shown and blocked publish. |
| U12 | PASS | UI ZIP upload created `fpt-slide-generator-en` as a draft and showed an import notice. |
| U13 | PASS | UI repo URL picker showed 9 candidates; selecting only `vercel-react-view-transitions` imported exactly one draft. Initial validation follow-up found B13. Post-fix live import and validation passed with no anchor-fragment errors (see B13 above). |
| U14 | PASS | Create Skill UI made `ui-builder-probe` for `skills-test`, linked builder session `602de710-ccf9-488f-9000-36e81c154c70`, and navigated to that chat. |
| U15 | PASS | Drawer resized to 380px and 1100px at a 1600px viewport; width persisted after close/reopen and reload. Original 560px preference was restored afterward. |
| U16 | RESOLVED ON RETEST | Initial run measured 320px with 376px available. Post-fix Playwright recheck at 680px measured the wrapped search at the full 376px row width. |
| U17 | PASS | Grid reflowed from one 412px column with the drawer open to two 294px columns after collapsing the sidebar; no squeezed three-column layout. |
| U18 | PASS | `viewer.html` preview used the sidebar tone and inner code used the surface tone; light-mode measurements matched `--sidebar`/`--surface`. |
| U19 | PASS | Dark mode applied across list, drawer tabs, preview, and Create/Publish dialogs. Measured list, drawer, preview, and Create-modal surfaces had readable contrast and no white slabs. Theme was restored to light. |
| U20 | RESOLVED ON RETEST | Initial run measured `scrollWidth=389px` versus `clientWidth=379px` with no scroll affordance. Post-fix Playwright verified `overflow-x=auto`; scrolling to the 22px maximum brought Usage fully inside the tab scroller. |
| U21 | PASS | Importing a valid ZIP without `SKILL.md` displayed `Import failed: no SKILL.md found in the archive`, with a dismiss button and no raw stack. The expected HTTP 400 appeared as a browser network console message. |

## 4. Real-world lifecycle journeys

| Journey | Result | Actual result / evidence |
|---|---|---|
| R1 ZIP → publish-local → use | PASS | Run `32e4c2d6-c996-44ca-a398-7bc4af4dfdf5` completed; agent listed `fpt-slide-generator-en`; manifest pinned it `live:`. Its test session was later deleted under R7. |
| R2 repo import → promote | PARTIAL | Initial run reproduced B9's local-shadow behavior. Post-fix live promotion of a test-owned agent-local skill returned revision 2 and changed effective resolution to global/`rev:` with no shadows; the full two-skill repository journey was not repeated. See B9 above. |
| R3 edit → republish → restore | PARTIAL | Initial run's second global publish returned 422 (B10). Post-fix global republish reached rev 2 and the restore endpoint returned rev 3 with rev1/rev3 hashes matching. No content edit was made between publishes, so the edit step remains unverified. |
| R4 shadowing | PASS | Scratch chat run `954fb5a3-9a15-4c6e-8d50-4d46f2218abb` quoted the local shadow description; `agent-builder` run `aad8db94-d736-4267-9e56-12d055b210a1` quoted the built-in description. Manifests recorded `live:` vs `rev:` pins. |
| R5 builder flow | PASS | Builder run `dfffbcf8-bffd-4df2-9ffa-909809046ef7` force-loaded `skill-creator` (`rev:`), wrote a valid Celsius-to-Fahrenheit SKILL.md, and operator publish created rev 1 linked to the builder session. |
| R6 disable/purge honesty | PASS | Run `27bc1631-ec5d-4cfc-aae3-39f0d2b501dc` manifest pinned `active-pin-test` as `rev:e01b6c65-57d1-44c8-9f7a-1ce68f502ada`. While awaiting the exact `sleep 25` terminal approval, archive succeeded and purge returned 409. After the run completed, purge returned 200. Only the matching agent/run approval was decided. |
| R7 session delete cleanup | PASS | Deleting R1's test session returned 200; it disappeared from the session list and its run detail returned 404. An unrelated R4 run detail remained 200. |
| R8 export → re-import | PASS | FPT rev-1 export re-imported as a draft; all 5 file byte sequences matched the export. The round-trip draft was then deleted. |

## 5. Findings and cleanup

Confirmed defects B7–B13 were appended to `docs/plans/v0.2/11-bug-fixes.md`:

- B7: duplicate without `owner_agent_id` returns 500 (Sev-1).
- B8: archived skills remain in All.
- B9: promotion leaves a live local shadow.
- B10: validation compares global skill names with `rev-N` storage-directory names.
- B11: tabs overflow at the 380px drawer minimum.
- B12: wrapped Skills search does not fill the available row.
- B13: resource validation treats Markdown `#anchor` fragments as part of a file path.

Cleanup removed only this run's test skills and drafts, removed the test-created promotion shadow directory, and disabled scratch agent `d26b139d`. Verification showed no scratch local skills, no test drafts, and no test globals. The pre-existing local skill and other agents were untouched. Test run records for R4/R5/R6 and the UI builder session remain for audit; R1's session was deleted as required by R7. Backend health remained `ok`, frontend returned HTTP 200, theme is `light`, and drawer width is 560px.

The W6 test-plan file remains unmodified and untracked. The coding agent's product-source fixes are uncommitted working-tree changes; this verification pass did not edit product source and created no commit.
