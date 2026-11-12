# Preliminary Regression Run — Not Final Release Acceptance

Date: 2026-11-05. Worktree: `feat/v0.2.1`, uncommitted working tree.
Scope: v0.2.1 automated gates only — this record authorizes no commit,
push, tag, or release. Per `12-integration-and-release.md`.

## Status Correction

The recorded commands/counts are an earlier regression checkpoint only. W7 is
OPEN; W9, W10, and W11 remain included workstreams, not implicitly deferred.
Final W12 acceptance runs after their implementation and W7 integration.
Suite success does not establish individual acceptance stories or security
coverage. The broad coverage statements below are historical and must be
replaced by scenario-specific evidence before release acceptance.

## Environment

- macOS / Darwin 27.0.0; backend Python 3.12.11, SQLite (aiosqlite).
- Frontend Node 22.22.3, Vitest 5.0.5, Vite 8.3.5, tsc.
- Managed Chromium binary present — live CDP browser tests ran for real
  (39/39, zero skips).

## Backend Gates

```bash
cd backend
uv run ruff check src/ tests/          # All checks passed!
uv run ruff format --check src/ tests/ # 313 files already formatted
uv run pytest -q                        # 1511 passed in 185.66s
```

Result: **PASSED** — 1511/1511. Warnings are pre-existing deprecations
(httpx `verify=<str>` and per-request cookies, one aiosqlite
teardown-thread warning, one pydantic ReadOnly notice). No real network
egress: provider/search/HTTP traffic used `httpx.MockTransport` or
recorded fixtures; DNS was monkeypatched.

## Frontend Gates

```bash
cd frontend
npm run lint    # 0 errors — warnings only (pre-existing require-yield
                # in notificationStore.test.ts, exhaustive-deps in
                # RuntimeInstallDialog.tsx)
npm run build   # tsc -b && vite build — clean, 2.47s
npm run test    # 37 files, 268 tests — all passed
```

Result: **PASSED**.

## Acceptance-Matrix Status Summary

Recorded against `test_plan/acceptance-matrix.md`:

- **S01/S03** ✅ covered — `test_netpolicy.py` (46), `test_network_settings.py` (4).
- **S02/S04** ◐ partial — navigation + findings enforced/documented in
  `test_result/2026-11-05-network-policy.md`; browser subresource coverage
  and hostile-MCP-metadata simulation are recorded residual risks, not
  claimed covered.
- **Q-rows** — covered by `test_search_providers.py` + ToolsTab component
  tests (12) and earlier `2026-11-04-search-provider-reuse.md` evidence;
  live real-provider QA not run (scripted adapters only, per plan).
- **C/W/V/T/B/M rows** — covered by the W1–W6 suites inside the 1511-test
  backend run and the 268-test frontend run.

## Not Run (honest exclusions)

- **R02 Postgres** — no isolated Postgres service configured; SQLite only.
- **R03 packaged desktop** — no `cargo test`, `desktop:build`, or Tauri
  native QA performed (permission/mic/updater paths untested).
- **Real-provider egress** — no live Tavily/Exa/Brave/Firecrawl/media
  calls; scripted fixtures only. Requires explicit per-test consent.
- **W11 remote terminal/cloud lease** scenarios — implementation pending;
  E-rows unexercised except where local-backend parity was already covered.
- **STT/TTS (A-rows)** — included v0.2.1 speech workstream not yet implemented.

## Migration/Failure Gate Notes

- Repeated init covered by suite fixtures (fresh + patched schema paths).
- Tool-binding persistence/migration, provider key custody (blank keeps,
  explicit delete-key action), DDGS option compatibility, and encrypted
  credential non-export covered by search/provider tests above.
- Private-network fetch policy is new behavior — see the W7 review record
  for the compatibility note (agents fetching intranet URLs will now see
  an explicit block + allowlist hint rather than silently succeeding).
