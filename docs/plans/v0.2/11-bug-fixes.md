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

### B23 — Rebuild and large ingest hold one uncommitted write transaction for their entire duration: global 503 blackout, invisible build progress, defeated 409 guard (FIXED)

**Fix applied (2026-10-01):** `rebuild_index` now commits the `building` row immediately (visible to `GET /index` progress and the 409 guard), embeds in segments with a commit every 8 batches (~256 vectors) so the write lock releases between batches, and marks the generation `failed` + committed (not silently rolled back) on error. An in-process `_REBUILD_LOCK` closes the check→commit race the DB guard can't see; the DB check stays for cross-process honesty. `ingest_document` commits the corpus write (doc + chunks + FTS, still atomic) before the embed phase, so a large ingest's hundreds of embed batches no longer pin one transaction. Follow-up: the committed `building` row can outlive a crashed process → `reconcile_stale_builds` flips stale `building` → `failed` at startup (same pattern as `run` reconcile → `interrupted`). Regressions: `test_rebuild_lock_rejects_concurrent_same_process`, `test_failed_rebuild_marks_generation_failed_and_recovers`, `test_stale_building_generation_reconciled_on_startup`.

**Independently re-verified (2026-10-01, uncommitted fix, live on :8081):** during a ~6,958-chunk rebuild: `GET /index` showed `building_generation` with live stats (`embedded: 768/6958` mid-flight — progress finally observable); a concurrent `POST /index/rebuild` → **409 "already running"** (was 503); a concurrent document upload → **200 in 6.1s** (was instant-503 blackout); build completed `embedded 6958/6958, failed 0` → `active`; a second rebuild completed `6960/6960`. 30/30 `test_knowledge_rag` green.

**Failure paths also verified live (second pass, 2026-10-01):** (a) *in-handler failure* — corrupted the provider's `encrypted_key` mid-build → `decrypt()` raises `InvalidToken` (not an `EmbeddingUnavailable`, so it escapes the per-batch catch) → `rebuild_index`'s except ran: gen `a09e51f4` committed `status=failed` with honest partial stats `{embedded:256, total:6612}` (one full commit segment) and the API returned 500 to the caller. Cosmetic note: `error` column empty because `str(InvalidToken)` is `""`. (b) *crash path* — `kill -9` mid-build left committed `building` row `67402cb6`; on restart `reconcile_stale_builds` flipped it to `failed` with `error="Gateway restarted during build"` (startup log confirmed), `/index` clean, and a fresh rebuild (`39bfe412`) accepted immediately — no stuck 409.

**Symptom (W7 run, 2026-10-01, gens `98408e82`/`a0df2322`/`2a1ca10b`):** `POST /index/rebuild` embeds the whole vault inside the request session's single transaction. While generation 1 built (~2.5 min, ~6959 vectors), every other write on the API failed instantly with `503 {"code":"database_busy"}` — two concurrent `/index/rebuild` calls and two document uploads all 503'd. During the build `GET /index` showed `building_generation: null` the entire time: the `building` row lives inside the uncommitted transaction, so **build progress is completely unobservable** — the documented "poll `stats_json` on the building generation" path cannot work. The `RebuildInProgress` check (`SELECT count(status='building')`) is blind to the same uncommitted row, so a concurrent rebuild gets `503` instead of the documented `409`, and nothing prevents a second generation row from being created mid-build. A disconnected client doesn't stop the work either: a `bigfile.md` (31.9 MB) upload whose curl died kept inserting ~53k chunk/FTS rows for minutes, growing the WAL to ~300 MB while all other writes were starved. SQLite-side recovery was clean after a forced restart (WAL rolled back, `integrity_check` ok).

**Root cause:** `rebuild_index` and `ingest_document` (incl. `embed_chunks_at_ingest` → `_embed_into_generation`'s `flush()` per 32-chunk batch) run entirely inside the request's session transaction; nothing commits until the handler returns. Fix direction: commit the `building` generation row in its own short transaction (or keep an in-process build flag) so progress is visible and the guard sees it; batch-commit chunk/embedding writes instead of one giant txn; consider `BEGIN IMMEDIATE` semantics deliberately rather than inheriting a lock for the whole sweep.

### B24 — Ingest-time/repair embedding overwrites `generation.stats_json`, corrupting build stats (FIXED)

**Fix applied (2026-10-01):** `_embed_into_generation` now accumulates `embedded`/`failed`/`total` onto the generation's existing `stats_json` instead of replacing them with the caller's batch, so a single-doc ingest no longer clobbers a completed build's totals. Regression: `test_ingest_stats_merge_into_generation_totals`.

**Independently re-verified (2026-10-01, live):** active generation showed `{embedded:6958, total:6958}` after rebuild; a 1-chunk ingest into it (`probe2.md`) moved stats to `{embedded:6959, total:6959}` — accumulated, not reset to `{1/1}`. `test_ingest_stats_merge_into_generation_totals` green.

**Symptom (W7 run, 2026-10-01):** gen `98408e82` (rev 1) was built covering 6959 chunks; after `tiny2.md` was ingested, `GET /index/generations` reported its stats as `{"embedded": 1, "failed": 0, "total": 1}` — the single ingest batch clobbered the sweep's cumulative stats. The generation actually holds 6961 `chunk_embeddings` rows.

**Root cause:** `_embed_into_generation` (`knowledge/indexing.py:100`) unconditionally writes `generation.stats_json = {embedded: done, failed, total: len(chunk_ids)}` where `chunk_ids` is only the *caller's* batch — called from `embed_chunks_at_ingest` with just the new doc's chunks. Fix: merge into existing stats (accumulate `embedded`/`failed` against the generation total) or keep build stats on the generation and per-op counts off it.

### B25 — Zero-chunk ingest crashes: `bind parameter 'content'` 500 on scanned/image-only PDF (FIXED)

**Fix applied (2026-10-01):** `_write_chunk_nodes` skips the FTS executemany when the retrievable set is empty, and `embed_chunks_at_ingest` returns `'na'` for a chunkless document rather than claiming `'embedded'`. A scanned PDF now indexes with `status=indexed`, `chunk_count=0`, `structure.pages` intact. Regression: `test_zero_chunk_document_indexes_honestly`.

**Independently re-verified (2026-10-01, live):** same fixture (`PublicWaterMassMailing.pdf`, 8pp image-only) → **200**, `status=indexed`, `chunk_count=0`, `structure.pages=[1..8]`, `semantic_state=null` (no resource configured → embed not invoked). No 500, no FTS error. `test_zero_chunk_document_indexes_honestly` green.

**Symptom (W7 §6.3, 2026-10-01):** uploading `scanned.pdf` (8 pages, image-only) returns **500 Internal Server Error**. Extraction produces 8 empty `page` blocks → `chunk_blocks` returns 0 nodes → `_write_chunk_nodes` phase 3 executes the FTS INSERT with an empty param list → `sqlalchemy.exc.StatementError: A value is required for bind parameter 'content'`. The plan requires the doc to index honestly with 0 chunks, `structure.pages` intact — currently impossible.

**Root cause:** `ingest.py:95` — the executemany has no empty-list guard. Fix: skip the FTS insert when `retrievable` is empty (and same for any sibling executemany); the doc should index with `status=indexed`, `chunk_count=0`, `structure.pages=[1..8]`.

### B26 — Failed ingest leaves orphaned vault files for any non-`ValueError` failure (FIXED)

**Fix applied (2026-10-01):** `upload`, `upload_scope`, and `ingest_workspace_file` now catch any post-stream exception, roll back, and unlink the file via `_unlink_unless_owned` — which first checks whether a document row already owns `storage_path` (a mid-ingest commit from the B23 fix makes the row the owner; deleting would orphan the row instead). Regression: `test_unlink_unless_owned_respects_committed_document`.

**Independently re-verified (2026-10-01, live):** uploaded `corrupt.pdf` (2 KB random bytes — extraction fails with a non-`ValueError`) → **500** as before, but shared-vault file count stayed **10 → 10** (streamed file unlinked) and zero `documents` rows created. Previously this path left 6 orphans. `test_unlink_unless_owned_respects_committed_document` green.

**Symptom (W7 run, 2026-10-01):** `upload_scope` writes the streamed body to `data/knowledge/shared/<uuid>.<ext>` *before* ingest, but only `unlink`s it on `except (ValueError, UnicodeError)`. Every other failure path (OperationalError `database_busy`, the B25 StatementError, 500s) leaves the file. Observed orphans: `f44a4fe1…md` + `2753abf5…md` (31.9 MB each, two raced bigfile attempts), `50e4f626…pdf` + `373b9c49…pdf` (two scanned.pdf attempts — B25), `62e016d9…md` — six files, zero document rows. The `_stream_upload` 413 path *does* unlink correctly; only post-stream failures leak.

**Root cause:** narrow `except` in `upload`/`upload_scope` (`api/knowledge.py:189-196` and `~331-340`). Fix: unlink `target` on any exception before commit, not just `(ValueError, UnicodeError)` — e.g. `except Exception` with re-raise, or track "row committed" and sweep unreferenced files.

### B27 — Operator `scope=shared` search leaks agent-private documents (FIXED)

**Fix applied (2026-10-01):** the scope predicate is now `(d.agent_id IS NULL OR d.agent_id = :agent_id)` in all four places — `retrieval.py` lexical leg (SQLite + Postgres branches), `vectors.py` `_SCOPE_SQL`, and legacy `ingest.search_documents`. `agent_id=None` now means shared-only (`IS NULL`); an agent id still gets shared + its own private docs. No caller needs an unscoped-everything path today. Regression: `test_shared_scope_never_returns_agent_private_docs`; existing `test_scope_isolation_shared_vs_private` still green.

**Independently re-verified (2026-10-01, live):** `private.md` uploaded under `caber` scope → `POST /scopes/shared/search {"query":"Blue Heron"}` → `[]` (was: leaked the doc); `scopes/caber/search` → `[private.md]`; `scopes/test-agent/search` → `[]`. Three-way scope semantics correct on the live API.

**Symptom (W7 §6.5, 2026-10-01):** `private.md` uploaded to `caber`'s private scope (`0b3b2712`) is returned by `POST /api/knowledge/scopes/shared/search` for its unique term — the "Shared" preview sees private docs. Agent-level isolation is correct (`test-agent`'s `doc_search` got 0 hits, run `e8f004fd`; `caber` found it, run `77a6b2d5`), so this is the operator/preview seam: `_resolve_scope("shared")` returns `None`, and the retrieval predicate `(:agent_id IS NULL OR d.agent_id IS NULL OR d.agent_id = :agent_id)` treats a NULL param as *unscoped* instead of *shared-only*. Both lexical and semantic legs (`retrieval.py:55`, `vectors.py:26`) share the predicate.

