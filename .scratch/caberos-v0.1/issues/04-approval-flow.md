# 04 — Approval flow

**What to build:** When the agent calls a capability marked `require_approval` (e.g. `shell.run` with dangerous commands, `email.send`), the syscall layer pauses the run and creates an approval request. The dashboard shows the pending approval inline in the conversation (and in an approvals queue). The operator approves or denies. If approved, the run resumes and the tool executes. If denied, the run continues with a "denied" result fed back to the agent. The agent learns it was denied and can adjust. This is the human-in-the-loop safety gate.

**Blocked by:** 03 — File operations + tool call visibility (needs the tool call block UI and the real syscall layer).

**Status:** ready-for-agent

- [ ] Approval request model: `ApprovalRequest` (id, run_id, capability_name, args JSON, status pending/approved/rejected, decided_by, decided_at, created_at). Already in the DB schema from ticket 01.
- [ ] Syscall layer approval gate: when a capability with `require_approval=true` is called, the syscall layer creates an ApprovalRequest, emits a `tool_call` SSE event with `status=pending` (showing "waiting for approval..."), and pauses the run using an asyncio Event. The run waits until the approval is decided.
- [ ] Approval API: `GET /api/approvals` — list pending approvals. `POST /api/approvals/{id}/approve` — approve. `POST /api/approvals/{id}/reject` — reject. Deciding sets `decided_by` (operator id) and `decided_at`.
- [ ] Frontend — inline approval: when a `tool_call` event arrives with `status=pending` and approval required, the tool call block shows the args and two buttons: "Approve" (green) and "Deny" (red). Clicking either calls the approval API. The block transitions to `running` (if approved) or `denied` (if rejected).
- [ ] Frontend — approvals queue: a page or sidebar showing all pending approvals across agents, with quick approve/deny. Accessible from the top bar (badge count).
- [ ] Agent feedback on denial: when denied, the syscall layer returns a "denied" result to the harness. The agent sees the denial in the tool result and can adjust its approach (try a different command, ask the user, etc.).
- [ ] `require_approval` configurable per capability grant: each `CapabilityGrant` on an agent has a `require_approval` flag. The operator can toggle it per agent per capability. e.g. `shell.run` requires approval for one agent but not another.
- [ ] Audit: approval decisions are recorded in the audit trail (who approved/denied, what capability, what args).
