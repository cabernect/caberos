# 09 — Observability + spend

**What to build:** The operator can see everything the agent has done. A runs list (filterable by agent, contact, outcome, trigger type). A run detail view (messages with timestamps, syscalls with results, model calls, errors — all linked by run_id). A syscall log (one table across all agents, filterable by agent, capability, contact, outcome). A spend dashboard (today's total, breakdown by agent, breakdown by trigger type — user vs heartbeat). Denied syscalls are highlighted. This is the transparency layer — the operator can audit every action the agent took.

**Blocked by:** 03 — File operations + tool call visibility (needs real syscalls flowing through the audit trail to populate the observability views).

**Status:** ready-for-agent

- [ ] Runs list API: `GET /api/runs` — paginated, filterable by agent_id, contact_id, status, trigger, date range. Returns run summary (id, agent, contact, status, trigger, cost, latency, started_at).
- [ ] Run detail API: `GET /api/runs/{run_id}` — full detail: messages (with timestamps, roles, content), syscalls (capability, args, allowed/denied, result, cost, latency), model calls, errors. All linked by run_id.
- [ ] Syscall log API: `GET /api/audit` — paginated, filterable by agent_id, capability_name, contact_id, allowed (bool), date range. Returns audit records.
- [ ] Spend API: `GET /api/spend` — today's total, breakdown by agent, breakdown by trigger (user_message vs heartbeat). Date range filter. Test sessions excluded (is_test flag).
- [ ] Frontend — Observability page: runs list (filterable), run detail (messages + syscalls inline), syscall log (one table, filterable, denied highlighted with reason). Spend dashboard (today's total, breakdown charts). Accessible from the top bar.
- [ ] Frontend — Run detail: messages with timestamps, tool call blocks (same component as conversation view but read-only), syscalls with results, cost per turn, total run cost. Errors visible with stack trace in a collapsible block.
- [ ] Operator audit trail: `OperatorAuditLog` — records operator actions (login, agent config change, approval decision, connector connect/revoke). Viewable in a dedicated section.
- [ ] System health: DB status, sandbox status, model provider status (can we reach OpenAI?). Shown in a small status indicator in the top bar.
