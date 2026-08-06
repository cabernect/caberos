# 10 — Testing hardening

**What to build:** The test suite is comprehensive enough to trust the system. Coverage targets are met. Security properties are tested as behaviour (path escape rejected, cross-contact memory impossible, sandbox containment holds). An end-to-end test runs against a real model and a real sandbox. This is the final quality gate before v0.1 is releasable. Tests were written incrementally in each ticket, but this ticket hardens the suite, fills gaps, and adds the integration tests that were deferred.

**Blocked by:** 09 — Observability + spend (needs all features complete so the full suite can be tested end-to-end).

**Status:** ready-for-agent

**Note (revised after 01-05a):** Write each ticket's security tests (path escape, sandbox containment, cross-contact isolation) as that feature lands, not deferred entirely to this ticket. This ticket hardens/fills gaps and adds the E2E tests, it doesn't start security testing from zero.

- [ ] Coverage targets: core modules (harness, syscall, pipeline, sandbox, memory) at 80%+ coverage. API routes at 70%+. Frontend components have basic render tests.
- [ ] Security tests (behavioural, not implementation):
  - [ ] Path escape: `file.read("../../etc/passwd")` → rejected with denied audit record (path escapes workspace)
  - [ ] Absolute path: `file.read("/etc/passwd")` → rejected
  - [ ] Cross-contact memory: Contact A stores a fact → Contact B queries → gets nothing (subject comes from session, not model)
  - [ ] Model supplies contact_id: `memory.recall(contact_id="someone_else")` → denied (no contact_id parameter in schema)
  - [ ] Sandbox containment: `shell.run("cat /etc/passwd")` → blocked by sandbox (no host file access)
  - [ ] Sandbox network: `shell.run("curl http://example.com")` → blocked (no host network by default)
  - [ ] Clean env: `shell.run("env")` → no host secrets in output
  - [ ] Approval bypass: agent calls `require_approval` capability without approval → syscall layer blocks, no execution
- [ ] Integration tests (E2E):
  - [ ] Full run: inbound message → pipeline → harness → model (scripted double) → tool call → syscall → sandbox → result → final answer → audit. One test, all real components except model.
  - [ ] Real model smoke: one test against a local Ollama model (if available) — verifies tool-calling reliability with a small model. Non-deterministic, excluded from default suite, run manually before release.
  - [ ] Heartbeat: scheduler fires → run created with `trigger=heartbeat` → result appears in history tagged as heartbeat.
  - [ ] Approval: agent calls `require_approval` capability → approval request created → operator approves → run resumes → tool executes.
  - [ ] Memory round-trip: agent stores fact → new session → agent recalls fact → correct.
  - [ ] Versioning: save agent → modify → save → diff → rollback → active config matches v1.
  - [ ] Compaction: context exceeds max_context_tokens → compaction fires → summary created → context shrinks → run continues.
  - [ ] Cost limit: run exceeds max_cost_per_run → fallback applied → run stops.
  - [ ] Turn limit: model keeps calling tools → exceeds max_turns_per_run → fallback applied → run stops.
- [ ] Frontend tests: component render tests (React Testing Library), SSE event handling tests (mock SSE stream), form validation tests.
- [ ] Release smoke test: one manual end-to-end pass against a real model and a real sandbox before release — dashboard chat, shell command, file read/write, email read via a real connector, heartbeat run, approval flow.
