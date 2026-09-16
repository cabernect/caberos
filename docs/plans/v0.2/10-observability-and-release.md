# v0.2.0 Observability and Release Hardening

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
