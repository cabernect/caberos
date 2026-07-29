# Implementation Plans

Each file in this folder is an implementation plan for one part of CaberOS v0.1, derived from [`docs/spec-v0.1.md`](../spec-v0.1.md).

## Build order

Following **D27** — vertical slice first, then the rest of the dashboard.

### Phase 1: Vertical slice (one agent, end-to-end)

The goal: one agent, seeded from a config file, reachable through the dashboard chat (with `scripts/smoke.py` as a dev tool for pipeline testing), with a real model, a real workspace, a real shell call into the sandbox, and a real audit record.

| Order | Plan | What it delivers |
|---|---|---|
| 1 | [00-project-scaffold.md](00-project-scaffold.md) | Monorepo, uv, Python project, frontend skeleton, dev scripts, pytest infrastructure |
| 2 | [01-database-layer.md](01-database-layer.md) | SQLAlchemy models, Alembic, SQLite — all tables the slice writes to |
| 3 | [02-agent-config.md](02-agent-config.md) | Pydantic config models, YAML load, versioning — seed one agent from file |
| 4 | [03-harness.md](03-harness.md) | Pydantic AI + LiteLLM adapter, the agent loop, context assembly (soul, persona, task, MEMORY.md, skills), compaction |
| 5 | [04-syscall-layer.md](04-syscall-layer.md) | Subject injection, scope, approval (asyncio Event), audit — the mediation boundary |
| 6 | [05-capabilities.md](05-capabilities.md) | Capability registry, tool + sub-agent kinds (MCP tools added in plan 10) |
| 7 | [06-sandbox.md](06-sandbox.md) | Process-level sandbox (sandbox-exec/bwrap), clean env, workspace, shell.run + file tools |
| 8 | [07-pipeline.md](07-pipeline.md) | D19's 13-step execution pipeline — the central orchestrator. Both channels and heartbeat call it. |
| 9 | [08-channels.md](08-channels.md) | Dashboard chat channel — the one v0.1 channel. Per-conversation SSE. |
| 10 | [09-observability.md](09-observability.md) | run_id correlation, JSON logging, audit records, cost tracking (write side) |

**Slice milestone:** run `scripts/smoke.py <agent_id> "echo hello"` → agent reasons → calls `shell.run` in sandbox → prints answer to stdout. Every row the dashboard will read is written. No frontend needed — the smoke script is a dev tool for testing the pipeline before the dashboard exists (the product CLI/TUI is v0.2, D38).

### Phase 2: Features on top of the slice

| Order | Plan | What it delivers |
|---|---|---|
| 11 | [10-connectors.md](10-connectors.md) | MCP integration layer: connect external MCP servers (email, Notion, GitHub), encrypted credential custody, OAuth loopback, subject binding via instance-per-Contact |
| 12 | [11-memory-skills.md](11-memory-skills.md) | Three-layer memory (MEMORY.md, knowledge graph, semantic recall) + Agent Skills (markdown prompt injection) + identity config fields (soul/persona/task) |
| 13 | [12-control-plane.md](12-control-plane.md) | FastAPI admin API (read side), session auth, operator audit trail, heartbeat scheduler (D31), approval endpoints |

### Phase 3: Frontend (conversation-first, D32)

| Order | Plan | What it delivers |
|---|---|---|
| 14 | [13-frontend.md](13-frontend.md) | React app: agent list → full conversation view, per-conversation SSE, heartbeat messages, management sidebar. One client of the API (D33). Design system: AI-Native UI, dark-only. |

### Phase 4: Testing hardening

| Order | Plan | What it delivers |
|---|---|---|
| 15 | [14-testing.md](14-testing.md) | Coverage hardening: real-infrastructure tests, integration tests, edge cases. (Pytest setup is in plan 00.) |

## How to read a plan

Each plan file contains:

- **Goal** — what this part does and why it exists
- **Spec references** — D-numbers, invariants, user stories
- **Dependencies** — which plans must be done first
- **Tasks** — ordered, concrete implementation steps
- **Files to create** — expected file paths in the monorepo
- **Verification** — how to test this part works
