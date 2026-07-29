# 07 — Heartbeat

**What to build:** The agent wakes up on its own. The operator enables heartbeat in the agent settings, sets an interval (e.g. every 60 minutes) and a task prompt (e.g. "Check my inbox and summarize important messages"). The heartbeat scheduler triggers a Run without a user message — the harness processes it the same way as a user-triggered run (same pipeline, same context assembly, same limits). The result appears in the conversation tagged as a heartbeat message (purple left border, "♢ heartbeat" header). If the heartbeat fails consecutively (configurable threshold, default 3), an alert is surfaced in the dashboard.

**Blocked by:** 06 — Memory + skills (heartbeat runs need full context assembly including MEMORY.md and skills, and the agent needs memory to be useful in unattended runs).

**Status:** ready-for-agent

- [ ] Heartbeat config: `HeartbeatConfig` on AgentConfig (enabled, interval_minutes, task_prompt, max_cost_per_heartbeat, consecutive_failure_threshold). Editable in the agent settings sidebar (from ticket 05).
- [ ] Heartbeat scheduler: asyncio task per agent. When enabled, fires at the configured interval. Creates a Run with `trigger=heartbeat`. Calls the same pipeline as user-triggered runs (D31 — the harness does not branch on trigger, it just records it).
- [ ] Cost budget: heartbeat runs check against `max_cost_per_heartbeat` (not `max_cost_per_run`). If exceeded, the run stops with fallback.
- [ ] Heartbeat SSE event: `heartbeat` event delivers heartbeat-tagged messages in real time. The message appears in the conversation with purple left border (3px) and "♢ heartbeat · timestamp" header.
- [ ] Consecutive failure alert: if a heartbeat run fails `consecutive_failure_threshold` times in a row (default 3), an alert is surfaced in the dashboard (visible in the top bar or a dedicated alerts area). The alert includes the failure reasons.
- [ ] Heartbeat messages in history: `GET /api/chat/{agent_id}/history` includes heartbeat messages. They're filterable by trigger type in observability (ticket 09).
- [ ] Audit: heartbeat runs write audit records like any other run. The `trigger` field distinguishes them for filtering.
- [ ] Daemon-only: heartbeat only runs when the daemon is running (not applicable in v0.1 since there's no CLI mode — but the scheduler is part of the daemon, not the frontend).
