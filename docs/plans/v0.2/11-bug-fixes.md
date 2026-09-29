# v0.2 Bug Fixes and Hardening (W11)

## Outcome

Known defects found during W3 development are fixed or honestly bounded, with
regression tests. This ticket is a living list — append newly found bugs rather
than filing ad-hoc.

## Dependencies

- 08b MCP OAuth machinery (already built — discovery, DCR, PKCE, token persistence)

## Bugs

### B1 — HTTP MCP servers don't discover OAuth on 401

**Symptom:** adding `{"type": "http", "url": "https://mcp.tradingview.com/mcp"}`
fails with `mcp_connection_failed` + "Server returned an error response".

**Root cause:** OAuth wiring is opt-in via `server.oauth_config` set at creation
(`mcp/registry.py:143`). A server added without it connects with a bare client;
the server's 401 + `WWW-Authenticate: Bearer resource_metadata=...` is treated
as a generic failure, never as "start OAuth". Claude Code et al. treat auth
discovery as part of the transport handshake — minimal config suffices there.

**Fix:**
- On failed HTTP connect (no `oauth_config`), probe `initialize` once; if the
  response is 401 carrying `resource_metadata`, auto-set `oauth_config`
  (default scope, default callback URI) so the server reports
  `auth_type: "oauth"` and the existing Connect-with-OAuth UI appears.
- Notification becomes "requires OAuth — connect via dashboard" instead of
  "Server returned an error response".
- `PATCH /servers/{id}` gains the ability to change `auth_type`/`oauth_config`
  so a misconfigured server is fixable without delete/re-add.

### B2 — Orphaned `pending`/`awaiting_approval` runs never reconciled

**Symptom:** an agent card shows a permanent "running" indicator —
`GET /api/runs?status=pending,running,awaiting_approval` keeps returning a
run that will never execute (observed: a `pending` row on `test-agent`
stuck for two days after a wedged backend).

**Root cause:** startup reconciliation in `main.py` (`_reconcile_runs`)
only swept `status == "running"` → `interrupted`. A run persisted as
`pending` (created but never picked up) or `awaiting_approval` (its
in-memory `RunContext` is gone after a restart, so a later approval can't
resume anything) survives every restart as a zombie.

**Fix (applied, uncommitted):**
- `_reconcile_runs` now sweeps `pending`, `running`, and
  `awaiting_approval` → `interrupted`, keeping the existing
  `run_interrupted` notification.
- Verified live: reload marked the orphan and zero non-terminal rows
  remain; the stale row itself was reconciled manually first.

### B3 — Run cost always `$0.000000` despite recorded tokens

**Symptom:** Traces → agent detail shows every run at `$0.000000` while
the Tokens column has real values (e.g. 12059, 12563). Spend totals and
per-call `model_call.cost` are likewise all zero.

**Root cause:** `litellm_adapter.py:591-600` (sync path) and `:795-804`
(stream path). The priced fallback does:

```python
prompt_cost, completion_cost = litellm.cost_per_token(model=model_str, ...)
```

with `model_str = f"{provider['type']}/{model_name}"` (e.g.
`openai/gpt-6-luna`). `cost_per_token` only resolves names in litellm's
static `model_cost` map; custom/nicknamed models (the `*-luna` ids,
OpenRouter proxies, any free-text name D40 allows) raise — and the
`except Exception: pass` swallows it silently, leaving `cost = 0.0`.
`response.cost`/`stream.cost` attributes that would bypass this are
almost never populated by litellm, so the fallback path is the norm and
cost is always zero for such models.

**Fix:**
- Replace the silent `except` with a per-model warning log (once each):
  "cost tracking unavailable — model {model_str} not in litellm pricing map".
- Resolution chain for pricing: `model_str` → unprefixed `model_name` →
  operator-declared price. The last needs an optional price override —
  e.g. `input_cost_per_mtok`/`output_cost_per_mtok` on the provider's
  model entry (or `provider.config.pricing`), fed into
  `litellm.model_cost`/`register_model` at adapter init so
  `cost_per_token` resolves it.
- UI honesty: persist `cost: float | None` (or a `cost_priced` flag) and
  render "n/a" instead of `$0.000000` when unpriced — `$0` currently
  implies the run was free.

