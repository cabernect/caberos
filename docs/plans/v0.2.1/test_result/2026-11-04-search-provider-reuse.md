# Provider Reuse And Initial Tavily Slice

Date: 2026-11-04. Worktree: `feat/v0.2.1`, base `091077e`; implementation remains
uncommitted. Existing planning, chat scroll/copy/image tests, and frontend example
changes were preserved. No commit, push, release, or live search probe performed.

## Scope

Reuse `Provider` rows/Fernet keys with model/search scoping. Configure Tavily
inline in Tools, bind it without a model, preserve free DDGS options, and keep
existing capability grants/approval/audit mediation. No connection table or
schema migration. Exa/Brave API adapters, speech, and terminals are not included
in this implementation slice.

## Environment And Isolation

- macOS / Darwin 27.0.0; backend Python 3.12.11, SQLite 3.51.3.
- Frontend Node 22.22.3, Vitest 5.0.5, Vite 8.3.5.
- Backend pytest uses disposable in-memory SQLite and temporary filesystem roots.
  Search HTTP responses use `httpx.MockTransport`, not a real provider.
- Browser checks use the actual ToolsTab/ConfirmProvider in an isolated DOM
  fixture at `127.0.0.1:5173/login`, with in-memory API replacements. This is
  component verification, not authenticated full-stack QA or a QA backend.
  No normal development database was replaced or written by the fixture.

## Commands And Results

| Command | Exit | Result |
|---|---|---|
| `uv run ruff check src/ tests/` | 0 | Passed |
| `uv run ruff format --check src/ tests/` | 0 | 308 files already formatted |
| `uv run pytest -q` | 0 | 1437 passed; 44 warnings |
| `npm test` | 0 | 36 files, 255 tests passed |
| `npm run build` | 0 | TypeScript and production build passed |
| `npm run lint` | 0 | Existing warnings only |
| `git diff --check` | 0 | Passed |

Backend warnings concern existing httpx cookie/SSL deprecations and Pydantic
ReadOnly handling. Frontend warnings concern Vite config loading, bundle/dynamic
import notices, existing hook dependencies, require-yield, and Fast Refresh.

## Acceptance Evidence

| IDs | Outcome | Evidence / limits |
|---|---|---|
| B02, B03, Q06 | Scripted paths passed | Model/service incompatibility and missing keys fail closed. Denied approval, key rotation, reset, or provider deletion while pending never dispatches the tool. |
| B04, Q05 | Partial | Saved DDGS options still resolve and engine order is preserved. No live DDGS query or upgrade/restart fixture performed. |
| Q01 | Partial | Tavily credentials/options/binding configured in Tools. Exa/Brave API remain unimplemented. |
| Q02 | Partial | Ciphertext differs from plaintext; reads/audit targets do not expose keys; blank preserves, replacement rotates, explicit removal invalidates readiness. Restart/export review remains pending. |
| Q03 | Partial | Saving service providers schedules no model discovery. Opening/saving makes no search request. Synthetic probe requires consent. Probe rate limiting remains pending. |
| Q04 | Tavily fixtures passed | Success/empty, auth/quota/server/redirect errors, timeout, invalid/oversized data, and query/result bounds; no paid fallback or automatic retry. No live API compatibility assertion. |
| Q07 | Partial | Measured request and reported-credit receipts; invalid/nonfinite credits and missing prices stay unknown. No model-call or visited-source rows. Durable service accounting/rollups remain pending. |

Browser interactions verified inline Provider creation, provider-only binding,
password input clearing after save, zero automatic probes, and explicit
confirmation before a single mocked probe. Layout fit at 1280px and 390px.
Mobile screenshot inspected at `/tmp/caberos-tavily-tools-mobile.png` (ephemeral,
not a committed artifact). Early fixture failures were module-identity/z-index
issues in the synthetic host; the corrected fixture completed the interactions.

## Remaining Gates

- Review official Tavily API contracts and perform a consented real-provider
  smoke test; current HTTP fixtures alone do not establish compatibility.
- Complete Exa/Brave API adapters and the remaining W9 acceptance scenarios.
- Add probe rate limiting, broader service usage accounting, and cancellation
  accounting before treating W9 as release-complete.
- Verify authenticated full-stack/desktop workflows and Postgres behavior.
- Provider mutations and binding writes are separate existing API operations;
  a binding conflict can leave a reusable saved Provider row, not an atomic
  all-or-nothing form transaction.
- W7 network/MCP security and W8 release gates remain open.
