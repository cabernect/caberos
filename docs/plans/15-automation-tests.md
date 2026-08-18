# Plan 14 — Automation Tests

## Goal

Lock in the bug fixes and features from the recent work session with automated tests so regressions are caught immediately.

## Current state

- **Backend:** 112 pytest tests pass. Covers config, providers, pipeline, harness, tools, guardrails, auth, elicitation, sandbox, syscall. No tests for the recent streaming/multi-run/session-switching fixes.
- **Frontend:** Zero tests. No test framework installed. No Playwright/vitest/jest. All frontend bugs (IME, session switching, multi-run streaming, token display) were verified manually via Playwright MCP.

## What needs coverage (from recent bug fixes)

### Backend gaps

| # | What | Why | Test approach |
|---|------|-----|---------------|
| B1 | Provider deletion clears agent model config | We fixed this — no test locks it in | API test: create provider → assign to agent → delete provider → verify agent's `model.provider_id` is `""` |
| B2 | Pipeline rejects when agent has no model configured | Fixed — was silently falling back to is_test | Pipeline test: agent with `model.is_configured == False` → `run_agent()` raises `ValueError("No model configured")` |
| B3 | Per-session lock allows concurrent runs for different sessions | Core design decision D25 — untested | Pipeline test: start 2 runs on different sessions of same agent concurrently → both complete, neither blocks |
| B4 | `stream_options: {"include_usage": true}` in streaming | Just added — ensures token counts are accurate | Unit test: verify LiteLLMAdapter passes `stream_options` in kwargs |
| B5 | Token fallback estimate includes thinking tokens | Just fixed — was only counting output text | Unit test: mock stream with no usage → verify `tokens_out` includes `len(full_thinking) // 4` |
| B6 | Stop run API (`POST /runs/{id}/stop`) | Used by frontend delete-session-while-running | API test: start run → stop run → verify status is "stopped" |
| B7 | Run status polling (`GET /runs/{id}`) | Used by frontend reconnect logic | API test: start run → poll status → verify "running" then "completed" |
| B8 | SSE event stream reconnect with `Last-Event-ID` | Core to multi-run support | API test: start run → read first N events → reconnect with Last-Event-ID → verify continuation |

### Frontend gaps (Playwright E2E)

| # | What | Why | Test approach |
|---|------|-----|---------------|
| F1 | Vietnamese IME input doesn't send on composition Enter | Fixed with `isComposing` check | Playwright: type with `insertText` simulating IME composition → press Enter during composition → verify message NOT sent → finish composition → press Enter → message sent |
| F2 | Session running spinner shows in sidebar | Fixed — spinner persists across session switches | Playwright: send message → verify spinner on session item → switch to another session → spinner still visible on running session |
| F3 | Switching to running session restores streaming | Fixed — `activeSessionRef` updated immediately | Playwright: start long run → switch to other session → switch back → verify streaming content visible and updating |
| F4 | New Chat doesn't kill running session | Fixed — removed `streamingStateRef = null` | Playwright: start run → click New Chat → switch back to running session → verify streaming still works |
| F5 | Concurrent runs in different sessions don't cross-contaminate | Fixed — multi-run Map | Playwright: start long run in session A → switch to session B → send message → verify session B shows its own response, not A's |
| F6 | Delete running session stops the run | Fixed — `handleDeleteSession` calls `stopRun` | Playwright: start run → hover session → click delete → verify session removed + spinner gone |
| F7 | Completed run shows as regular message (not streaming block) | Fixed — reload messages after `message_complete` | Playwright: send message → wait for completion → verify response is a `MessageRow` (hoverable, with cost badge), not a `StreamingMessage` |
| F8 | No duplicate thinking blocks on session switch | Fixed — filter run messages from API response | Playwright: start run with thinking → switch away → switch back → verify only ONE thinking block |
| F9 | Token display shows output tokens only | Fixed — removed input tokens from badge | Playwright: complete a run → verify cost badge shows `N tokens` where N = output tokens only |
| F10 | Agent list shows "no model" warning for unconfigured agents | Fixed — warning badge | Playwright: delete provider → verify agent card shows warning |
| F11 | Chat page shows "No model configured" banner + disabled input | Fixed — no isTest fallback | Playwright: agent with no model → verify banner + disabled send button |
| F12 | ModelSelect searchable combobox | New component — no test | Playwright: open settings → click model select → type search → verify filtered results → select → verify saved |

## Implementation plan

### Phase 1: Backend tests (extend existing pytest suite)

**Files to create/modify:**
- `backend/tests/test_run_manager.py` — new file for B6, B7, B8
- `backend/tests/test_pipeline.py` — add tests for B2, B3
- `backend/tests/test_providers.py` — add test for B1
- `backend/tests/test_litellm_adapter.py` — new file for B4, B5

**Run:** `cd backend && uv run pytest -v`

### Phase 2: Frontend E2E setup (Playwright)

**Install:**
```bash
cd frontend && npm install -D @playwright/test
npx playwright install chromium
```

**Files to create:**
- `frontend/playwright.config.ts` — config (baseURL: localhost:5173, webServer to start dev)
- `frontend/e2e/fixtures.ts` — shared fixtures (login, create agent, create session)
- `frontend/e2e/chat-ime.spec.ts` — F1
- `frontend/e2e/session-switching.spec.ts` — F2, F3, F4, F8
- `frontend/e2e/multi-run.spec.ts` — F5, F6
- `frontend/e2e/message-rendering.spec.ts` — F7, F9
- `frontend/e2e/model-config.spec.ts` — F10, F11, F12

**Run:** `cd frontend && npx playwright test`

### Phase 3: CI integration

- Backend: `cd backend && uv run pytest --cov=agentos --cov-report=xml`
- Frontend: `cd frontend && npx playwright test --reporter=github`
- Add to `.github/workflows/test.yml` (or local `scripts/test.sh`)

## Verification

```bash
# Backend
cd backend && uv run pytest -v

# Frontend E2E (requires dev servers running)
cd frontend && npx playwright test

# Both
./scripts/test.sh
```

## Priority order

1. **B1, B2** — model config fixes (highest value, simplest to write)
2. **B6, B7, B8** — run manager (core to streaming)
3. **F2, F3, F5** — session switching + multi-run (most bug-prone area)
4. **B4, B5** — token counting
5. **F1** — IME (edge case but user-facing)
6. **F7, F8, F9** — rendering correctness
7. **F10, F11, F12** — model config UI
8. **B3** — concurrent runs (harder to test, lower priority)
