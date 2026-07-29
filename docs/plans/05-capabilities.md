# 05 — Capabilities

## Goal

Build the capability registry and the implementations for each capability kind in v0.1: `tool`, `sub_agent`, `memory`, and `connector_action`. Each capability is a named, registered operation with a schema, an egress flag, and an execution function. All are invoked through the syscall layer.

## Spec references

- **D9** — One capability concept, four kinds (v0.1: tool, sub_agent, memory, connector_action)
- **D12** — Sub-agents are pooled capabilities
- **D18** — Declared egress per capability
- **Stories 3, 34-37** — tick capabilities, create sub-agents, see which agents call a sub-agent, sub-agent warnings

## Dependencies

- [04-syscall-layer.md](04-syscall-layer.md) — capabilities are invoked through the syscall layer
- [03-harness.md](03-harness.md) — sub-agent capabilities call back into the harness
- [07-pipeline.md](07-pipeline.md) — the pipeline orchestrates runs that invoke capabilities

## Tasks

### 1. Build the capability registry

`backend/src/agentos/capabilities/registry.py`:

```python
@dataclass
class CapabilityDef:
    name: str                          # e.g. "file.read", "shell.run"
    kind: Literal["tool", "sub_agent", "memory", "connector_action"]
    description: str
    parameters_schema: dict            # JSON schema for the model
    egress: bool                       # does this leave the machine?
    require_approval: bool = False
    subject_scoped: bool = False       # if true, subject injected by syscall layer
    execute: Callable                  # async fn(args, subject, credentials) -> result

class CapabilityRegistry:
    def register(self, def: CapabilityDef): ...
    def get(self, name: str) -> CapabilityDef: ...
    def list_all() -> list[CapabilityDef]: ...
    def list_by_kind(kind: str) -> list[CapabilityDef]: ...
```

- On startup, validate all registered capabilities (D10 schema check: subject-scoped capabilities must not expose a subject parameter)
- The registry is the source of truth for what capabilities exist; agent configs reference capabilities by name

### 2. Implement built-in tools

`backend/src/agentos/capabilities/tools/`:

**`file.py`** — `file.read`, `file.write`, `file.list`
- `file.read(path)` — read a file from the workspace (path resolved relative to workspace root, D29)
- `file.write(path, content)` — write a file to the workspace
- `file.list(path)` — list files in a directory within the workspace
- All paths are validated against workspace boundary before execution (D29)
- Egress: false

**`shell.py`** — `shell.run`
- `shell.run(command)` — execute a shell command in the sandbox (D28)
- Routes to the Sandbox interface (sandbox-exec on macOS, bwrap on Linux — see plan 06)
- Egress: true (shell can make network calls if granted)
- `require_approval`: configurable per-agent, default true for safety

### 3. Implement sub-agent capability kind

`backend/src/agentos/capabilities/sub_agent.py`:
- A sub-agent call is a recursive harness invocation (D12)
- The sub-agent receives: its own prompt, an explicit task from the caller, fresh context (no parent transcript)
- The sub-agent's capabilities are intersected with the caller's at runtime (D11)
- Depth capped at 2 (D12 rule 6) — a sub-agent cannot call another sub-agent beyond depth 2
- The sub-agent's turns and cost roll up to the parent Run (D12 rule 5)
- Output enters the caller's context as untrusted data (D12 rule 7)
- Audit records carry both `agent_id` and `sub_agent_id` (D12 rule 8)

### 4. Implement memory capability kind

- See [11-memory-skills.md](11-memory-skills.md) for the memory implementation
- `memory.recall(query)` and `memory.store(key, value, tags)` are registered as capabilities of kind `memory`
- Both are subject-scoped (resolve the Contact from the session)

### 5. Implement connector action capability kind

- See [10-connectors.md](10-connectors.md) for the connector implementation
- Connector actions (e.g. `email.read`, `calendar.create`) are registered as capabilities of kind `connector_action`
- The connector provides the `execute` function; the registry wraps it
- Credentials are injected by the syscall layer, not by the capability

### 6. Create API routes for capability management

`backend/src/agentos/api/capabilities.py`:
- `GET /api/capabilities` — list all registered capabilities (name, kind, description, egress)
- `GET /api/capabilities/{name}` — get capability detail (schema, egress, require_approval)

### 7. Create sub-agent API routes

`backend/src/agentos/api/sub_agents.py`:
- `POST /api/sub-agents` — create sub-agent
- `GET /api/sub-agents` — list all sub-agents
- `GET /api/sub-agents/{id}` — get sub-agent detail
- `PUT /api/sub-agents/{id}` — update sub-agent (new version)
- `GET /api/sub-agents/{id}/agents` — which agents call this sub-agent (story 35)

## Files to create

- `backend/src/agentos/capabilities/__init__.py`
- `backend/src/agentos/capabilities/registry.py`
- `backend/src/agentos/capabilities/tools/file.py`
- `backend/src/agentos/capabilities/tools/shell.py`
- `backend/src/agentos/capabilities/sub_agent.py`
- `backend/src/agentos/api/capabilities.py`
- `backend/src/agentos/api/sub_agents.py`
- `backend/tests/test_capabilities.py`

## Verification

- Registry lists all built-in tools with correct schemas
- `file.read("../etc/passwd")` → path rejected (escapes workspace)
- `file.read("test.txt")` → reads from workspace
- `shell.run("echo hello")` → executes in sandbox, returns "hello"
- Sub-agent call → fresh context, intersected capabilities, cost rolls up
- Sub-agent at depth 3 → rejected (depth cap)
- `GET /api/capabilities` returns all capabilities with egress flags
- Subject-scoped capability with a subject parameter in its schema → startup error
- `uv run pytest tests/test_capabilities.py` passes
