# W11 Testing-Agent Handoff

## Goal And Baseline

Independently test Runtime Readiness on `feat/v0.2.0-runtime-readiness`.
Baseline: `f4c323c`, including accounting fix `3a77cca`, OAuth discovery
`0d1267a`, and scheduler restart-note fix `c7b7be2`.

The last local gate passed: 1121 backend tests, 156 frontend tests, backend
Ruff check/format, and frontend lint/build. These are prior results, not the
testing agent's independent verdict.

Use the comprehensive [W11 acceptance plan](11-runtime-readiness-test-plan.md).
This handoff supplies the runnable environment, priority cases, and boundaries.

## Test Environment

- Frontend: `http://127.0.0.1:15173`.
- Backend: `http://127.0.0.1:18081`; health: `/health`.
- Frontend proxies `/api` and `/health` to the QA backend, not port 8081.
- QA root: `/tmp/w11-qa/handoff/`.
- Database: `/tmp/w11-qa/handoff/data/agentos.db`.
- Login: read `/tmp/w11-qa/handoff/login.txt` locally; QA account only.
  Do not copy passwords, cookies, or session tokens into reports or the repo.
- Environment/restart configuration: `/tmp/w11-qa/handoff/env.sh`.
- Backend log/PID: `/tmp/w11-qa/handoff/backend.log` and `backend.pid`.
- Frontend log: `/tmp/w11-qa/vite.log`.
- Setup evidence: `.scratch/w11/handoff-env-smoke.log`.

The environment uses a fresh QA database and separate workspaces, knowledge,
agent homes, secrets, skill stores/drafts, and a copied built-in skills directory.
Managed runtimes, model-catalog snapshots, and browser runtime data belong under
the QA database's parent directory. The normal macOS HOME is retained for Chrome.

Outbound proxy settings deliberately refuse external connections. Catalog
auto-refresh is disabled in this QA environment. No model providers, paid model
calls, runtime install jobs, or real OAuth grants are supplied.

Before testing, verify backend and frontend `/health` return 200, log in, and
confirm the dependency/job APIs respond without 500s. Reuse running processes.
If a restart is needed, inspect `backend.pid` and the listener before stopping
only the owned QA backend; source `env.sh` and use:

```bash
# From the repository's backend directory, after confirming port 18081 is free:
source /tmp/w11-qa/handoff/env.sh
uv run --frozen --no-sync uvicorn agentos.main:app \
  --host 127.0.0.1 --port 18081 --timeout-graceful-shutdown 5
```

If the QA frontend is absent, run from the repository's frontend directory:

```bash
VITE_API_PROXY=http://127.0.0.1:18081 \
  npm run dev -- --host 127.0.0.1 --port 15173 --strictPort
```

## Safety And Exclusions

- Never stop/restart or write through the main services on 8081/5173.
- Never use the production database, regular workspaces, personal agent homes,
  production provider credentials, or real MCP accounts.
- Do not change global PATH, uninstall system tools, invoke sudo/package
  managers, or alter unrelated `scripts/dev.sh`.
- The user's refusal means this handoff is NOT download/install permission.
  Obtain explicit approval naming dependency/version/source/size/destination
  before enabling outbound access or approving a real installer job.
- Do not run paid model calls or real OAuth authorization. Use scripted
  responses and local fake HTTP servers for behavioral tests.
- Git MCP combined preparation and historical-cost backfill are excluded.
  Existing recorded costs are not repriced.
- Chat intentionally displays the same scalar zero for unresolved and genuine
  zero. Detailed receipts/observability retain the distinction.
- Frontend rework follows W11; it is not deferred.
- Do not commit or push. Return findings and evidence to the lead/user.

## Priority Cases

| ID | Action | Expected Evidence |
|---|---|---|
| H01 | Open global Settings -> General | Optional Tools & Runtimes is reachable; no internal Model Catalog maintenance card |
| H02 | Inspect readiness; Re-check; close/reopen settings | Truthful status/source/version; no installs or unrelated system changes |
| H03 | Observe idle settings requests for at least 15 seconds | One initial jobs fetch; no recurring jobs polling while idle; explicit Re-check may fetch again |
| H04 | Observe notification SSE; exercise a controlled disconnect/reconnect | Healthy SSE has no recurring inbox poll; only leader polls during outage; reconnect catches up and stops fallback |
| H05 | Preview an install with a missing-runtime fixture, then decline | Exact version/source/destination/verification shown; no install POST or download before consent |
| H06 | Run consent, progress, cancel, failure, retry, and reload scenarios with mocked I/O | Bounded jobs; truthful terminal states; active-only polling; previous working installation preserved |
| H07 | Remove only a fixture-owned cached executable, then attempt stdio use | Stale runtime is rechecked; actionable missing-runtime result; no silent reinstall/incompatible fallback |
| H08 | Exercise real MCP initialize against a local fake 401 Bearer challenge | Default OAuth consent configuration persists; Connect OAuth is offered; no automatic metadata/token fetch or redirect |
| H09 | Exercise Basic/bare 401/malformed challenges, 403/500, and another URL | No guessed OAuth configuration; existing operator configuration is not overwritten |
| H10 | Use scripted native OpenAI and explicitly mapped proxy accounting cases | Native tier estimates resolve; proxy unsupported tier basis remains unknown; genuine reported zero preserved |
| H11 | Reconcile a fixture running schedule with an existing skip note twice | Cancelled with finish time; both skip/restart reasons survive; no duplicate restart reason |
| H12 | Exercise General/install dialog at 375/768/1024/1440, light/dark, keyboard | Readable preview/progress/errors, usable consent controls, no stuck polling, record overflow and console errors |