### B4 — `DELETE /api/chat/{agent}/sessions/{id}` returns 500 (FIXED)

**Symptom:** deleting a chat session fails with HTTP 500 for any session
whose runs were executed under W1+ code.

**Root cause:** `api/chat.py:572-601` deletes `messages`,
`audit_records`, `approval_requests`, `elicitation_requests`, then the
`runs` rows — but misses four other run children, all FK'd `NO ACTION`
(SQLite `foreign_keys=ON` per `db_backends/sqlite_backend.py:38`):
`execution_manifests.run_id`, `model_calls.run_id`,
`run_sources.run_id`, and `web_sources` (FK'd on both `message_id` and
`run_id`). W1+ runs always write an `execution_manifests` row and
`model_calls` rows, so nearly every session deletion violates the FK →
IntegrityError → 500. Additionally `messages_fts` (standalone FTS, not
FK'd) keeps stale rows after deletion — orphaned search hits.

**Fix applied:** added `delete_runs(db, run_ids)` in
`services/data_lifecycle.py` — deletes `web_sources`, `messages`,
`audit_records`, `approval_requests`, `elicitation_requests`,
`execution_manifests`, `model_calls`, `run_sources`, then the
`messages_fts` rows (SQLite-only branch — the table doesn't exist on
Postgres), then `runs`. `delete_session` now calls it; the helper is
shared for agent deletion and retention sweeps. Regression test:
`test_chat.py::test_delete_session_removes_full_run_cascade` asserts
every child table + FTS is emptied (test SQLite lacks FK enforcement,
so asserting absence is what catches a missing cascade). Verified live:
session with run+manifest+model_call+sources+FTS row deleted via the
real endpoint → 200, `PRAGMA foreign_key_check` clean.

### B5 — `GET /api/runs/{run_id}` returns 500 (FIXED)

**Symptom:** opening any run in the Traces run-detail page failed with
HTTP 500 for every run carrying an execution manifest.

**Root cause:** W6 regression — `pipeline.py` pins
`skill_revision_ids` as a dict `{skill_name: "rev:<id>" | "live:<hash>"}`
(`manifest.py:69`), but the response model declared
`ManifestOut.skill_revision_ids: list[str]` → Pydantic validation error
on `observability.py:303`. Introduced by the W6 pin-map change; the
response schema was never widened.

**Fix applied:** `ManifestOut.skill_revision_ids` widened to
`dict[str, str] | list[str]` (`observability.py:116`) — covers both the
W6 pin map and any legacy list-shaped rows. Verified live: a manifest
with 17 pins returns 200 with the dict intact; the run-detail page
renders timeline/syscalls/messages. Swept for adjacent failures: zero
NULLs in non-nullable response fields across `runs`/`messages`/
`audit_records`/`model_calls`; `ManifestOut` is constructed only at
`observability.py:303`. Frontend never consumes the field.

### B6 — `GET /api/skills/{id}` returns 500 for rev-pinned skills (FIXED)

**Symptom:** clicking a built-in/global skill card in Skills Studio 500s;
agent-local skills loaded fine.

**Root cause:** W6 bug — the detail endpoint's usage section
(`api/skills.py:518-525`) serializes `r.created_at` on `Run`, but `Run`
has no `created_at` column (`started_at`/`completed_at` only) →
AttributeError → 500. Only fires when the skill has `rev:`-pinned usage
rows; agent-local `live:` pins never match `rev_ids`, so `usage` stayed
empty and those skills loaded — masking the bug in light testing.

**Fix applied:** `r.created_at` → `r.started_at` (`skills.py:522`).
Regression test:
`test_skills_studio.py::test_detail_usage_lists_runs_pinning_revision`.
Verified live: `algorithmic-art` detail → 200 with 11 usage rows.

### B7 — Skill duplicate without an owner agent returns 500 (FIXED)

**Symptom:** `POST /api/skills/{id}/duplicate` with `{"new_name":"copy-of-x"}` returns HTTP 500, despite `owner_agent_id` being optional in the request model.

**Root cause:** the route passes `None` to the duplicate service, which joins that value into the agent workspace path while checking for a name collision; the resulting `TypeError` is not converted to a 4xx response. Reproduced against a published test global skill. Sev-1 per W6 test-plan rule for any 500.

**Fix applied:** `service.duplicate` now supports ownerless duplication — the draft lands in `data/skills-drafts/{name}` (same convention as `create_draft`/`import_draft`) with scope `global`/status `draft`, and the collision loop checks ownerless draft rows + the drafts dir instead of the workspace path. Signature corrected to `owner_agent_id: str | None`. Regression: `test_skills_studio.py::TestW11Regressions::test_duplicate_without_owner_lands_ownerless_draft`.

### B8 — Archived skills remain in the `all` view (FIXED)

**Symptom:** after archiving a published global skill, `GET /api/skills?view=all` and the Skills Studio All view still include it; detail remains accessible as expected.

**Root cause:** the non-drafts list query excludes drafts but does not exclude archived rows.

**Fix applied:** all live views (`all`/`built-in`/`global`/`agent-local`) now exclude `archived` alongside `draft`; a new `?view=archived` lists archived rows so they stay reachable for unarchive/purge, and the Skills page gained an "Archived" tab. Regression: `test_archived_hidden_from_live_views`.

### B9 — Promoting a local skill leaves a live shadow behind (FIXED)

**Symptom:** promotion returns the same skill id with global scope and preserved revision history, but `/effective?agent_id=<owner>` still resolves the old workspace copy as `agent-local` with a `live:` pin and `shadows:["global"]`. Another agent sees the promoted global row with a `rev:` pin.

**Root cause:** publishing an agent-local row to global scope does not remove or retire its live workspace directory; effective resolution intentionally lets that directory win over governed rows.

**Fix applied:** `service.publish` captures the live workspace dir when the target is `global` and the skill is a published `agent-local`, snapshots it into the new revision via `_next_revision`, then removes the dir — the owner then resolves the promoted global row (`rev:` pin) like everyone else. Regression: `test_promote_retires_live_dir` (asserts dir gone + owner resolves `rev:`).

### B10 — Global revisions fail validation against their storage directory name (FIXED)

**Symptom:** validating or republishing a published global skill fails with `name '<skill>' must match directory 'rev-1'` (or the current `rev-N` directory). A second global publish returns 422, blocking the W6 edit/re-publish/restore journey.

**Root cause:** validation compares the skill frontmatter name with the immutable revision directory name rather than the skill name. Reproduced by `GET /api/skills/{id}/validate` and a second `POST /publish` on the test global skill.

**Fix applied:** `validate_skill_dir` gained `expected_name` — `_validate_now` passes `skill.name`, so governed `rev-N` storage dirs check the frontmatter name against the skill row, while unscoped validation (imports, drafts on disk) still enforces name==dirname. Regressions: `test_second_global_publish_revalidates_cleanly` (publish → publish again → rev 2), `test_validate_revision_dir_uses_expected_name`.

### B11 — Skills drawer tabs overflow at the minimum width (FIXED)

**Symptom:** at a 380px drawer width, the tab bar measured 389px scroll width against a 379px client width; the Usage tab extends about 10px beyond the drawer edge and is clipped. No horizontal scroll affordance appears.

**Root cause:** the five-tab flex row does not wrap or enable horizontal scrolling at the minimum drawer width.

**Fix applied:** tab bar is now `overflow-x-auto` with `shrink-0 whitespace-nowrap` buttons — tabs scroll horizontally instead of clipping at narrow drawer widths. Re-verified live 2026-09-28: at a 380px drawer width, `clientWidth=379`, `scrollWidth=401`, and computed `overflow-x=auto`; scrolling to `scrollLeft=22` brought Usage fully inside the visible scroller bounds.

### B12 — Skills toolbar search does not fill its wrapped row (FIXED)

**Symptom:** at a 680px viewport with the sidebar expanded, the search row wraps below the one-line view pills but measures 320px while the row has 376px available, leaving 56px unused. This misses U16's full-width-row expectation.

**Root cause:** not isolated. The search wrapper uses `min-w-[160px] max-w-md flex-1` inside the wrapping toolbar; U16 reproduces the unused row space and the flex sizing needs follow-up.

**Fix applied:** dropped the `max-w-md` cap — the search is `min-w-[160px] flex-1` and now fills whatever its line affords, wrapped or inline. Note: the 320px measurement equals the pre-W6 `max-w-xs` value, so the observed build may have been stale; the uncapped flex rule is correct under either interpretation. Re-verified live 2026-09-28: at a 680px viewport with the sidebar expanded and drawer closed, the available inner row and search input both measured 376px.

### B13 — Markdown resource fragments are treated as part of the file path (FIXED)

**Symptom:** the imported `vercel-react-view-transitions` draft contains `references/css-recipes.md` and `references/patterns.md`, but validation reports missing resources `references/css-recipes.md#reduced-motion` and `references/patterns.md#layout-displacement-morph`.

**Root cause:** the resource-reference regex retains the `#anchor` fragment and validation calls `Path.exists()` on the path-plus-fragment as if it were a filename. Strip the fragment before checking the file path, and validate the heading separately if anchors are part of the contract.

**Fix applied:** the existence check strips `#fragment` via `str.partition("#")` before resolving inside the skill dir; bare `#`-refs are skipped, and the error message still shows the original reference for readability. Anchor-target verification deferred (fragments resolve to headings, not files). Regression: `test_anchor_fragment_refs_resolve`.

### B14 — Promote route accepts global and built-in skills (FIXED)

**Symptom:** `POST /api/skills/{id}/promote` returned HTTP 200 for an already-global skill and for built-in `algorithmic-art`, although A22 expects both to be rejected. Promoting the built-in changed its DB scope to `global` and current revision to 2, removing it from the Built-in view.

**Root cause:** the promote route calls `service.publish(..., scope="global")` without checking the row is `agent-local`; `service.publish` accepts built-ins and global rows.

**Recovery:** this built-in request was a testing mistake; the plan explicitly warned not to attempt it. I stopped and disclosed it, then restored `algorithmic-art` to built-in revision 1 and removed only the test-created rev-2 row/store copy after the user authorized restoration. The shipped source directory and revision-1 hash were verified unchanged.

**Fix applied:** the route now rejects non-`agent-local` rows with HTTP 400 before validating, and calls `service.promote` (which keeps its own scope guard) instead of `service.publish` directly; `promote` gained `availability`/`agent_ids`/`validation` passthrough params so the route keeps its body semantics. Regressions: `test_promote_rejects_global_skill`, `test_promote_rejects_builtin_skill` (both assert 400, scope/`current_revision_id` unchanged, no new SkillRevision). Re-verified live: `POST /promote` on built-in `algorithmic-art` → 400, detail still `scope=built-in`, `current_revision=1`.

### B15 — Skills main pane collapses when a narrow viewport has the drawer open (FIXED)

**Symptom:** at 680×900 with the sidebar expanded and the drawer at its 380px minimum, the main pane measured 60px, its toolbar 64px, and the search remained 160px wide. At the stored 560px drawer width the main pane collapsed to 0px. The full-width search passes at 680px with the drawer closed and at 1280px with the drawer open, but this narrow/open combination is unusable.

**Root cause:** the right-docked drawer is non-shrinking beside the fixed sidebar; the main flex pane can shrink to almost nothing rather than overlaying or clamping the drawer against the remaining viewport width.

**Fix applied:** main pane + drawer now sit in a measured content region (`ResizeObserver` on a `relative flex min-w-0 flex-1` wrapper, measured independent of the docked drawer — no feedback loop). When `contentWidth - drawerWidth < 420` (`MAIN_MIN_WIDTH`) the drawer switches to overlay mode: `absolute inset-y-0 right-0 z-30 shadow-xl`, width `min(drawerWidth, contentWidth)`, main pane keeps the full content width underneath; otherwise it docks exactly as before. Resize handle, the 380/1100/560 width limits, and the `caberos.skillDrawer.width` storage key are unchanged. Re-verified live: at 680×900 + 380px drawer the drawer is `position:absolute` and the main pane keeps ~436px; at 1280×900 the drawer stays docked (`position:relative`) and the grid is unchanged.

### B16 — ZIP import switches to Drafts but lists all skills (FIXED)

**Symptom:** after importing a ZIP on the Skills page, the view pill switches to "Drafts" but the grid still renders every skill — the imported draft is only visible after a manual reload.

**Root cause:** `handleImportResult` called `setView("drafts")` and then awaited the current render's `loadSkills` closure — which still fetched `view=all`. `setView` recreated `loadSkills` (deps `[view, agentFilter, search]`) and the effect fired a second `view=drafts` fetch. The two requests raced; the stale `view=all` response usually resolved last and overwrote the drafts list. `loadSkills` also had no out-of-order guard, so fast search typing could race the same way.

**Fix applied:** `loadSkills` now stamps each call with `++loadSeq.current` and only applies `setSkills`/`setError`/`setLoading(false)` when the sequence is still current — superseded responses are dropped. `handleImportResult` calls `setView("drafts")` only when switching views (the effect then issues the single `view=drafts` fetch) and calls `loadSkills()` directly when already on drafts. Re-verified live: importing a ZIP from the All view issues exactly one post-import `GET /api/skills?view=drafts` and every rendered card is a draft; importing while already on Drafts reloads drafts correctly; a fast `pdf` keystroke burst ends on the final query's result set.

### B17 — `GET /api/elicitation` 500s when a pending elicitation has structured options (FIXED)

**Symptom:** `GET /api/elicitation` returns HTTP 500 whenever any pending elicitation request carries `options` as a list of `{label, description}` objects — which is what `agent_ask_user` actually stores. Reproduced 2026-09-29 with one pending row (run `e07c28f5`, options `[{label, description}]`); the endpoint error disappears only when no structured-options rows are pending. This breaks the frontend's pending-questions surface for the common case.

**Root cause:** `ElicitationOut.options` was declared `list[str] | None` in `backend/src/agentos/api/elicitation.py`, but the mediator normalizes every option — plain strings included — to `{label, description}` objects before persisting (`syscall/mediator.py:848-868`). `json.loads(r.options)` therefore always yields `list[dict]` and the response model fails to serialize (FastAPI ResponseValidationError → 500) for any options-bearing row.

**Fix applied:** added `ElicitationOption` (`label: str`, `description: str = ""`) and widened `ElicitationOut.options` to `list[ElicitationOption | str] | None` (`api/elicitation.py:25-42`), matching the `agent_ask_user` schema union — object rows serialize with their shape preserved and raw-string rows still pass. Swept for adjacent paths: `ElicitationOut` is used only by the list route (`respond` returns a plain dict, no by-id GET exists), so the single serializer covers every read path. Regressions: `test_elicitation.py::test_list_pending_elicitation_preserves_structured_options` (object options round-trip verbatim) and `test_list_pending_elicitation_plain_string_options` (raw-string rows serialize). Verified live: the reproducing row (run `e07c28f5`, four `{label, description}` options) returns 200 with the objects intact.

### B18 — doc-coauthoring: section-by-section flow and reader tests skipped (FIXED)

**Symptom (run `3c7c3d14` + `31f20a56`, real model):** skill loaded via `skills_load` and Stage 1 meta questions were asked with `agent_ask_user` ✅, but the run then ended with a question inline in the final message instead of an elicitation; on reply the whole `auth-module-decision.md` was written in one `write_file` — no proposed structure with `[To be written]` placeholders, no per-section drafting, and **no `run_subagent` reader tests** (Stage 3 absent entirely).

**Suspected cause:** behavioral — the model compressed the three-stage process once it felt it had enough info. The skill text does not forbid single-shot drafting strongly enough to hold under "write it now" pressure.

**Fix applied:** intro now states the three stages run in order and each **Done when** gates the next; Stage 2 gained an explicit "Skeleton first" step — the file is created with all agreed headings + `[To be written]` placeholders before any section prose is written, and "the file never jumps ahead of the conversation"; Stage 3's criterion now requires one `run_subagent` call per predicted question plus the contradiction pass ("reading the document yourself is not a substitute"). Built-ins reseeded at rev 1 with the fix.

**Re-verified (run `9b6683a4`, 2026-09-29):** full process followed — skeleton file with 4 headings + `[To be written]` placeholders written before any prose, sections drafted incrementally across 3 `write_file` passes with elicitation between them, then 10 `run_subagent` calls (two rounds of 4 predicted-question readers + 1 contradiction pass). The subagent *calls* all failed with "Provider openai/anthropic not found" — a separate resolution defect, filed as B21 — and the final message honestly reported the reader check could not complete.

### B19 — frontend-design: plan/critique/screenshot steps skipped (FIXED)

**Symptom (run `01bce87d`, real model):** `skills_load` fired first ✅, but the transcript shows no compact design plan (color/type/layout/signature) written anywhere — not in a message and not as a file — no plan critique pass, and no `browser_open` + `browser_observe(visual)` screenshot of the rendered page (it was never served). Deliverable `roastery-landing.html` was produced in a single `write_file`.

**Suspected cause:** behavioral — same class as B18: the skill's two-pass "plan → critique → build → critique rendered result" process collapses to a single generation step when the model is confident. The HTML itself was on-brief.

**Fix applied:** the process section is now gated steps with a checkable artifact: Step 1 writes the plan (color/type/layout/signature) into `design-plan.md` *before any HTML/CSS exists*; Step 2 is a critique pass that names what was revised; Step 3 builds only from the revised plan; the **Done when** requires the plan artifact + named critique + plan-conformant page. Built-ins reseeded at rev 1 with the fix.

**Re-verified (run `ab2d04ab`, 2026-09-29):** `skills_load` → `write_file design-plan.md` (5 hex colors, 3 type roles, ASCII wireframe, signature) → `terminal ls` → `write_file index.html`. A "Critique and revision" section names the defaults avoided and the changes made. No screenshot pass (page never served — conditional step).

### B20 — browser-workflows: `browser_close` and URL citation skipped (FIXED)

**Symptom (runs `2e20384d`, `c4174c27`, real model):** the observe→act→observe loop with refs worked (click `e7` revealed `SECRET-ORCHARD-42`), but the run ended without `browser_close` — leaving the managed browser session open — and the final answer reported the extracted text without citing the source URL. In run `2e20384d` the plain "summarize" task did not trigger `skills_load` at all (borderline: `web_fetch` was attempted first as required, then escalated legitimately when fetch TLS-failed).

**Suspected cause:** behavioral — teardown/citation steps are the first to drop; also possibly a trigger-description gap for bare "summarize a URL" asks.

**Fix applied:** (a) description rewritten to trigger on the user's ask — "read, summarize, or extract from a URL or web page; operate a site; pull data from a rendered page; test a web app" — since "web_fetch returns empty" was unknowable before trying; (b) a global rule added: every `browser_open` ends in `browser_close`, and extracted content names its URL; per-branch Done-when criteria for read/operate/test now require `browser_close`. Built-ins reseeded at rev 1 with the fix.

**Re-verified (runs `5fe73fb7`, `e91a565a`, 2026-09-29):** bare "summarize this page: <url>" now triggers `skills_load`; `web_fetch` first, `browser_open` only after the TLS failure, and `browser_close` closes the session in both runs; the S5b answer cites `http://localhost:8899/` verbatim.

### B21 — `run_subagent` model override accepts provider *names*, then fails "Provider X not found" (FIXED)

**Symptom (run `9b6683a4`, 2026-09-29):** doc-coauthoring's reader tests issued `run_subagent` with `model: {"provider_id": "openai", "name": "gpt-4.1-mini"}` — all five failed `Provider openai not found`; a retry round with `{"provider_id": "anthropic"}` failed the same way. Provider ids in CaberOS are UUIDs (`providers.id`), not vendor names, so the override never resolves. The subagents work when `model` is omitted (they inherit the parent's model), but nothing tells the model that, and the error gives no hint that omitting `model` would have worked.

