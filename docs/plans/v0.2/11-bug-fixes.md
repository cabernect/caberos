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
`test_skills_v6.py::test_detail_usage_lists_runs_pinning_revision`.
Verified live: `algorithmic-art` detail → 200 with 11 usage rows.

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
