# W6 Test Plan — Skills Studio

**Audience:** an agent executor. Every case has an exact command + a
machine-checkable assertion. Branch under test: `feat/v0.2-skills`.

**What W6 added:** governed skills — `Skill`/`SkillRevision`/`SkillAssignment`
models, startup reconcile (seeds built-ins, migrates legacy dirs, indexes
agent-local workspace dirs), effective resolution with precedence
`agent-local > global > built-in`, per-run revision pinning in execution
manifests (`{name: "rev:<id>" | "live:<sha256>"}`), builder-mode sessions,
hardened ZIP/repo-URL imports (incl. GitHub `owner/repo` shorthand),
validate/publish/promote/duplicate/restore/disable/archive/purge lifecycle,
and the React Skills Studio UI.

**Fixtures:**
- `data/fpt-slide-generator-en.zip` — single-skill zip → draft
  `fpt-slide-generator-en`, SKILL.md + 4 PNG assets under `assets/`.
- `vercel-labs/agent-skills` — GitHub repo shorthand, multi-skill repo →
  candidate pick-list.
- A scratch agent for publish-local / builder / effective-resolution cases
  (create once in setup, reuse `$AGENT`).

---

## 0. Setup

```bash
cd backend
uv run uvicorn agentos.main:app --port 8081 &
# wait for: curl -s http://127.0.0.1:8081/health → {"status":"ok"}

TOKEN=$(curl -s -X POST http://127.0.0.1:8081/api/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"<operator>","password":"<password>"}' | python3 -c 'import json,sys;print(json.load(sys.stdin)["session_token"])')
H="Authorization: Bearer $TOKEN"
API=http://127.0.0.1:8081/api/skills
```

