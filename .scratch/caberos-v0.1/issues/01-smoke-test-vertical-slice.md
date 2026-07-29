# 01 — Smoke test vertical slice

**What to build:** The thinnest end-to-end path through every layer of CaberOS. Running `python scripts/smoke.py test-agent "echo hello"` sends a message to an agent, the agent reasons (using a scripted model double — no real LLM, no API key), calls `shell.run("echo hello")` in the sandbox, the sandbox executes it, the result returns to the agent, the agent produces a final answer, and an audit record is written to the DB. Every row the dashboard will eventually read is written. No frontend, no real model, no connectors, no heartbeat, no memory, no approval flow.

This is the tracer bullet: it proves the architecture works end-to-end before any feature depth is added.

**Blocked by:** None — can start immediately.

**Status:** ready-for-agent

- [ ] Monorepo scaffolded: `/backend` (Python 3.12, uv, FastAPI), `/frontend` (empty skeleton), `/docs`, `/sandbox`, `/scripts`. Dev scripts work (`scripts/dev.sh`).
- [ ] Database layer: SQLAlchemy 2.0 async + aiosqlite + Alembic. All v0.1 tables created (Agent, AgentVersion, Capability, AgentCapability, SubAgent, Connector, Provider, Contact, Session, Run, Message, AuditRecord, ApprovalRequest, MemoryEntry, MemoryTriple, Operator). WAL mode active. Seed script creates operator + capability registry.
- [ ] Agent config: Pydantic models (AgentConfig with soul/persona/task/model/capabilities/limits/fallback/heartbeat). YAML import. Versioning (save → new AgentVersion row, active_version pointer). One test agent seeded from YAML with `shell.run` capability.
- [ ] Harness: Pydantic AI loop with LiteLLM adapter (but using a scripted model double that returns a predetermined tool call then a final answer). Context assembly loads soul/persona/task. Turn counting, cost accumulation (fake costs from the double). Event emitter interface (SSE events emitted to a callback — no real SSE stream yet, just the interface).
- [ ] Syscall layer: protocol interface (`SyscallHandler.mediate()`). Stub implementation that auto-approves all calls. Subject injection (resolves contact from session). Audit record written for each syscall.
- [ ] Capabilities: registry seeded with `file.read`, `file.write`, `file.list`, `shell.run`, `memory.recall`, `memory.store`. Capability kinds: tool, sub_agent, memory, connector_action (no mcp_tool).
- [ ] Sandbox: process-level sandbox (sandbox-exec on macOS, bwrap on Linux). Clean env. Workspace bounded. `shell.run` executes inside the sandbox.
- [ ] Pipeline: D19's 13-step execution pipeline. Inbound message → persist → resolve contact → resolve session → serialize (per-contact lock) → assemble context → reason → mediate → check limits → iterate → deliver → record. Both the smoke script and future channels call this pipeline.
- [ ] Smoke script: `scripts/smoke.py <agent_id> "<message>"` — sends a message via the pipeline directly (or via HTTP if the API is up), prints tool calls and final answer to stdout.
- [ ] `uv run pytest` passes with basic tests: DB CRUD, config validation, harness loop with scripted double, sandbox executes a command, audit record written.