**Suspected cause:** the `run_subagent` schema exposes `model.provider_id` without constraining it to configured providers, and the description ("Optional model override. Defaults to the parent's model") doesn't warn against guessing. Two candidate fixes: (a) tool description/schema — tell the model to omit `model` unless it has a real provider id, or validate `provider_id` against configured providers and return a corrective error listing valid ids; (b) resolution — fall back to the parent model when the override's `provider_id` doesn't resolve, and record the fallback in the audit record.

**Fix applied:** combined both, minus silent fallback — `capabilities/tools/subagent.py::_resolve_provider_ref` resolves the override before the sub-agent spawns: a bare provider id wins; a provider *name* or *vendor type* resolves only when exactly one configured provider matches (the guessed-`"openai"` case now works, and the result carries `model_resolved: "openai -> <uuid>"`); zero or ambiguous matches return a corrective error naming the valid `id (name, type)` values and telling the caller to omit `model` to inherit the parent's model. The `model`/`provider_id` schema descriptions now say provider ids are UUIDs and omitting is the common case. Regressions: `test_subagent_isolation.py::TestSubAgentModelOverride` (6 tests — exact id, unique type, name match, ambiguous, unknown, non-string). 721 backend tests pass; live on :8081.

**Re-verified (runs `d566fe28`, `4f1ed406`, 2026-09-29):** the provider-name resolution works end-to-end — a live `run_subagent` with `provider_id: "openai"` resolved to `a4da6653` and returned `model_resolved: "openai -> a4da6653-…"`. The sub-agent still cannot complete a tool-using task: it now dies one layer deeper on `approval_batch` — filed as B22. Note an empty `name` in the override is passed through to litellm verbatim (`The model '' does not exist`) rather than falling back to the parent's model name; whether that needs a fix can ride on B22.