Scratch agent (reuse the operator's configured provider_id/model):

```bash
curl -s -X POST http://127.0.0.1:8081/api/agents -H "$H" \
  -H 'Content-Type: application/json' \
  -d '{"name":"skills-test","provider_id":"<pid>","model_name":"<model>",
       "task":"You test the skills system."}'
# → {"id": "<AGENT>"}
```

Fetch skills the skills suite relies on:

```bash
# built-in id for later cases
BUILTIN=$(curl -s "$API?view=built-in" -H "$H" | python3 -c \
  'import json,sys;print(json.load(sys.stdin)["skills"][0]["id"])')
```

---

## 1. Operator API (deterministic — no model needed)

| #   | case                                    | command                                                                                          | expect |
| --- | --------------------------------------- | ------------------------------------------------------------------------------------------------ | ------ |
| A1  | list all                                | `curl -s "$API" -H "$H"`                                                                          | `count` ≥ 17; every row has `id,name,description,scope,status,current_revision,resource_count`; no `status:"draft"` rows |
| A2  | view filters                            | `?view=built-in`, `?view=global`, `?view=agent-local`, `?view=drafts`                              | each returns only its scope/status; `?view=nope` → 400 |
| A3  | search                                  | `?view=all&q=art`                                                                                 | only names containing `art` (case-insensitive) |
| A4  | agent filter                            | `?view=agent-local&agent_id=$AGENT`                                                                | only `owner_agent_id == $AGENT` |
| A5  | effective resolution                    | `curl -s "$API/effective?agent_id=$AGENT" -H "$H"`                                                 | `skills[]` each with `name,scope,pin`; governed rows pin `rev:<uuid>`, agent-local live dirs pin `live:<sha256>` |
| A6  | detail                                  | `GET $API/$BUILTIN`                                                                               | `revisions[]` non-empty w/ `revision_number,content_hash,is_current`; `validation`; `usage[]`; `body` non-empty |
| A7  | files + preview + raw                   | `GET $API/$BUILTIN/files` → pick `SKILL.md`; `GET .../preview?path=SKILL.md`; `GET .../raw?path=SKILL.md` | files list has `path,size,mime`; preview returns classified kind (`markdown`); raw returns bytes; `?path=../x` → 403 |
| A8  | validate                                | `GET $API/$BUILTIN/validate`                                                                      | `errors`/`warnings` arrays; built-ins may warn (missing license) but must not error |
| A9  | export                                  | `curl -sOJ "$API/$BUILTIN/export" -H "$H"`                                                        | zip downloads, `filename="<name>-rev<N>.zip"`, unzips to real content; `?revision=1` exports that rev |
| A10 | create draft                            | `POST $API/drafts {"name":"api-test-draft"}`                                                       | draft row appears under `?view=drafts`, **absent** from `?view=all` |
| A11 | draft name validation                   | `POST .../drafts {"name":"Bad Name!"}`                                                             | 400 — lowercase/hyphens only; duplicate name → 409 |
| A12 | delete draft                            | `DELETE $API/drafts/<id>`                                                                          | `{"deleted":true}`; gone from `?view=drafts` |
| A13 | ZIP import                              | `curl -s -X POST $API/import -H "$H" -F "file=@../data/fpt-slide-generator-en.zip"`                | `{"imported":[{"name":"fpt-slide-generator-en",...}],"errors":[]}` — single-skill zip auto-imports (no pick-list) |
| A14 | imported draft is complete              | `GET $API/<id>/files` on the imported draft                                                        | `assets/*.png` ×4 + `SKILL.md` present; preview of a PNG returns `image` kind |
| A15 | repo shorthand pick-list                | `POST $API/import-url {"url":"vercel-labs/agent-skills"}`                                          | `candidates[]` lists every SKILL.md dir in the repo; `imported:[]` — multi-skill → no auto-import |
| A16 | import selected candidates              | `POST $API/import-url {"url":"vercel-labs/agent-skills","paths":["<cand1>","<cand2>"]}`            | `imported` has exactly the selected skills as drafts; unselected candidates not imported |
| A17 | URL forms                               | repeat `import-url` with `https://github.com/vercel-labs/agent-skills` and a `/tree/main` URL      | all accepted — same candidates payload as A15 |
| A18 | import rejects non-https / junk         | `{"url":"ftp://x"}` / `{"url":"not a url"}` / zip without SKILL.md                                  | 400 with clear detail; nothing lands in drafts |
| A19 | publish draft → global                  | `POST $API/<id>/publish {"scope":"global","availability":"all","change_summary":"v1"}`             | `{"published":true,"revision":1}`; detail `current_revision:1`; appears in `?view=global` and `/effective` for `$AGENT` as `rev:` pin |
| A20 | validation gates publish                | create draft via API with a SKILL.md missing `description` → publish                                | 422 `{"message":"validation failed","errors":[…]}` — errors block, warnings don't |
| A21 | publish-local (agent-local snapshot)    | `POST $API/<id>/publish {"scope":"agent-local","owner_agent_id":"$AGENT"}`                         | draft becomes published agent-local owned by `$AGENT`; `?view=agent-local&agent_id=$AGENT` shows it; publish without `owner_agent_id` → 400 |
| A22 | promote agent-local → global            | `POST $API/<id>/promote {"availability":"all","change_summary":"promote"}`                         | `{"promoted":true,"revision":<n>}` — **same skill id**, scope becomes global, history preserved; promoting a built-in/global → error |
| A23 | duplicate                               | `POST $API/<id>/duplicate {"new_name":"copy-of-x"}`                                                | new `status:"draft"` named `copy-of-x` with copied content; lands in `?view=drafts` |
| A24 | restore-as-new-revision                 | publish a second rev (edit → publish), then `POST .../restore {"revision_number":1}`               | `{"restored":true,"revision":3}` — current rev = 3 whose content matches rev 1; history keeps 1,2,3 |
| A25 | disable                                 | `POST $API/<id>/status {"status":"disabled"}`                                                      | `status:"disabled"`; drops out of `/effective`; `POST .../status {"status":"published"}` re-enables |
| A26 | archive                                 | `{"status":"archived"}`                                                                            | `status:"archived"`; hidden from `?view=all` but still in detail by id |
| A27 | purge guard — not archived              | `DELETE $API/<id>` on a `published` skill                                                          | 409 "archive or disable first" |
| A28 | purge guard — built-in                  | `DELETE $API/$BUILTIN`                                                                             | 400 "built-in skills cannot be purged" (button must also be absent/hidden in UI — U-check) |
| A29 | purge happy path                        | archive a global skill → `DELETE`                                                                  | `{"deleted":true}`; `data/skills-store/<id>/` gone; agent-local purge also removes `workspaces/<agent>/skills/<name>/` |
| A30 | draft lifecycle guards                  | `POST .../status {"status":"disabled"}` on a draft                                                  | 400 — drafts can only be deleted, not disabled/archived |
| A31 | effective shadowing                     | create agent-local skill with the **same name** as a global/built-in → `/effective?agent_id=$AGENT` | the agent-local entry wins; the shadowed row reports `shadows` (or is excluded per API shape — document actual) |
| A32 | unauthenticated                         | any of the above without `-H "$H"`                                                                 | 401/403 — never 200 |

---

## 2. Suite gate

| #   | case                                                             | expect |
| --- | ---------------------------------------------------------------- | ------ |
| B1  | `cd backend && uv run pytest tests/test_skills_v6.py tests/test_skills_api.py tests/test_skills_loader.py -v` | all pass (25 + 10 + loader cases at time of writing) |
| B2  | `uv run pytest`                                                  | full suite green — no collateral regressions |
| B3  | `cd frontend && npx tsc -b`                                      | clean |

---

## 3. UI cases — `http://localhost:5173/skills`

| #   | case                                    | steps                                                                                  | expect |
| --- | --------------------------------------- | -------------------------------------------------------------------------------------- | ------ |
| U1  | views + cards                           | click All / Built-in / Global / Agent Skills / Drafts                                  | card grid refilters; scope badge + `rev N` + resource count on each card; draft cards only under Drafts |
| U2  | search                                  | type in search box                                                                     | grid filters live; clearing restores |
| U3  | agent filter                            | Agent Skills view → agent dropdown                                                     | only that owner's skills |
| U4  | detail drawer                           | click a built-in card                                                                  | drawer opens: name, `built-in · rev N`, tabs Overview / Instructions / Resources / History / Usage |
| U5  | Overview tab                            | —                                                                                      | description, scope, status, revision, availability, license, validation warnings (amber banner) |
| U6  | Instructions tab                        | —                                                                                      | SKILL.md renders as styled markdown — headings, bold, inline-code chips, code blocks on `--tool-bg` surface, copy button inside block's top-right on hover |
| U7  | Resources tab                           | open a skill with assets (e.g. `fpt-slide-generator-en` draft after A13)               | collapsible file tree; clicking a file opens the preview panel; PNGs render as images |
| U8  | History tab                             | on a multi-revision skill                                                              | revision list newest-first, `current` marker, restore action on old revs |
| U9  | Usage tab                               | on a built-in pinned by runs (e.g. `algorithmic-art`)                                  | run list w/ status + timestamp; **must not 500** (B6 regression) |
| U10 | action gating                           | check buttons per scope                                                                | built-in: Export/Disable/Archive only (no Purge/Duplicate-into... verify actual); agent-local: + Promote/Purge; draft: Publish/Delete |
| U11 | publish dialog                          | draft → Publish                                                                        | dialog offers scope (global / agent-local), owner picker when agent-local, availability + assignment, change summary; validation errors block with messages |
| U12 | Import .zip                             | header → Import .zip → pick `data/fpt-slide-generator-en.zip`                          | lands in Drafts; toast/notice; no auto-publish |
| U13 | From URL                                | header → From URL → enter `vercel-labs/agent-skills`                                   | pick-list dialog of detected skills; selecting subset imports only those as drafts |
| U14 | Create Skill → builder                  | header → Create Skill → pick agent                                                     | creates draft + opens a builder session (dashboard_chat) on that agent; session is flagged builder-mode — `skill-creator` force-loads on next run |
| U15 | resizable drawer                        | drag the drawer's left edge                                                            | width follows pointer 380–1100px, accent line on hover/drag, `cursor: col-resize`, width persists across close/reopen + reload |
| U16 | toolbar wrap                            | with drawer open / narrow content                                                      | pill tabs stay one line (no mid-word wrap); search drops to a full-width row below pills |
| U17 | card grid reflow                        | open/close drawer, collapse sidebar                                                    | grid columns follow container width (`auto-fill`), never squeezed 3-col |
| U18 | preview panel                           | Resources → open `viewer.html`/any code file                                           | docked preview on `var(--sidebar)` tone, not bright white; inner code blocks on `--surface` |
| U19 | dark mode                               | toggle dark → sweep list, drawer, all tabs, dialogs, preview                           | no white slabs, readable contrast, borders/accents consistent |
| U20 | narrow drawer content                   | drag drawer to ~380px min                                                              | drawer content stays usable — tabs scroll or fit, no clipped text |
| U21 | error normalization                       | trigger a failure (e.g. import a non-skill zip via UI)                                 | error banner/notice shows the API `detail` message, dismissible, no raw stack |

---

## 4. Real-world E2E — full lifecycle journeys

| #   | journey                                | steps                                                                                                             | pass = |
| --- | -------------------------------------- | ----------------------------------------------------------------------------------------------------------------- | ------ |
| R1  | **zip → draft → publish-local → use**  | Import `fpt-slide-generator-en.zip` (U12) → publish as agent-local to `$AGENT` (A21) → run a chat on `$AGENT`: "what skills do you have?" | Agent lists `fpt-slide-generator-en`; `GET /api/runs/<run>` manifest pins it `live:` or `rev:`; run detail page opens (B5 regression) |
| R2  | **repo import → promote**              | Import 2 skills from `vercel-labs/agent-skills` (U13) → publish one global (A19) → promote the other agent-local→global (A22) | Both end as published global skills with revision history; `/effective` pins them `rev:` |
| R3  | **edit → re-publish → restore**        | Edit a published global skill's draft (duplicate → edit → publish rev 2) → restore rev 1 (A24)                     | Current content = rev 1's bytes, at rev 3; History tab shows 3 revisions |
| R4  | **shadowing**                          | Agent-local same-name skill vs built-in → chat on that agent + on another agent                                    | Test agent sees the agent-local version; other agents see the built-in — precedence only applies per-owner |
| R5  | **builder flow**                       | Create Skill → builder session → ask it to draft a tiny skill → publish                                             | Draft written under `skill-drafts/`; publish produces rev 1; `builder_session_id` links the session |
| R6  | **disable mid-run honesty**            | Pin a skill in a run (manifest) → archive it → try purge (A29)                                                     | Purge blocked while an *active* run pins it (409); after run settles, purge proceeds |
| R7  | **session delete cleanup**             | Delete the chat session that pinned skills (B4)                                                                    | DELETE 200; no FK errors; Traces unaffected |
| R8  | **export → re-import round-trip**      | Export a skill rev (A9) → re-import the zip (A13)                                                                  | Re-imported draft content matches exported bytes |

---

## Cleanup

```bash
# purge test skills (archive first), delete drafts, delete scratch agent
for id in <imported/draft ids>; do
  curl -s -X POST $API/$id/status -H "$H" -d '{"status":"archived"}' -H 'Content-Type: application/json'
  curl -s -X DELETE $API/$id -H "$H"
done
# scratch agent has no DELETE endpoint — disable it instead:
curl -s -X PATCH http://127.0.0.1:8081/api/agents/$AGENT -H "$H" \
  -H 'Content-Type: application/json' -d '{"enabled":false}'
```

## Notes for the executor

- **Drafts are inert** — nothing scans `data/skills-drafts/`; a draft never
  reaches a run until published. Verify by checking `/effective` excludes them.
- **`live:` vs `rev:`** — agent-local skills pin by content hash until
  promoted; that's expected, not a missing revision.
- **Multi-skill repos never auto-import** — the candidates pick-list is the
  intended gate; selecting nothing imports nothing.
- A **run manifest pin** (`skill_revision_ids`) is written once at run start —
  mid-run publishes don't wobble the run.
- Report format: case id → PASS/FAIL + evidence (curl output, screenshot
  path, run_id). Any 500 = sev-1 FAIL; append new findings to
  `docs/plans/v0.2/11-bug-fixes.md` rather than filing elsewhere.
