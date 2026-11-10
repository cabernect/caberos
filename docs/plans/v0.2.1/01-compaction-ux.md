# Manual Compaction UX

Status: proposed. Dependencies: existing summary/coverage implementation.

## Goal

Make `/compact` submission, progress, success, no-op, and failure unmistakable
without changing the summarization algorithm or creating a background job system.

## Existing Files

- `frontend/src/components/ChatInputBar.tsx` and its tests: command autocomplete,
  Enter handling, IME protection, context meter.
- `frontend/src/pages/Conversation.tsx`: command dispatch and pending state.
- `frontend/src/lib/api.ts`: compaction response type.
- `backend/src/agentos/api/chat.py`: manual endpoint and summary persistence.
- `backend/tests/test_compaction.py`: existing backend regression coverage.

## Interaction Contract

| Input/outcome | Expected behavior |
|---|---|
| Exact `/compact` + Enter | One request, not autocomplete-only selection |
| Partial `/comp` + Enter/Tab | Complete suggestion; make submit step clear |
| Shift+Enter or IME-confirming Enter | Preserve editor/composition behavior |
| Pending request | Status above composer; prevent duplicate submissions |
| `compacted=true`, no error | Show estimated before/after context |
| `compacted=false`, no error | Say no compaction occurred; do not claim failure |
| Nonempty response `error` | Visible failure, even with HTTP 200 |
| HTTP/network/409 failure | Safe explanation; explicit retry when appropriate |

Errors take precedence over success flags. Do not update the context meter from
an errored response. Retain backend reasons without exposing raw secret-bearing
provider payloads. Result labels say "estimated context tokens", not billed tokens.

## State And Concurrency

Use a small session-keyed state model: idle, pending, succeeded, unchanged, failed.
Capture agent id, session id, and a request identity before dispatch. Apply a
result only to that identity; switching conversations must never overwrite the
new conversation's context meter. Disable duplicate dispatch synchronously,
not only after a React state update.

While compaction is pending, prevent a conflicting local send to that session.
Audit existing server concurrency behavior against other tabs/automatic
compaction; preserve CAS rejection and fix demonstrated gaps rather than
assuming the local disabled composer serializes all clients.

Keep status outside the scrolling message list; use an accessible live region
without repeated announcements. Completion/error can remain until dismissal or
the next relevant action. Avoid a toast as the only evidence.

Navigating away or aborting a fetch does not prove server compaction stopped.
On return/reload, refresh persisted session context. Do not show an invented
live progress state after reload when the server exposes no such contract.

## Implementation Steps

1. Add a named response type including `error: string | null`. Test interpretation
   of success/no-op/error/HTTP failure without invoking a real provider.
2. Implement session-scoped request state and composer-adjacent status. Preserve
   token estimates on error; refresh persisted context after uncertain outcomes.
3. Fix exact-command Enter handling before generic autocomplete consumption.
   Preserve skill suggestions, keyboard navigation, multiline input, and IME.
4. Add request identity and rapid-submit/session-switch regression tests.
   Retain summary immutability, coverage, and concurrent-CAS backend tests.
5. Browser-verify all states using deterministic fixtures/intercepted responses,
   then optionally do consented real-model summary persistence/recall QA.

## Acceptance

- Progress is visible while scrolled far from the latest message, on narrow and
  wide layouts, and with keyboard/screen-reader status semantics.
- Exact command Enter submits once; rapid Enter cannot create duplicate requests.
- No-op and provider failure never masquerade as successful compaction.
- An agent/session switch cannot leak status or token counts into another chat.
- Reload reads actual saved summary state; old transcript messages stay intact.

## Non-Goals

No compaction algorithm rewrite, fabricated percentage progress, automatic retry
of potentially billable calls, or persistent job orchestration.