**Root cause:** the query needs a three-way distinction — `shared` → `d.agent_id IS NULL`, `agent:<id>` → `(agent_id IS NULL OR = :id)`, and only an internal "everything" path should skip filtering. Either give the shared scope a sentinel (`agent_id IS NULL` when `scope == "shared"`) or split the predicate so the operator preview of Shared can't see private content.

### B28 — Approval card never re-renders after navigating away: `awaiting_approval` invisible to run-restore on both ends (FIXED)

**Fix applied (2026-10-01):** added `awaiting_approval` to both filters — `chat.py`'s `active_run` query (`Run.status.in_`) and `Conversation.tsx`'s `recoverableSessions` predicate. The deep-linked session now marks recoverable, SSE replays from seq 0, and the `tool_call` event carrying `approval_id` rebuilds the pending-approval card. Verified: 751-test suite green, `tsc --noEmit` clean.

**Independently re-verified (2026-10-01, live + real browser):** agent `45a754cb` ("Atlas", `terminal` requires approval) run `c5273cd3` → `awaiting_approval`; `GET /chat/45a754cb/sessions` now reports `active_run_id` + `active_run_status=awaiting_approval` (was `null`/`null` pre-fix); SSE replay from seq 0 re-emits `tool_call` with `pending_approval` + `approval_id`. **Browser E2E (Playwright, frontend :5173):** sent terminal request → approval card rendered → "Back to Agents" → deep-linked back via `?session=<id>` → **card re-rendered** ("Run command `echo ORCHARD-B28`", Requires approval, live Approve/Deny) — then clicked **Deny** on the restored card → approval `rejected`, run `f58ae168` completed. The exact original failure is gone.

**Symptom (2026-10-01):** start a run → leave to the dashboard → the `approval_required` toast pops → click it → lands on the right conversation (`action_path=/agents/{id}/chat?session={sid}` works) but the pending-approval card is gone; the run sits silently parked with no way to approve. Persisted messages carry no approval state (`Conversation.tsx:205-218` maps no `approval_id`), so the card only exists inside the live `streaming` block, rebuilt by replaying the `tool_call` SSE event — which requires the stream to re-attach. It never does: `chat.py:411` selects `active_run` with `Run.status.in_(("pending","running"))` (an `awaiting_approval` run reports `active_run_id=null`), and `Conversation.tsx:799` filters `recoverableSessions` on the same two statuses — so the session is never marked recoverable and `streamRunEvents(seq 0)` never fires. The inner check at `Conversation.tsx:814` that accepts `awaiting_approval` is dead code behind the outer filter; the channel-only poll at `:661` handles it but is gated on `session.channel` (dashboard chat never qualifies). Notifications page is view-only — the `pending_approval` card in `ToolCallBlock` is the sole approve surface. Net: a parked run is unreachable until gateway restart reconciles it to `interrupted`. Elicitation is unaffected (run stays `running`, restores correctly).

