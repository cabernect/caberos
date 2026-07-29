# 04 — Syscall Layer

## Goal

Build the single boundary every capability call crosses. The syscall layer resolves the subject (whose data), narrows scope (agent ceiling ∩ sub-agent ceiling), authorizes, injects credentials, checks approval, executes, reduces oversized results, and writes an audit record. This is where the OS's security guarantees are enforced (I2, I3, I4).

## Spec references

- **I2** — Every effect is a syscall
- **I3** — The subject is never model-supplied
- **I4** — Authority narrows monotonically
- **D10** — The syscall layer injects the subject; the agent cannot name it
- **D11** — Authority narrows monotonically (`min(agent_ceiling, sub_agent_ceiling)`)
- **D14** — The agent has real authority, bounded by a sandbox
- **D18** — Execution limits (timeout, result reduction, declared egress)
- **D19** — Execution pipeline step 9 (mediate)

## Dependencies

- [01-database-layer.md](01-database-layer.md) — needs AuditRecord, ApprovalRequest tables
- [02-agent-config.md](02-agent-config.md) — needs agent config for capability grants and scope
- [07-pipeline.md](07-pipeline.md) — the pipeline calls the syscall layer during step 9 (mediate)

## Tasks

### 1. Define the syscall interface

`backend/src/agentos/syscall/__init__.py`:

```python
class SyscallHandler:
    async def mediate(
        self,
        call: ToolCall,          # name, args (from the model)
        session: Session,         # contact_id, agent_id
        agent_config: AgentConfig,
        is_sub_agent: bool = False,
        sub_agent_id: str | None = None,
    ) -> SyscallResult:           # output, allowed, denied_reason, cost, latency
```

### 2. Implement the mediation pipeline

`backend/src/agentos/syscall/mediator.py` — for each tool call, in order:

1. **Resolve capability** — look up the capability by name in the registry. Reject if not found.
2. **Check grant** — verify the agent (or sub-agent) has this capability granted. Reject if not.
3. **Resolve subject** (D10) — if the capability is subject-scoped (`self`):
   - Look up the session's Contact
   - Look up the Contact's binding (D8)
   - If no binding exists → **fail closed**: denied audit record, reason "no subject binding"
   - The subject is the binding, not anything the model passed
   - If the model passed a subject parameter → **startup error** (enforced at schema registration, not here, but double-check)
4. **Narrow scope** (D11) — `effective_scope = min(agent_ceiling, sub_agent_ceiling)`
   - If sub-agent call: intersect sub-agent's grants with calling agent's grants
   - If the effective scope doesn't include what the call needs → deny
5. **Check approval** (Decision 4) — if the capability or grant has `require_approval: true`:
   - Create an `ApprovalRequest` row (status=pending)
   - The run blocks on an `asyncio.Event` while waiting for approval
   - The per-Contact lock is held during this wait — **known limitation for v0.1**: in a single-user system, the operator is the one who needs to approve, so they can't send another message anyway
   - The control plane's `POST /api/approvals/{id}/approve` sets the event; `POST /api/approvals/{id}/reject` sets it with a denied flag
   - On approval → continue execution. On rejection → denied audit record, run continues.
6. **Inject credentials** — if the capability is a connector action:
   - Look up the connector's `credential_ref` (e.g. `secret://outlook/token`)
   - Decrypt the credential (via the secret store, D13)
   - Pass the credential to the capability implementation
   - **Never** put credentials in model context or logs
7. **Execute** — call the capability implementation:
   - Under a timeout (D18)
   - Shell/filesystem capabilities → route to the sandbox (D28)
   - Connector capabilities → route to the connector implementation (plan 10)
   - Memory capabilities → route to the memory store (D30, plan 11)
   - Sub-agent capabilities → route to the harness (recursive, depth capped at 2)
8. **Reduce result** (D18) — if the result exceeds the token threshold, truncate or summarize
9. **Write audit record** — immutable insert into `AuditRecord`:
   - run_id, agent_id, sub_agent_id (if applicable)
   - capability_name, subject_contact_id (if subject-scoped)
   - allowed (bool), denied_reason (if denied)
   - cost, latency_ms, created_at

### 3. Implement subject parameter enforcement

`backend/src/agentos/syscall/schema_check.py`:
- At capability registration time (not runtime), check that subject-scoped capabilities do not expose a subject parameter in their schema
- If they do → startup error, not a code-review convention (D10 enforcement)
- This is a one-time check per capability, not per call

### 4. Implement the per-Contact lock

`backend/src/agentos/syscall/lock.py`:
- At most one Run per Contact at a time (D19 step 6)
- Concurrent arrivals queue
- Implemented as an in-process asyncio lock keyed by `contact_id`

> **Note:** The asyncio.Event approach is simple and correct for v0.1's single-user model. For multi-user systems, a suspend/resume mechanism would be needed to release the lock during approval waits.

## Files to create

- `backend/src/agentos/syscall/__init__.py`
- `backend/src/agentos/syscall/mediator.py`
- `backend/src/agentos/syscall/schema_check.py`
- `backend/src/agentos/syscall/lock.py`
- `backend/tests/test_syscall.py`

## Verification

- Model calls `email.read()` → syscall resolves subject from session Contact's binding → executes → audit record written with `allowed=true`
- Model calls `email.read()` on a Contact with no binding → denied audit record, reason "no subject binding"
- Model passes `email.read(mailbox="someone_else")` → denied (schema doesn't accept a mailbox param, so this is a schema violation at the model level, but if it somehow gets through → denied)
- Agent not granted `shell.run` → model calls it → denied, reason "not granted"
- Sub-agent calls a capability the parent agent doesn't have → denied (scope narrowing)
- `require_approval` capability → ApprovalRequest created, run blocks on asyncio.Event → approve (POST /api/approvals/{id}/approve) → executes → audit record
- `require_approval` capability → reject (POST /api/approvals/{id}/reject) → denied audit record, run continues
- Capability times out → error recorded, run continues with fallback
- Two concurrent messages from same Contact → second queues behind first
- `uv run pytest tests/test_syscall.py` passes