### B22 — `run_subagent` is broken for all tool-using sub-agents: `_SubAgentSyscallHandler.mediate` signature lacks `approval_batch`/`trigger` (FIXED)

**Symptom (runs `4f1ed406` ×6 calls, `d566fe28`, 2026-09-29):** every `run_subagent` whose sub-agent attempts a tool call fails with `sub-agent failed: _SubAgentSyscallHandler.mediate() got an unexpected keyword argument 'approval_batch'`. doc-coauthoring's six reader tests all failed this way; a direct `capabilities: ["read_file"]` probe failed the same way. Repro rate: 100% for tool-using sub-agents.

**Root cause:** `harness/loop.py:660-668` dispatches every tool call via `syscall_handler.mediate(..., approval_batch=…, trigger=…)`. Inside a sub-agent the handler is `_SubAgentSyscallHandler` (`capabilities/tools/subagent.py:318`), whose `mediate` signature still ends at `capability_catalog` — missing `approval_batch` and `trigger`, both added to `SyscallMediator.mediate` (`syscall/mediator.py:65-77`) by the approval-batching work. The wrapper also does not forward either kwarg to `self._parent.mediate`. The B21 unit tests never exercised a sub-agent tool call, so the drift was invisible to them.

**Fix applied:** `_SubAgentSyscallHandler.mediate` now accepts `approval_batch` and `trigger` (same defaults as the mediator) and forwards both — so sub-agent calls keep approval-batching semantics and trigger attribution. Also took the B21 rider: an empty `model.name` in the override now falls back to the parent's model name instead of passing `""` to LiteLLM. Regression: `test_subagent_isolation.py::TestSubAgentWrapperForwarding` — a fake harness drives a real `mediate` call through the wrapper with the loop's kwargs and asserts both reach the parent mediator, with `is_sub_agent`/`sub_agent_id`/parent `run_id` stamped. 13 sub-agent tests pass; ruff clean; backend restarted on :8081.

**Re-verified (runs `0e79f316`, `c47d551d`, 2026-09-29):** end-to-end on `caber`. (a) `run_subagent` with `capabilities: ["read_file"]` — the sub-agent's own `read_file` mediated cleanly, returned `ORCHARD-77`, `status: completed`. (b) override `{"provider_id":"openai","name":""}` resolved the provider (`model_resolved: "openai -> a4da6653-…"`), fell back to the parent's model name, and completed — both previously-broken paths now work. 13 `test_subagent_isolation` tests pass.

## Tests first

- Fake HTTP MCP that 401s with `WWW-Authenticate` → server gains
  `oauth_config`, notification says OAuth-required; PATCH auth_type change.
- `cost_per_token` failing for a custom model name → warning logged once,
  `cost` recorded as unpriced (not `0.0` masquerading as free); a
  provider-declared price override resolves and produces a real cost.

## Done when

- A minimal `{type: http, url}` server that requires OAuth ends up connected
  after one user consent — matching Claude Code behavior.
- No known-bug entries remain without either a fix or an explicit documented
  limitation.
