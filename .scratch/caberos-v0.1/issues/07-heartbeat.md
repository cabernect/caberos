# 07 — Scheduler (Heartbeat)

**What to build:** A unified **Scheduler** page in the dashboard sidebar (replacing the placeholder "Scheduler" nav item). In v0.1 the only scheduling mode is **heartbeat** — a per-agent periodic trigger that fires a Run without a user message. The operator enables heartbeat per agent, sets an interval (e.g. every 60 minutes) and a task prompt (e.g. "Check my inbox and summarize important messages"). The scheduler triggers a Run with `trigger=heartbeat` — the harness processes it the same way as a user-triggered run (same pipeline, same context assembly, same limits). The result appears in the conversation tagged as a heartbeat message (purple left border, "♢ heartbeat" header). If the heartbeat fails consecutively (configurable threshold, default 3), an alert is surfaced in the dashboard.

The page is built to extend to future scheduling modes (cron, event triggers, multi-agent coordination — deferred to v0.5) without re-architecting the UI. Heartbeat is the first row in the scheduler; later modes slot in as additional rows/sections.

**Blocked by:** 06 — Memory + skills (heartbeat runs need full context assembly including MEMORY.md and skills, and the agent needs memory to be useful in unattended runs).

**Status:** ready-for-agent

- [ ] **Scheduler page** (`/scheduler`, sidebar nav `scheduler`): lists every agent with its heartbeat status — enabled/disabled toggle, interval, task prompt, cost budget, last fired, next fire, consecutive failure count. Editable inline. Replaces the per-agent heartbeat fields currently in Settings → General (those fields are removed from the General tab; the General tab's `handleSave` no longer sends `heartbeat`).
- [ ] Heartbeat config: `HeartbeatConfig` on AgentConfig (enabled, interval_minutes, task_prompt, max_cost_per_heartbeat, consecutive_failure_threshold). Edited from the Scheduler page, persisted via `PUT /api/agents/{id}` (same endpoint, just `heartbeat` field only — no need to send the rest of the config).
- [ ] Heartbeat scheduler: asyncio task per agent. When enabled, fires at the configured interval. Creates a Run with `trigger=heartbeat`. Calls the same pipeline as user-triggered runs (D31 — the harness does not branch on trigger, it just records it).
- [ ] Cost budget: heartbeat runs check against `max_cost_per_heartbeat` (not `max_cost_per_run`). If exceeded, the run stops with fallback.
- [ ] Heartbeat SSE event: `heartbeat` event delivers heartbeat-tagged messages in real time. The message appears in the conversation with purple left border (3px) and "♢ heartbeat · timestamp" header.
- [ ] Consecutive failure alert: if a heartbeat run fails `consecutive_failure_threshold` times in a row (default 3), an alert is surfaced in the dashboard (visible in the top bar or a dedicated alerts area). The alert includes the failure reasons. The Scheduler page also shows the failure count per agent.
- [ ] Heartbeat messages in history: `GET /api/chat/{agent_id}/history` includes heartbeat messages. They're filterable by trigger type in observability (ticket 09).
- [ ] Audit: heartbeat runs write audit records like any other run. The `trigger` field distinguishes them for filtering.
- [ ] Daemon-only: heartbeat only runs when the daemon is running (not applicable in v0.1 since there's no CLI mode — but the scheduler is part of the daemon, not the frontend).
- [ ] **Future-proofing (not built in v0.1):** the Scheduler page structure leaves room for additional scheduling modes (cron expressions, external event triggers, multi-agent coordination) without UI re-architecture. These are v0.5 — out of scope here, but the page title and layout should not imply heartbeat is the only mode forever.
