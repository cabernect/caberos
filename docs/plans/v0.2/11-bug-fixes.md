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
