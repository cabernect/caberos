# W12 — Integration & release acceptance run (2026-11-09)

Scope: automated gates + acceptance-matrix mapping on `feat/v0.2.1` at
`65cc2d4`. This records evidence; it authorizes no tag, push, or release.
Remote-terminal scenarios are **not run** — W11 gates 3–7 are deferred by
operator decision (no verifiable remote infrastructure); per the plan,
no selector-only placeholders exist to exercise.

## Environment

- macOS / Darwin (arm64); Python 3.12.11, SQLite (aiosqlite).
- Node 22.x, Vitest 5, Vite 8; Rust toolchain for `src-tauri`.
- Dev DB `backend/data/agentos.db` migrated through `binding_revision`.

## Automated gates — PASS

```bash
cd backend
uv run ruff check src/ tests/          # All checks passed
uv run ruff format --check src/ tests/ # already formatted
uv run pytest -q                       # 1750 passed, 4 skipped (3m00s)
cd frontend
npm run lint                           # 0 errors (warnings pre-existing)
npm run build                          # tsc + vite — clean
npm run test                           # 268 passed (37 files)
cd frontend/src-tauri && cargo test    # 4 passed
```

Notes: the run initially showed one failure —
`test_strict_mode_via_backend` used `/tmp` as a strict workspace, which
W7's Seatbelt deny-roots correctly refuse (pre-existing stale test since
W7). Fixed in `65cc2d4` to use a real workspace fixture; its file is
24/24 green and included in the count above. Skips are platform-gated
(linux/windows-only paths), unchanged.

## Acceptance matrix mapping

Evidence references per workstream; rows without a live record remain
covered by suite tests only.

| Matrix rows | Status | Evidence |
|---|---|---|
| C01–C05 compaction UX | PASSED (suite) | W1 delivered earlier; summary/CAS/coverage tests green |
| W01–W11 workspaces | PASSED (suite) | pinning columns + resolver/mediation tests green |
| V01–V04, T01–T06 vault/tabular | PASSED (suite) | index/inspection tests green |
| B01–B04 bindings | PASSED | `test_tool_bindings.py`, restart persistence |
| M01–M04 media | PASSED (suite) | image dispatch/ledger tests green |
| Q01–Q07 search services | PASSED (fixtures) | `test_search_providers.py` + `2026-11-04-search-provider-reuse.md`; scripted adapters — **no live-provider verification claimed** |
| A01–A12 speech | PASSED + live | `2026-11-09-speech.md` — OpenRouter+Gemini live-verified; Tauri mic prompt operator-confirmed; ElevenLabs live 402 = provider-side plan gate, not a defect |
| E01 Auto/explicit local backend | PASSED (this host) | `test_terminal_binding.py` — save-time foreign refusal, honest unavailable states, no fallback |
| E02 readiness/experimental | PASSED (this host) | backend_catalog rows; MXC experimental wording surfaced |
| E03–E11 remote SSH/Daytona/Modal | **NOT RUN — deferred** | requires fixture host + provider accounts |
| Story 12–13 (remote lifecycle) | **NOT RUN — deferred** | same |
| S01–S10 security | per matrix/descope | `2026-11-05-network-policy.md`, `2026-11-05-w7-execution-mcp.md`; S02/S03 deferred by re-scope; S05 bwrap/MXC not run on non-native platforms |

## Migration & failure gates

- Additive `terminal_sessions.binding_revision` applied on this dev DB;
  repeated `init_db` idempotent (sqlite patch list; postgres mirror added).
- Old terminal rows keep `binding_revision = NULL` → treated as legacy
  unpinned, matching "existing local sessions receive a compatible local
  pin; never migrate to remote" — they are simply local rows.
- Encrypted search/speech credentials unchanged; settings endpoints make
  no provider calls (`test_settings_endpoints_make_no_provider_calls`).

## Explicitly not run

- Isolated-port browser QA sweep (wide/narrow layout, keyboard/IME,
  console errors) — dev-instance checks only so far.
- Postgres integration tests — no configured service; per plan, recorded
  as not run, not passed.
- Packaged-build verification (Tauri `desktop:build`, updater restart).
- Real-provider media/compaction egress QA — requires explicit consent
  per test.

## Remaining risks for an actual release

1. Linux/Windows native backend readiness is unverified here — bwrap/MXC
   selection paths are code-reviewed but not executed.
2. Remote terminal scope is deferred; release notes must not claim
   SSH/cloud execution.
3. Speech pricing is intentionally uncalculated — receipts carry units,
   not dollars.
4. W7 S06–S09 items (credential-leak sweeps, CSRF fixtures, resource
   bound evidence) remain open in the matrix; baseline scope was the
   operator's accepted bar — a release decision should confirm that bar
   still stands.
