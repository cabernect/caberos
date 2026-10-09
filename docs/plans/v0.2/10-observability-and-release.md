# v0.2.0 Observability and Release Hardening

> Release hardening is a separate final workstream — the release/security/
> restore-point sections below are NOT completed by the W10 observability work.

## Outcome

Operators can explain what every complex v0.2 run used, changed, produced, and cost, and the signed desktop/Docker releases reproduce the verified behavior on clean and upgraded installations.

## Per-model-call accounting

A Run may use several providers/models. Store each call:

```text
ModelCall
  run_id
  plan_step_id?
  purpose: reasoning | embedding | reranking
  provider_id
  model
  tokens_in
  tokens_out
  thinking_tokens
  cached_tokens
  cost
  latency_ms
  status
  error?
```

Provider/model filters match runs containing at least one matching call. Spend/latency aggregate calls rather than assigning one provider to an entire run.

**Non-run model calls.** `run_id`/`agent_id` are non-nullable today — but embedding calls (W7's `embedding_calls` ledger: index/ingest/repair/validate/query), provider save-time validation probes, memory auto-extract, and any future system jobs call models outside runs. W10 unifies this: either fold `embedding_calls` into `ModelCall` (via `purpose` + nullable run context) or keep the separate ledger and build a **platform spend** view — all model spend grouped by kind (agent chat | embedding | probe | …), so Observability stops being agent-only. `/api/spend` stays agent-scoped; embedding spend already surfaces on the Vault index surface (`GET /index.embedding_spend`, per-generation `cost`/`tokens_in`).

## Tool status

Persist and render distinct states:

```text
pending
awaiting_approval
running
completed
denied
failed
timed_out
interrupted
```

Runtime/extraction errors never display as syscall denial. UI reason and audit record agree.

## Integrated trace

Link Execution Manifest, Plan Steps, model calls/fallback, capability load state, terminal sessions, browser actions/evidence, Vault retrieval/citations, Artifact revisions, approvals/elicitation, Schedules, and notification deliveries.

Do not leak credentials, cookies, browser storage, secrets, or unrelated private document text.

## Filters

Provider/model/purpose, agent, trigger/Schedule, channel, Plan, capability/status/effect, browser session/profile, Artifact format, retrieval mode/degradation, and time range.

## Migration

- Create a restore point before v0.2 schema migration.
- Preserve v0.1.9 agents, sessions, messages, runs, audit, Vault, skills, schedules, notifications, credentials, and workspaces.
- Migrate built-in/global/local Skills without authority expansion.
- Preserve existing citations and rebuild only derived indexes.
- Failed migration leaves prior state recoverable.

## W10 observability — implemented decisions

Settled during implementation (stages 1–5, branch `feat/v0.2.0-observability`):

- **Unified ledger.** `model_calls` is the single table; `embedding_calls` is dropped. `kind` is the transport/domain (`chat`, `embedding`, `probe`, `extract`, `title`), `purpose` the intent (`reasoning`, `embedding`). Embedding provenance lives in `detail` (`resource_id`, `generation_id`, `operation`, `chunk_count`). Non-run calls carry `run_id`/`agent_id` NULL — probes are platform-scoped, extraction/title calls keep the agent (and run for extraction). `ModelCall.run_id` is an indexed nullable string reference, intentionally **not** a DB foreign key: six orphan rows existed in the field and ledger records must survive run deletion. DB-enforced integrity is traded for durability; application-level conversation deletion still deletes model calls explicitly, unchanged.
- **Two spend scopes, honestly named.** `GET /api/spend` defaults to `scope=agent` — the historic `Run`-totals shape for backward compatibility (legacy pre-ledger runs keep showing). `scope=platform` reads ledger calls only, includes runless/deleted-run calls, and excludes positively identified test runs. The two totals are not algebraically equal by design; the UI says so.
- **Thinking tokens are reported, not computed.** `thinking_tokens` is preserved `None` vs explicit `0`, never automatically added to `tokens_out` (some providers already include it), and displayed as "Not reported" when NULL.
- **Correlation is exact, never temporal.** `call_id` + `sub_agent_id` on audits, approvals, elicitations, terminal sessions, artifact revisions, and first-citation run sources. Children join parents only on the exact pair; NULL legacy rows stay rootless. A fast tool may finish before a domain row exists — in-flight state is SSE-only, not persisted.
- **Audit timestamps.** `audit_records.created_at` is additive: legacy rows stay NULL (`estimated_time` on the timeline), new rows get real UTC. Nothing backfills fabricated time.
- **Redaction is a read boundary.** Stored rows are untouched; the API projects safe payloads — per-capability allowlists, recursive secret-key rejection, regex redaction before truncation, fail-closed on malformed/sensitive bodies. Flat legacy lists (`audit_records`, `messages`, `model_calls`, `manifest`) go through the same projector as the timeline.
- **Deferred by design.** No browser-session filter (no durable session identity exists — sessions are derived, not stored). No Plan-step linkage or model fallback events (no Plan storage yet). No third tool table. Historical rows untouched.

## Release verification

Automated:

```bash
cd backend && uv run pytest -v
cd backend && uv run ruff check src/ tests/
cd backend && uv run ruff format --check src/ tests/
cd frontend && npm run lint
cd frontend && npm test
cd frontend && npm run build
cd frontend/src-tauri && cargo test
cd frontend/src-tauri && cargo check
```

Also require existing Playwright E2E verification, packaged-runtime tests, security tests, Docker parity, clean desktop installation, v0.1.9 upgrade, signed updater, and release tag/version/commit verification.

## Security scanning (W10 scope)

Add `.github/workflows/security.yml` — runs on all PRs (any base) + weekly schedule:

- `dependency-review-action` — fails PRs that add vulnerable deps
- `osv-scanner` — CVE scan across `uv.lock`, `package-lock.json`, `Cargo.lock`
- `gitleaks` — secret scanning of commit history
- `zizmor` — static analysis of workflow files (template injection, over-privileged tokens, unpinned actions)
- `trivy` — scan the Docker image for OS + dependency CVEs
- Enable ruff `S` rules (bandit-derived) in the existing lint step

Repo settings (no code): Dependabot alerts + security updates (scans main's manifests, opens fix PRs), secret scanning + push protection, GitHub code scanning default setup.

CodeQL decision needed: default setup only scans the default/protected branches — either protect `feat/**` via ruleset (also blocks force-push/deletion of umbrella branches) or use advanced setup with unrestricted `pull_request` triggers. Rust extraction needs a successful Tauri build — flag if flaky on CI.

## Manual smoke

- Clipboard image and attachment previews
- DOCX/PPTX/XLSX/PDF create/preview/revise/restore/export/conflict
- Managed browser first-use install, isolated research, persistent login/revoke
- Plan create/revise/approve/execute/deviate
- Skill Builder draft/validate/publish/shadow
- Local hybrid retrieval/re-index/fallback
- Background terminal read/complete/close/cleanup
- Schedule restart/sleep/approval
- Native/browser notification suppression/deduplication
- Provider/model spend and integrated trace
- Signed updater from v0.1.9

## Done when

All umbrella release gates pass, documentation states real limitations, and the exact signed artifacts are built from the verified v0.2.0 merge commit.