**Root cause:** `awaiting_approval` excluded from both active-run filters. Fix: add it to `chat.py:411`'s `Run.status.in_` and `Conversation.tsx:799`'s `recoverableSessions` predicate — replay from seq 0 then rebuilds the card correctly on re-attach. (Also surfaced in §re-verified: B23's 503 blackout makes the same approval unreachable during a rebuild — distinct bug, same "parked run" UX.)

### B29 — `test-run` can never return: the scripted demo pipeline parks on approval/elicitation forever (FIXED)

**Symptom (W8 §4.5, 2026-10-02):** `POST /api/schedules/{id}/test-run` hangs indefinitely — the request never returns, the ad-hoc occurrence stays `running`, and the run row stays `running` with no terminal state. Root cause: `_execute → run_agent(is_test=True)` drives `_DEMO_SCRIPT`, whose turn 5 calls `agent_ask_user`. On agents where `agent_ask_user` is in the ceiling (e.g. `caber`) the mediator creates an `ElicitationRequest` and blocks on `elicitation_registry` — but a headless test-run has nobody to answer → parked until `hitl_timeout` (or forever if timeout=0). Evidence: run `9abc28cc` (caber) parked with elicitation row; on `45a754cb` (`agent_ask_user` not granted but `terminal` approval-gated) runs `31f66536`/`50ad4d3e` parked at the earlier `terminal` approval instead — same class of hang, earlier turn. `run-now` on a disabled schedule completes fine (~4.5s), so the hang is specific to the scripted path hitting a blocking gate. `test-run`'s value as "scripted fast path" is void — it can never produce a result on scripts that touch a gate.

**Root cause / fix direction:** scripted test-runs need a headless policy — auto-deny + auto-answer elicitations (record both as scripted), or a `hitl` override in `schedule_context`/`run_agent(is_test=True)` that makes gates resolve immediately with a test fixture response.

**Fix applied (2026-10-02):** `pipeline.py` sets `syscall_handler._is_test_run = run.is_test`; the mediator gains a headless branch — approval gates auto-approve *after* the ceiling check (never widens permissions) and `_handle_elicitation` auto-resolves immediately with the first option (`responded_by="test"` recorded on the ElicitationRequest row — the scripted answer is auditable). Regression: `test_test_run_auto_approves_gated_capability`, `test_test_run_auto_answers_elicitation`. **Independent re-verification (2026-10-02):** `test-run` on `caber` → run `71932592` returned `completed` in 13.1 s (previously hung indefinitely). DB confirms the headless path: 0 `approval_requests` rows for the run, elicitation row `answered`/`responded_by='test'`/`response='Brief overview'` (first option). FIXED.

### B30 — `missed=run_once` skips earlier occurrences but erases the audit note (FIXED)

**Symptom (W8 §5, 2026-10-02):** after a ~4.8 min `kill -9` outage with a 60 s interval schedule, `missed=run_once` correctly materialized only the latest missed instant and ran it — but the occurrence's `error`/note field ended up **empty**; the plan expects `"N earlier occurrence(s) skipped"` to be recorded. `scheduler.py` sets `occ.error = f"{len(instants) - 1} earlier occurrence(s) skipped"` during materialization, but `_execute` then unconditionally writes `occ.error = result.get("error")` (≈line 513), clobbering the note on success. Verified by code inspection + live row (completed occurrence, empty error). Compare: `missed=skip` correctly produced `skipped_missed` with `"5 occurrence(s) missed"` — the note survives there because no `_execute` runs.

**Fix direction:** preserve the materialization note — e.g. `occ.error = result.get("error") or occ.error`, or store the skip-count in a dedicated column.

**Fix applied (2026-10-02):** `scheduler.py` `_execute` now does `occ.error = result.get("error") or occ.error` — a run error wins, a clean run keeps the materialization note. Regression: `test_execute_preserves_materialization_note`. **Independent re-verification (2026-10-02):** `kill -9` the gateway with a `run_once` schedule enabled → ~2.5 min outage → restart → startup sweep materialized one occurrence at the latest missed instant (09:06) which completed with `error = "2 earlier occurrence(s) skipped"` — the note survives `_execute`. FIXED. **Residual edge case:** `_reconcile_stale_occurrences` (scheduler.py:318) still overwrites `occ.error` unconditionally with `"Gateway restarted during execution"` — a note-carrying occurrence killed mid-run loses the note to the restart error. Same clobber shape, narrower path.

### B31 — Run holds an uncommitted write transaction across the whole first model call: concurrent scheduled runs trigger a global `database is locked` storm (FIXED — round 2)

**Symptom (W8 §6, 2026-10-02):** with four 60 s schedules firing `sleep 75` runs concurrently, every write path began failing — **62 `sqlite3.OperationalError: database is locked`** errors (well past `busy_timeout=15000`), scheduler ticks ran ~8 minutes behind their instants (`created_at` ≫ `scheduled_for`), API writes (session create, schedule POST) timed out, and runs/occurrences were orphaned `running`/`pending`/`queued` after their tasks died mid-write. Meanwhile reads stayed fast — classic single-writer starvation.

**Root cause:** `pipeline.py` line ~353-355 sets `run.status="running"` + `await self.db.flush()` inside the session lock, and nothing commits until the first event persist (`db.commit()` at ~529/549/588 inside `_persisting_emitter`, or end-of-run). The intervening code — config load, manifest capture, **and the entire first model call** — runs with an open write txn holding the SQLite RESERVED lock. Any other writer's `busy_timeout` is eaten by the model-call latency; with several runs per minute the queue self-feeds. A visible corollary: runs show DB status `pending` while actually running (the `running` write sits uncommitted — observed on `afaa65ea`, `ff4a4bfb`). The comment at line 342-345 states the intent ("release the write lock before the long-running harness loop") but the later flush re-opens the txn. Secondary fallout: `ov-queue` accumulated 7 permanently-`queued` occurrences (no drain while the head run never finished; disabling the schedule strands them — no reaper).

**Fix direction:** `await self.db.commit()` immediately after the `run.status/started_at` flush (status becomes observable too — fixes the phantom `pending`), and audit other flush-then-await seams (manifest capture, event persist) for the same pattern.

**Fix applied (2026-10-02):** `pipeline.py` now commits all pre-loop writes (run status, manifest, workspace path, attachments) immediately before `harness.run` — covering the status flush *and* the manifest write, which would otherwise re-open the txn after a 355-line commit. The exception path was also hardened: `rollback()` first, then mark the run `failed` via a **fresh** session (`update(Run)`) — a mid-flush DB error previously left the session unusable so the failure mark itself could never land (the orphaned `pending`/`running` rows). Seam audit: mediator audit flushes sit post-execution and ride the per-event emitter commits; mediator approval/elicitation paths already commit before blocking. Regression: `test_run_status_committed_before_harness` (fresh-session mid-run read sees `running`). **Live re-verification (2026-10-02):** four 60 s schedules (`B31-storm-1..4`) fired concurrently on `caber` → 4/4 occurrences `completed` on attempt 1, **zero** `database is locked` in the gateway log (vs 62 pre-fix), and 16 pause/resume API writes during the storm all returned 200 in ~30 ms. No orphaned `pending`/`running`/`queued` rows.

**Independent re-verification (2026-10-02): DOES NOT REPRODUCE — still broken.** Re-ran the identical storm (four 60 s schedules, `sleep 75` prompts, `overlap=allow_parallel`, on `caber`, plus one extra enabled 60 s schedule): **48 `database is locked` errors**, 7/8 first-tick occurrences `failed` ("internal error"), **12 run rows orphaned `running`** with zero model-call progress (startup reconcile had to mark them `interrupted` — same pre-fix orphan shape), and lock accrual only stopped when all schedules were disabled. Traceback shows the surviving seam: the first **in-loop** write — `INSERT INTO model_calls` on the run's session right after the first model call returns — hits the >15 s write lock under concurrency, the session rolls back, and every subsequent statement fails `PendingRollbackError` → run dies "internal error". The pre-loop commit at pipeline.py:640 is correct as far as it goes, but per-event writes inside `harness.run` still contend; under ≥4 concurrent runs the single-writer queue self-feeds. API writes did stay fast mid-storm (8 PUTs 21–26 ms — that part of the claim holds). Needs a deeper fix (e.g. per-run short-lived sessions for event writes with retry, or serialized writer), not just an earlier first commit.

**Round-2 fix applied (2026-10-02): transaction-boundary fix across the remaining seams.** The deeper diagnosis: any `db.add(); flush()` on the run's shared session opens a write txn that stays open until the *next* commit — which could be a sibling tool call's `sleep 75` away. Fixed by bounding every write transaction so none can span a slow await:

- `syscall/mediator.py` — `_SessionWriteLock` wraps the shared session: every `async with db_lock` section now commits on clean exit and rolls back on error (was: serialized flushes that left the txn open). All 7 mediator audit writes moved to `_write_audit()` on a **fresh** session with `retry_locked_transaction` — audit I/O can never re-open the run's txn mid-dispatch.
- `pipeline.py` — commits after `_resolve_session` before `_close_idle_sessions` (session insert no longer spans summary/KG LLM calls); rollback added to `_close_idle_sessions`, skill-resolution, and manifest-capture except paths (was: swallowed errors poisoned the session → `PendingRollbackError` → "internal error").
- `loop.py` — `_record_model_call` writes on a fresh session (model_call inserts visible pre-dispatch); commit before `asyncio.gather` tool dispatch; compaction-summary flushes followed by commits.
- `episodic.py` — `close_session` commits after the summary-FTS write and after KG extraction (write txn no longer spans the extraction LLM call).
- `web.py`, `terminal/registry.py`, `memory/*` — all tool-internal `flush()`-only writes now commit via `db_lock` (or directly).
- `scheduler.py` — `_execute` commits after loading occurrence/schedule/revision (no read snapshot held across `run_agent`); restructured to short sessions so failure paths can't orphan `running` rows.
- `api/schedules.py` — `run-now`/`test-run` release the request session before the long-running run.
- `db.py` — pool 5+10 → 10+20 (each run legitimately holds ~2 connections: shared session + fresh audit/model_call sessions).

**Regressions:** `test_dispatch_does_not_hold_write_lock` (real file-backed DB, `busy_timeout=500`: fresh-connection write succeeds *during* in-flight tool dispatch), `test_model_call_committed_before_dispatch`, `test_record_model_call_rollback_recovery`, plus `_SessionWriteLock` commit-on-exit/rollback-on-error tests. **Live re-verification (2026-10-02):** nine 60 s schedules (`storm-v2-*`, `storm1-4`, `storm-writeprobe`) firing on the same tick → **41/41 occurrences `completed`, 0 errors, 0 `database is locked`/`QueuePool`/`PendingRollback`/`Traceback` lines** in the gateway log; 15 pause/resume API writes mid-storm all 200 at **2–5 ms** (vs 16 s stalls/503s pre-fix); **0 orphaned `running` rows** after drain. Full suite: 793 passed, ruff clean.

**Independent re-verification (2026-10-05, round 2): CONFIRMED FIXED.** Re-ran the exact storm that wedged round 1 (four 60 s `sleep 75`/`allow_parallel` schedules on `caber` + a fifth 60 s schedule): **24/24 occurrences and runs `completed`, 0 `database is locked`/`PendingRollback`/`QueuePool`/`Traceback` in the gateway log**, 10 real PUT writes mid-storm all 200 at **23–39 ms**, runs drained cleanly after disable (no orphans — last tick's runs finished on their own). Previously-red `test_approval_park_persists_status_and_notification` now also passes; scheduler suite **45/45**. Contrast with round 1 (48 lock errors, 7 failed occs, 12 orphaned runs) — the transaction-boundary fix eliminated the starvation.

### B32 — Scheduled run parked at approval is operator-invisible: status stays `running`, no `approval_required` notification (FIXED)

**Symptom (W8 §8.1, 2026-10-02):** a scheduled run on `45a754cb` (`terminal` approval-gated, `auto_approve=[]`) parked correctly — `approval_requests` row `6090c1fd` created and approvable — but (a) the run row kept `status='running'` (never `awaiting_approval`), and (b) **no `approval_required` notification was emitted** (zero rows with `entity_id=run 49d44d04`; elicitation path does emit one). Operator has no surface to discover/approve it; the run sits until `hitl_timeout`. Root cause: `run_manager.py:173-188` only sets `ctx.status='awaiting_approval'`, fires `_update_run_status`, and posts the notification when `rid in _active_runs` — and `scheduler._execute → run_agent` never registers a RunContext. Chat runs register; schedule runs don't.

**Fix direction:** register schedule `_execute` runs in the run manager (or emit the status update + `approval_required` notification unconditionally from the mediator path), so parked scheduled runs surface on the dashboard like chat runs do.

**Fix applied (2026-10-02):** moved the lifecycle write into the pipeline itself — `_persisting_emitter` now persists `run.status='awaiting_approval'` and fires the `approval_required` notification (fresh session, same deep-link shape) on the `pending_approval` event, so every transport (schedule, channel, headless) behaves like chat. `run_manager`'s callback keeps its in-memory `ctx.status` update for SSE clients; `create_notification` dedupes the double post. Regression: `test_approval_park_persists_status_and_notification`. **Independent re-verification (2026-10-02):** `run-now` on a schedule for `45a754cb` (terminal gated, `auto_approve=[]`) → run `4c71ea84` parked with `runs.status='awaiting_approval'` (was `running` pre-fix), `approval_required` notification created unread with deep-link `action_path=/agents/45a754cb/chat?session=71bb83a3`, approval row `bd6849a0` pending → `POST …/approve` → run `completed`. FIXED.

### B33 — `POST /schedules/{id}/duplicate` reports the source's `revision_number`, not the clone's (FIXED, cosmetic)

**Symptom (W8 §2.4, 2026-10-02):** duplicating a schedule at revision 2 returns `"revision_number": 2`, while the clone's actual `schedule_revisions` row is `revision_number=1` (verified in DB). The response serializes the copied config against the source's rev field. Harmless but misleading — the UI card then displays the correct rev (1) after refetch.

**Fix applied (2026-10-02):** `duplicate_schedule` fetches `current_revision` for the clone after `write_revision` and serializes against it. Regression: `test_duplicate_reports_clone_revision`. **Independent re-verification (2026-10-02):** source bumped to `revision_number=2` via PUT → `POST /duplicate` response reports `revision_number: 1`; DB confirms the clone holds exactly rev 1. FIXED.
### B34 — `vault_index_degraded` never emits when a rebuild finishes "successfully" with a broken embedding resource (FIXED)

**Symptom (W9 §5.2, 2026-10-05, live on :8081):** corrupted the embedding provider's `encrypted_key`, then `POST /api/knowledge/index/rebuild` → **200** with a generation committed `status="active"`, `failed=6552`, reason "embedding resource not ready". **No `vault_index_degraded` notification was emitted** — the vault is silently degraded to lexical-only while the generation reports active. The operator gets no ping for a state the feature explicitly wants surfaced.

**Root cause:** `_notify_index_degraded` in `backend/src/agentos/knowledge/indexing.py` was only invoked on the exception path and by `reconcile_stale_builds` — not when a generation activates cleanly but degraded.

**Fix (2026-10-05):** after a clean activation, `run_rebuild` inspects `stats_json` — `failed > 0` now emits `vault_index_degraded` (title "Knowledge index degraded", message includes `embedded/total` + reason, `event_id=vault_index_degraded:{generation.id}` for per-generation dedup). `activate_generation` emits the same when chunks remain unembedded because the resource isn't ready. `_notify_index_degraded` gained a `title` kwarg so build *failures* still read "build failed" vs. degraded-active "degraded".

**Verified live:** `POST /api/knowledge/index/rebuild` with `unvalidated` resource → generation `5618f6f0` active `0/6552` embedded → notification `vault_index_degraded:5618f6f0-…` emitted, SSE fan-out observed, action_path `/knowledge`.

**Independently re-verified (2026-10-05):** fresh rebuild against the still-`unvalidated` OpenAI embed resource → generation `6cec83e3-2da1-42d5-a40a-d182049468f9` committed `status="active"`, `embedded=0`, `failed=6552`, reason "embedding resource not ready" → notification row `vault_index_degraded:6cec83e3-…`, title "Knowledge index degraded", message carries `0/6552` + reason, `action_path=/knowledge`, unread.

### B35 — Notification prefs writes are lost-update prone: any tab PUTs its full stale blob (FIXED)

**Symptom (W9 §6–§8, 2026-10-05, live, reproduced twice):** `saveNotificationPrefs` merged the caller's patch into the module cache and PUT the **entire blob**. Any tab whose cache predates a newer write reverted untouched fields (banner's delayed `markAsked` reverted quiet hours; a closed tab's late permission resolution reverted `defaults.browser`).

**Root cause:** replace-semantics PUT of the whole prefs object — the last full-blob writer wins, including writers patched against a stale cache.

**Fix (2026-10-05):** patch protocol end-to-end. Backend `PUT /prefs` merges the request onto the **stored** row (was: onto a fresh-defaults blob); `defaults`/`quiet_hours`/`permissions` merge shallowly, `overrides` merges per event type, `null` deletes an override (omission can't express delete). Frontend: `NotificationPrefsPatch` type; `saveNotificationPrefs` PUTs the patch, not the blob; every call site sends only owned keys (master toggle, quiet-hours rows, override selects, banner `markAsked` — all audited; "Default" sends `null`).

**Verified:** pytest `test_prefs_patch_merges_onto_stored` + live on :8081 — `{"permissions":{"tauri_asked":true}}` left quiet hours + overrides intact; `{"overrides":{"run_failed":null}}` deleted only that key. 58 vitest incl. null-delete regression.

**Independently re-verified (2026-10-05):** seeded `quiet_hours` + two `overrides` via PATCH-shaped PUT → `{"permissions":{"tauri_asked":true}}` → quiet hours and both overrides survived (previously wiped); `{"overrides":{"run_failed":null}}` deleted only that key, `elicitation_required` override kept. `saveNotificationPrefs` PUTs the patch, not the blob — `NotificationPrefsForm`/`NotificationPermissionBanner` send owned keys only.

### B36 — Prefs changes in one tab never reach other tabs' caches (FIXED)

**Symptom (W9 §7.3 live test, 2026-10-05):** enabled quiet hours covering the current window via PUT, emitted an event — the leader tab reported `browser|delivered` + `toast|delivered` anyway. Its prefs cache predated the write; `inQuietHours` evaluated a stale matrix. Suppression only corrected after the tab happened to reload (`suppressed` observed on retry).

**Root cause:** `notificationPrefs.ts` caches the blob per-tab at load; nothing invalidates a peer's cache — the leader keeps stale quiet-hours/override state indefinitely while holding ping authority.

**Fix (2026-10-05):** `crossTab` gains a `prefs` gossip message — `saveNotificationPrefs` broadcasts after a successful PUT; every tab's store subscribes `onPrefsChanged → loadNotificationPrefs()` (re-fetch, never trust a broadcast blob). Only covers tab-origin writes; a `curl` PUT still requires reload — acceptable, same contract as before.

**Verified:** vitest "re-fetches prefs when a peer tab broadcasts a prefs change" + live re-run of §7.3 (`suppressed` on both surfaces, row stays unread).

**Independently re-verified (2026-10-05, agent-browser, 2× localhost:5173 tabs):** quiet-hours window widened to 14:00–17:00 via tab B's settings UI (its own `saveNotificationPrefs` → gossip). Tab A's cache still held 14:00–16:00 — a stale tab would show a toast for a 16:0x emit. Emitted `test:v2gossip1` → tab A showed **no** toast and the leader reported `toast/suppressed` — tab A's cache was refreshed by the `prefs` gossip (`onPrefsChanged → loadNotificationPrefs`, no reload).

### B37 — `ERR_INSUFFICIENT_RESOURCES` still reachable: unbounded poll + unguarded store re-instantiation (FIXED)

**Symptom (W9 §8.4/§10 live run, 2026-10-05, Playwright headless):** during the test-result pass the page wedged — DevTools console showed hundreds of `Failed to load resource: net::ERR_INSUFFICIENT_RESOURCES @ /api/notifications` in ~4/sec bursts (the 5 s inbox poll failing instantly against an exhausted socket pool), and navigation timed out entirely. Same user-visible signature as the original "site won't load" report.

**Root cause (two compounding defects):**
1. `setInterval(poll, 5000)` fired regardless of the previous tick and `api.request()` had **no timeout** — a slow/hung fetch stacked one socket per tick until the per-origin pool was gone.
2. ~4 failing polls/sec implies multiple live store instances in one page: Vite can re-instantiate `notificationStore.ts`/`crossTab.ts` through a dependency update where the `import.meta.hot.dispose` handler isn't reached, leaving a second poller/SSE/channel alive.

**Fix (2026-10-05):** (a) poll serialized via `pollInFlight` guard and bounded with `AbortSignal.timeout(15_000)` — worst case one socket per store instance; (b) `notificationStore` and `crossTab` stash their cleanup on `globalThis` at module init — a re-instantiated module always kills the previous instance's timers/socket/channel regardless of accept boundaries (`__agentosNotifStoreStop`, `__agentosCrossTabStop`).

**Verified:** 58/58 vitest, tsc clean. Post-fix, exactly one delivery report per adapter per event (leader-only) in live emit checks; prior zombie evidence was the 3-socket leader set matching 3 browser instances — now additionally protected when instances multiply.

**Independently re-verified (2026-10-05, agent-browser):** 3 same-origin tabs → exactly **1** upstream `:8081` connection (leader-only SSE, survived tab churn/re-election); `pollInFlight` guard + `AbortSignal.timeout(15_000)` confirmed in source and live (no overlapping `/api/notifications` polls, no `ERR_INSUFFICIENT_RESOURCES` in console/network log); live emit → exactly one delivery row, `attempts=1`. **Residual found → B38.**

### B38 — Notification poll-seen while a tab is a follower is permanently never reported (FIXED)

**Symptom (2026-10-05, agent-browser, 3× localhost:5173 tabs):** during leader-election churn (third tab joining + SSE reconnect gap) emitted five notifications `test:v2burst1-5`. Minutes later: still `read=0`, **zero `notification_deliveries` rows** — no tab ever reported delivered/suppressed for them. A live probe emitted after election settled reported `toast/suppressed` within a second, so the pipeline itself was healthy — the gap items are permanently stranded.

**Root cause:** `process()` in `notificationStore.ts` ran `seenIds.add(n.id)` **before** the `leader` checks. Any tab whose 5 s poll picks up a notification while its local `leader` flag is `false` marks it seen and skips the reports; when that tab later wins the election the items are already in its `seenIds` so its poll never re-processes them, and `retryFailedDeliveries()` only retries existing `failed` rows — never-reported items have no row to retry. Consequences: missing delivery-audit rows, and a toast the user never sees if the only processing pass ran on a hidden follower (inbox unread state is still correct).

**Fix applied (2026-10-05):** `deferredReports` — `process()` records every unread id it handles while `!leader`; `markRead` drops ids (read rows never need reports). On promotion (`onLeaderChange(true)`), before `retryFailedDeliveries`, each deferred id is re-`process()`ed with `reportsOnly=true`: full leader-side pass (suppression/quiet-hours re-evaluation, `reportToastAggregate`, `fireOsAdapter`) but no duplicate toast — the tab already rendered it as a follower. Regressions: `promotion to leader reports items poll-seen as follower (B38)` + `promotion skips items the user already read (B38)` in `notificationStore.test.ts` (12/12 file, 58→60 Vitest suite).

**Related fix (same commit, found while auditing pulled W8):** `scheduler.py::_notify_failure` emitted `schedule_failed` with no `event_id` — content-hash fallback would dedup a *new* failure streak producing an identical error message. Now keyed `schedule_failed:{schedule_id}:{YYYY-MM-DD}` + `entity_type="schedule"`, matching the pre-rewrite emitter's daily-dedup semantics at schedule granularity.

### B39 — Disabled agents still execute runs and accept chat: `enabled` is never enforced (FIXED)

**Symptom (2026-10-05, operator report):** "I still can run the disabled agent… I can also click into the disabled agent in GUI." Disabling an agent dimmed its card but every execution path still worked — chat sent real runs, and nothing in the UI told you the agent was off.

**Root cause:** `run_agent()` — the single entry point for every trigger (dashboard chat, schedules, heartbeat, channel webhooks) — verified the agent *exists* but never checked `agent.enabled`. The chat route pre-checked existence only, and `Conversation.tsx` rendered a fully functional composer for disabled agents. `enabled` was cosmetic.

**Fix applied (2026-10-05):**
- `runner.py` — `run_agent` raises `ValueError("Agent is disabled: {id}")` before building the inbound message. Schedules/heartbeats hitting a disabled agent now record an honest `failed` occurrence with that error; channel webhooks log it.
- `api/chat.py` — `POST /api/chat/{id}/message` returns `400 "Agent is disabled"` up front (previously the refusal would have surfaced as a run failure / 500).
- `Conversation.tsx` — disabled-agent banner ("read-only — re-enable in Agents") + composer `disabled` while `agent.enabled === false`; no-model banner suppressed on disabled agents.
- Card still navigates — history stays readable; only execution is gated.

**Verified:** `test_run_agent_refuses_disabled_agent` in `test_pipeline.py` (8/8 file); `tsc` clean. Live: `POST /api/chat/45a754cb/message` (pre-disabled agent) → `400 Agent is disabled` on the restarted gateway.

### B40 — OS pings suppressed while the app window is merely unfocused (FIXED)

**Symptom (2026-10-05, operator report — Tauri debug app):** chat view left open on the agent, operator switched to another application, `run_completed` landed → **no macOS notification**, no toast; the inbox row was auto-marked read. Same would occur in a backgrounded-but-on-screen browser window.

**Root cause:** focus suppression equated "operator is looking" with `document.visibilityState === "visible"` (`selfTabVisible()` gating the local check in `isSuppressed`). A window that stays on-screen but loses OS focus still reports `visible` — `visibilityState` tracks page occlusion/minimize, not window focus. So the exact case OS pings exist for (you're in another app) was classified as "already watching" and suppressed + auto-read.

**Fix applied (2026-10-05):** "looking" now means *visible AND focused*.
- `crossTab.ts` — new `selfFocused()` = `selfVisible() && document.hasFocus()`; heartbeat/hello gossip a `focused` flag (`PeerState.focused`, backfilled `?? visible` for pre-B40 peers); `window` `focus`/`blur` listeners re-beat on focus change; `peerFocusKeys()` only unions keys from peers that are `visible && focused`. Exported `selfTabFocused()`.
- `focusRegistry.ts` — `isSuppressed` local check gates on `selfTabFocused()`; peer side inherits the tighter `peerFocusKeys()`.
- Toasts and leader election deliberately unchanged: `anyPeerVisible()`/toast gating stays visibility-only (an unfocused window still displays a toast to glance back at); leadership doesn't care about focus.
- Regression: `visible-but-unfocused window does not suppress (B40)` in `focusRegistry.test.ts` — focused entity + unfocused window → not suppressed.

**Verified:** Vitest 61/61, `tsc` clean. Live re-check pending a Tauri reload — the fix lands when the running debug app next loads the dev frontend.

**Semantics refined (2026-10-05, operator decision):** focus suppression now gates **toast + auto-read only**. The OS adapter (`browser`/`system`) bypasses focus suppression entirely — the ping doubles as the completion signal even when you're already on the page. Quiet hours still suppress all pings. Delivery audit: focused → `toast|suppressed` + `browser|delivered`; quiet → both `suppressed`.

**Note:** suppression failures now resolve toward the *extra* ping — a focused-window false negative (e.g. focus inside DevTools) pings anyway rather than missing one.

### B41 — macOS-level notification switch invisible to the app: toggle + audit lie (FIXED)

**Symptom (2026-10-05, operator report — bundled `CaberOS.app`):** operator disabled CaberOS under System Settings → Notifications → the in-app "Enable notifications" toggle still showed enabled, and deliveries kept auditing `system|delivered` while macOS dropped every post.

**Root cause:** `tauri-plugin-notification`'s desktop permission methods are hardcoded — `isPermissionGranted()`/`requestPermission()` unconditionally return `Granted` (`desktop.rs`). Its send path is `notify-rust` → `mac-notification-sys` → `NSUserNotificationCenter`, an API that predates the per-app permission model and is removed on macOS 26/27: posts silently vanish, `show()` still returns `Ok`. Three lies stacked: the toggle showed pref-not-permission, `osPermissionState()` always reported `granted`, and `deliverOs` audited `delivered` for posts the OS discarded. (Same dead path explains dev-mode no-shows — additionally dev posts under a spoofed `com.apple.Terminal` identity with no bundle.)

**Fix applied (2026-10-05):** migrate to `UNUserNotificationCenter` (the real per-app permission API) + honest state plumbing.
- `Cargo.toml` — `[target.'cfg(target_os = "macos")']`: `mac-usernotifications 0.3.1` + `notify-rust 4.18` with `preview-macos-un` (feature-unifies the plugin's own `notify-rust` onto the modern backend).
- `lib.rs` — two app commands: `notification_os_state` → `get_notification_settings()` mapped `Authorized|Provisional|Ephemeral→granted`, `Denied→denied`, `NotDetermined|other→default`, error→`unavailable`; `notification_os_request` → `request_auth()` (`true→granted`, `false→denied`, err→`unavailable`). Non-macOS builds return `unavailable`. Registered in `generate_handler!` (app commands need no capability grant).
- `notifAdapters.ts` — desktop `osPermissionState`/`requestOsPermission` now `invoke` the commands instead of the plugin's stubs; `deliverOs` reads state, requests once when `default`, and reports `{state:"failed", error:"permission_<state>"}` unless actually granted — the audit can no longer claim delivery macOS denied. Browser path untouched.
- `NotificationPrefsForm.tsx` — the pre-existing `perm === "denied"` blocked-hint finally works (it never fired under the stub); re-checks permission on window `focus` (macOS toggles change outside the app); the hint deep-links to `x-apple.systempreferences:com.apple.Notifications-Settings` via `tauri-plugin-opener`.
- Frontend bump already in place: `tauri` 2.12.1 / `tauri-plugin-notification` 2.5.1 (fixed the JS↔Rust version mismatch that hard-blocked `tauri build`).

**Verified:** `cargo check` clean (dev profile), `tsc -b` clean, Vitest 61/61. End-to-end on the rebuilt bundle: OS toggle off → app shows `denied` + blocked hint, deliveries audit `system|failed permission_denied`; toggle on → real banner via `UNUserNotificationCenter`, including while the app is frontmost.

**Signing postmortem (2026-10-06, verified in `usernoted` logs):** the UN migration surfaced a deeper blocker — Tauri's linker ad-hoc signature gives each binary a hash-derived identifier (`caberos-<cdhash>`), and `usernotificationsd`'s entitlement check requires the code-signing identifier to equal `CFBundleIdentifier`. Every UN call logged `Entitlement 'com.apple.private.usernotifications.bundle-identifiers' required ... not allowed` → the app permanently read `denied` regardless of the System Settings toggle. Fix proven live: **ad-hoc re-sign with an explicit identifier** — `codesign --force --deep -s - --identifier com.caberos.desktop` → `Entitlement check success: matching bundle identifiers` → `Presenting as banner`. No Apple account required; an Apple Development cert or Developer ID works equally well (any stable signature whose identifier matches the bundle id). Wired into the pipeline: `scripts/sign-app.sh` runs at the end of `desktop:build`; distribution still needs Developer ID for Gatekeeper, but local notifications no longer depend on it.

### B42 — Zombie gateway resurrects reconciled runs + approval state is not durable (FIXED 2026-10-06)

**Symptom (2026-10-06, operator report — "error in the latest run"):** run `793bbde9` (`vietnam-stock-market-analyst`, user asked about VN30) parked on two `web_search` approvals at 06:06 and showed `running` for ~6h across multiple app restarts. Eventually the whole gateway wedged — requests accepted, zero bytes returned. Separately reported by operator: outside the chatview the session shows "waiting approval", inside the chatview **no approval card renders**.

**Root cause — two halves, both traceable to process lifecycle:**

1. **Zombie gateway re-asserts `running`.** Killing the app binary (`pkill` on `Contents/MacOS/caberos`) orphans its `caberos-gateway` child, which keeps :51718, keeps the DB, and keeps the run's in-memory asyncio task awaiting approvals. B2's startup reconcile in the *new* gateway marks the row `interrupted` — but the zombie's still-live task checkpoints status back to `running` on its next write. Reconcile wins the write; the zombie wins the rewrite. Verified live: `kill -9` of every caberos-gateway + relaunch → reconcile ran at startup → `793bbde9` → `interrupted` instantly. Collateral during the zombie window: `sqlite3.OperationalError: database is locked` on `INSERT INTO runs` (a second run attempt, `cf180d52`, died at insert) and total gateway starvation (single wedged write transaction queues every DB request — the "zero bytes" hang).
   - **Fix direction:** (a) app exit must reap the gateway child (Tauri sidecar kill-on-exit / process-group kill, not just the main binary); (b) reconcile needs *ownership fencing* — a run row should record its owning gateway instance id, and the owner heartbeats; reconcile only sweeps rows whose owner is dead, and zombie writes get rejected by an owner-token check. A run also needs an approval/expiry timeout — "pending forever" is not a terminal state but behaves like one with zero operator signal.

2. **B28 fix only covers live in-memory context.** The approval card is rebuilt by replaying `tool_call`/`approval_id` SSE events from `ctx.events` — which requires `get_run(run_id)` to hit a live `RunContext`. Pending approvals live only in `approval_requests` rows; `getSessionMessages` never hydrates them, and `Conversation.tsx` learns `approval_id` solely from the live stream (`:500`). Owner dead → `stream_run_events` 404 → card unrecoverable forever, while the outside-chatview surface still correctly reports `awaiting_approval`/`waiting` from DB state.
   - **Fix direction:** persist pending-approval state durably — either write the `tool_call` message row with `status=pending_approval` + `approval_id` at creation (not after decision), or have the session/run API join pending `approval_requests` so the chatview can render the card without SSE replay. Same applies to `elicitation_requests`.

**Verified state after fix:** clean restart → run `interrupted`, API responsive, approvals still `pending` in DB (inert). Neither fix implemented — needs the ownership-fencing + durable-approval persistence work.

**Update (2026-10-06) — reaping is now structural, approval staleness reconciled:**

- **Windows was already fenced** (PR #65): the gateway joins a `KILL_ON_JOB_CLOSE` Job Object — the kernel terminates the whole tree when the app dies, including Task-Manager force-kill (`gateway.rs` `win_job`).
- **macOS/Linux now fenced** via a parent-death watchdog in `gateway_entry._start_parent_watchdog`: a daemon thread polls `os.getppid()` every 2s and `os._exit(0)`s when the ppid *flips* (init/subreaper adoption = parent gone). Kill −9 verified live: `kill -9` on the app → gateway + port 51718 gone within 5s; normal launch unaffected. The earlier accidental self-limit was SIGPIPE on the broken stdout pipe — worked only if the orphan happened to log; the watchdog makes it deterministic.
- **Ownership-token fencing (zombie write rejection) — unnecessary now.** It only mattered while a zombie could survive; the watchdog caps the multi-writer window at the ~2s adoption lag. No live zombie, nothing to fence against.
- **Pending approvals reconcile** to `interrupted` (`decided_by="system_restart"`) at startup via `reconcile_pending_approvals` — runs BEFORE the orphan-early-return and commits independently, so a stale card can't click through a successful "approved" write on a dead run. Operator decision: interrupted is terminal — no resume.
- **Durable timeline hydration (2026-10-06):** the feared "dead card looks actionable" turned out to be worse and quieter — `tool_call` messages only persist on *terminal* status (`pipeline.py`), so a call killed mid-approval left no row at all and simply vanished from the timeline. `reconcile_pending_approvals` now writes a `role="tool_call"` row per stale approval (`status="interrupted"`, capability + args + `approval_id`, next `seq` for the run) so the run's tail explains itself. No card can render actionable because `pending_approval` never persists.
- **Port-claim honesty (2026-10-06):** `gateway_entry._claim_port_or_die` bind-probes the port before uvicorn; on conflict it names the holder (`lsof`/`netstat` → `ps`/`tasklist` for the full path — a dev box now prints e.g. `/Applications/CaberOS.app/.../caberos-gateway (pid N)`) and exits 3. The Rust side watches the spawned child (`GatewayProcess` monitor thread, 500ms `try_wait` poll, `stopping` flag distinguishes intentional kills) — on spontaneous death `gateway_error` returns the last FATAL line from gateway.log. The frontend asks for it after 8 failed health polls (~12s) and shows it instead of spinning "Starting the local gateway…" forever. Verified live: squatter test against the real app's port printed the full holder path + exit 3.
- **Still open:** nothing structural. Residual: while a *foreign healthy CaberOS gateway* squats (second app copy), the app's health check succeeds against it — no ownership token distinguishes "ours" from "theirs" (deliberately descoped).

### B43 — OS pings silently dropped when the UI thread is busy; audit says `delivered` anyway (FIXED)

**Symptom (2026-10-06, operator report):** `approval_required` pings produced macOS banners, but every `run_completed` ping didn't — while the delivery audit recorded `system|delivered` for all of them.

**Root cause — two stacked defects in the send path:**

1. **`block_on_current` drops the send before dispatch.** `sendNotification` → `notify_rust::Notification::show()` → `send_blocking` → `block_on_current(send_and_wait_for_delivery)`. On a tokio worker thread, `block_on_current` checks `CFRunLoop::main().is_waiting()` and returns `Err(MainThreadNotRunning)` when the main run loop isn't idle *at that instant* — **before the send future is ever polled**, so `addNotificationRequest` is never called. The gate exists because `block_on` parks the calling thread and needs the loop already pumping to guarantee the completion handler wakes it. `run_completed` fires exactly when the app is busiest (SSE teardown, DOM churn) → is_waiting false → silent drop. Approvals landed during idle moments → delivered. Verified in `usernoted` + app-process logs: only the two approval sends ever produced "Adding notification request"; the four `run_completed` sends (with `Getting notification settings` permission checks at the exact audit times) produced nothing.
2. **The plugin discards the result.** `tauri-plugin-notification`'s desktop `show()` does `tauri::async_runtime::spawn(async move { let _ = notification.show(); })` — the JS `sendNotification` returns as soon as the payload is prepared, so `deliverOs` reported `delivered` for sends that never reached macOS.

**Fix:** new `notification_os_send(title, body)` Tauri command (`frontend/src-tauri/src/lib.rs`) calling `mac_usernotifications::send()` — the **async** path: dispatch → `addNotificationRequest` → await the completion handler → real `Ok`/`Err` back to JS. No `is_waiting` gate (the future simply pends until the main loop next pumps — a GUI app pumps continuously). `deliverOs` (`frontend/src/lib/notifAdapters.ts`) invokes it and propagates errors into the delivery audit; on `unavailable` (non-macOS) it falls back to the plugin's `sendNotification`, whose Windows/Linux paths don't have the run-loop gate.

**Also verified:** inbox ordering fix — `GET /api/notifications` now orders by `julianday(created_at)` because the stored column is text and mixed ISO shapes (`T`+offset vs space-separated) break lexicographic `ORDER BY` (all `T` rows sorted above all space rows regardless of time). Regression test: `test_inbox_orders_mixed_timestamp_formats`.

### B44 — Session messages endpoint returns the FIRST 100 rows; new replies invisible once a session outgrows the limit (FIXED)

**Symptom (2026-10-06, operator report):** "cannot see the model output in chatview" — the run completed (`tokens_out` > 0, assistant row in DB) but the reply never rendered, even on reload.

**Root cause:** `GET /api/chat/{agent}/sessions/{id}/messages` ordered `Run.started_at ASC, Message.seq ASC` then applied `.limit(100)` — returning the session's **oldest** 100 rows. The operator's session had 112 rows (tool_call rows count), so every message past row 100 — including the newest model output — was silently cut. The chatview showed a frozen prefix; every new reply vanished on reload.

**Fix:** `backend/src/agentos/api/chat.py` — order DESC + LIMIT, then `reversed()` in Python: the endpoint now returns the newest `limit` rows in chronological order. Regression test: `test_session_messages_limit_returns_newest` (5 runs × 2 msgs, `limit=4` → the newest four, ascending).

**Follow-up — cursor pagination for >100-row sessions:** the window fix alone left older rows unreachable in the UI. Added `before_id` cursor + `has_more` to the endpoint (returns `{messages, has_more}`), `Message.id` as final sort tiebreaker (seq resets per run, `started_at` can tie), and scroll-top lazy loading in `Conversation.tsx` (`loadOlderMessages` + scroll anchoring via `useLayoutEffect`, 50-row pages, id-deduped prepends, spinner row).

**Cursor subtlety:** timestamp comparisons must go through `cast(col, String)` on both sides — `server_default func.now()` stores second precision (`'SS'`) while ORM-bound datetimes rebind microseconds (`'SS.000000'`), so a typed row-value `<` lets the cursor row compare *less than itself* and leak into the next page. Ordering uses the same casted expressions so predicate and sort share one total order.

### B45 — YOLO mode reset on every app restart; no chatview indication (FIXED)

**Symptom (2026-10-06, operator report):** "when I enable yolo mode, it's not saved when I close the app" — and no warning in the chat view while it's on.

**Root cause:** `PUT /api/settings/yolo` mutated the in-memory `settings` singleton only; the `app-settings.json` overlay (`persist_setting`/`_apply_persisted_overrides`) whitelisted `browser_binary` alone. On restart the field's `False` default won.

**Fix:** `yolo_mode` added to the overlay whitelist; `set_yolo_mode` now calls `persist_setting` and returns 409 when `AGENTOS_YOLO_MODE` is env/.env-pinned (same contract as `browser_binary`). Function-level `from ..config import env_pinned, persist_setting` preserved so the `settings_overlay` test fixture (monkeypatches `config.env_pinned`) still applies. Chatview gets a pinned danger strip above the message area ("YOLO mode is on — tools run without approval"); `SettingsOverlay.toggleYolo` dispatches `caberos:yolo-mode` so the banner updates live without remount. Verified live: enabled → restarted the packaged app → `GET /yolo` returns `true`.

**Tests:** `test_yolo_persists_across_overlay` (PUT → file → overlay re-apply → off persists as explicit `false`), `test_yolo_put_refused_when_env_pinned`.

### B46 — YOLO toggle is global but sits in a per-agent panel (FIXED → per-agent flag)

**Symptom (2026-10-06, operator report):** "why is yolo mode set for every agent" — the toggle card sits atop the agent-scoped Capabilities tab, but `settings.yolo_mode` bypasses approvals for *all* agents.

**Fix:** `AgentConfig.yolo_mode` (versioned — a toggle writes a new AgentVersion, so "when did this agent go unsupervised" is auditable). Mediator bypasses when `settings.yolo_mode or agent_config.yolo_mode`; `agent_config` is always the parent config so the flag also covers the agent's sub-agent calls. `PUT /api/agents/{id}` accepts `yolo_mode`; `GET` returns it. The overlay card now writes the agent field and reads "for this agent only"; when the global flag is on it shows "Forced on for all agents" with a **turn off global override** action (the global `/api/settings/yolo` endpoints stay for env/ops use). Chatview banner fires on `global OR agent`.

**Tests:** `test_agent_yolo_skips_approval_gate` (yolo agent executes approval-gated calls without asking), `test_agent_yolo_off_still_gates` (default config still parks on `_await_approval`). Verified live: global reset to `false`, per-agent PUT created version 10 with the flag on, other agents unaffected.

### B47 — Notifications carry no agent context or content; inbox grows forever; quiet hours silence blocking approvals (FIXED)

**Symptom (2026-10-06, operator ask):** "can it be more detail like from which agent and a brief of content?" — every ping read "Run completed" / "An agent is waiting…" with no agent name and no hint of what happened. Audit also found: `Notification`/`NotificationDelivery` had no retention (append-only forever), and quiet hours suppressed `approval_required` — a blocked run could stall silently overnight.

**Fix:**
- `Notification.agent_id` + `agent_name` (snapshot at emit — survives renames/deletes, no join). Emitters pass `agent_id`; name resolved in `create_notification`. Badge renders beside the title in inbox + toast.
- Content briefs per event: `run_completed` carries the first ~160 chars of the final assistant reply (`excerpt_reply` queries `Message`); `run_failed` the one-lined error; `approval_required` a `call_brief(payload)` — capability + headline arg + `(+N more)` for batches; `elicitation_required` keeps the question. `one_line()`/`call_brief()` helpers in `notifications.py`.
- `prune_notifications(db, max_age_days=30)` runs at gateway startup (`main.py` lifespan) — deletes old notification + delivery rows via `julianday` compare (mixed timestamp formats can't dodge the cutoff).
- `HITL_TYPES = {approval_required, elicitation_required}` pierce quiet hours in the delivery coordinator; explicit per-type mutes still win. Settings copy updated to say approvals still reach you.

**Deploy-time crash caught (same class as the timestamp bugs — test DBs never exercise the patch path):** `sqlite_backend.add_column` whitelists column types; `VARCHAR(64)` wasn't in it → gateway died in `init_db` on first boot of the installed app. Fixed to `VARCHAR(255)` + explicit `CREATE INDEX` for `agent_id` (ALTER doesn't create indexes for existing DBs). Tests pass because fresh test DBs go through `create_all` — a schema-patch smoke against a real DB copy is still a gap.

**Also observed during deploy:** a leftover dev `uvicorn` squatting on :8081 — packaged app silently talked to stale code (B42 class again; killed it).

**Tests:** `test_agent_attribution_snapshots_name`, `test_prune_notifications_ages_out_rows_and_deliveries`; vitest `quiet hours do NOT silence approval_required`. Verified live: columns + `ix_notifications_agent_id` in the app DB, gateway healthy after patch.

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