A synthetic `qa-oauth-mcp` may be seeded for checking the existing consent UI.
It points at `http://127.0.0.1:18082/mcp`, not a real provider. A seeded
`oauth_config` proves rendering only; H08 requires actual challenge discovery
using a controlled fake server or the real-SDK regression test.

Known layout limitation: at 375px the existing MCP header pushes action controls
off-screen. Record it as a known frontend-rework item, not a fresh discovery or
a mobile usability pass. Do not silently enlarge W11 into a frontend rewrite.
The Agents page's active-run poll is separate from notification/install polling;
do not assert that every application poll was removed.

## Real Installer Verification: Permission Required

Host coverage here is macOS ARM64 only. Windows/x64 claims require those hosts.
Pinned distributions are defined in
`backend/src/agentos/defaults/runtime-recipes.json`:

| Tool | Version | Source | Recorded Archive Size |
|---|---|---|---|
| Node.js | 24.21.0 | nodejs.org release archive | Unknown; installer maximum 256 MiB |
| uv/uvx | 0.12.24 | astral-sh/uv GitHub release | 14650202 bytes |
| Git | 2.53.0; Dugite v2.53.0-4 | desktop/dugite-native GitHub release | 62348987 bytes |

System Node/uv/Git may already be Ready. Reuse is correct behavior and does NOT
prove private installation. Never uninstall them to manufacture a missing host.
For missing-runtime tests, use the registry's injected `finder` seam inside an
isolated test fixture. Keep actual archive/checksum/health I/O real only after
approval, and label discovery simulation explicitly. Do not use fake health
results or mocked downloads as evidence of real-install success.

An approved standalone fixture can instantiate
`RuntimeDependencyRegistry(data_dir=qa_runtime_root, finder=lambda _: None,
platform_key="darwin-arm64")` and `RuntimeInstaller(registry=registry,
data_dir=qa_runtime_root, platform_key="darwin-arm64")`, where
`qa_runtime_root` is `/tmp/w11-qa/handoff/data/managed-runtimes`.
Leave production code and global PATH unchanged.

For each approved real install, capture the frozen plan, exact URL/digest,
destination, downloaded bytes, job lifecycle, health versions, managed pointer,
and post-install readiness. Verify no outside-QA files changed. Reopen/recheck
must rediscover a working managed binary. Test cancellation/failure without
destroying a previous installation. Do not delete fixture data until evidence
is collected; never remove a system/user-owned installation.

If approval is absent, mark live install cases NOT RUN, not PASS or FAIL.

## Automated Regressions And Results

Run focused tests first, with roots separate from the running QA server:

```bash
# From the backend directory:
source /tmp/w11-qa/handoff/env.sh
test_root=$(mktemp -d /tmp/w11-regressions.XXXXXX)
mkdir -p "$test_root/data"
cp -R /tmp/w11-qa/handoff/builtin-skills "$test_root/builtin-skills"
export AGENTOS_DB_PATH="$test_root/data/agentos.db"
export AGENTOS_SECRET_KEY_PATH="$test_root/data/secret.key"
export AGENTOS_WORKSPACE_ROOT="$test_root/workspaces"
export AGENTOS_KNOWLEDGE_ROOT="$test_root/knowledge"
export AGENTOS_AGENT_HOME_ROOT="$test_root/agenthomes"
export AGENTOS_SKILLS_STORE_ROOT="$test_root/skills-store"
export AGENTOS_SKILLS_DRAFTS_ROOT="$test_root/skills-drafts"
export AGENTOS_SKILLS_DIR="$test_root/builtin-skills"
uv run --frozen --no-sync pytest -q \
  tests/test_mcp.py tests/test_mcp_oauth_refresh.py tests/test_scheduler.py \
  tests/test_call_accounting.py tests/test_runtime_installer.py \
  tests/test_dependencies.py tests/test_mcp_stdio_resolver.py
```

Full gate commands are in the main W11 acceptance plan. Keep the separate
automated-test environment for those commands. **Note:** when running the
catalog-accounting suite that needs the default/auto-refresh toggle, unset
`AGENTOS_MODEL_CATALOG_AUTO_REFRESH` first — the running QA server pins it
to `false` in `/tmp/w11-qa/handoff/env.sh`. Never point pytest at the running
QA or production database; fixtures must use their temporary DBs.
Do not rerun a costly full gate merely to restate the existing green baseline.

Write an independent report under
`docs/plans/v0.2/test_result/11-runtime-readiness-independent-test-results.md`.
Record source commit, platform, effective isolation paths, and each case's
PASS/FAIL/NOT RUN/BLOCKED status. Include exact repro steps, expected/actual
behavior, response/job evidence, screenshots, console/network traces, and
redacted logs. Separate simulated checks from real installer execution.
Do not overwrite the existing implementation report or claim full W11
verification while required live checks remain unexecuted.
