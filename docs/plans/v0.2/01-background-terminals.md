# v0.2.0 Background Terminals

## Outcome

An agent can start a long-running sandboxed command, observe bounded incremental output, and close it safely without orphaning processes.

## Current behavior and gap

`terminal(async=true)`, `read_terminal`, and `close_terminal` are advertised, but `shell_run` ignores `async`, no terminal registry exists, and read/close have no executor. Timeout paths do not consistently terminate process groups.

## Included

```text
terminal(command, async=true)
  → terminal_id + running status

read_terminal(terminal_id, offset?, max_chars?, wait_ms?)
  → incremental output + cursor + status

close_terminal(terminal_id)
  → terminate if running + unread final output + closed status
```

Detached commands that outlive the owning run are deferred. Durable unattended work belongs to Scheduler/Plan execution.

## Terminal session

```text
TerminalSession
  id
  agent_id
  session_id
  run_id
  workspace_path
  process_group_id
  status
  stdout_path
  stderr_path
  started_at
  completed_at?
  exit_code?
```

Terminal IDs are opaque and ownership-scoped. Output is spooled to bounded files, not retained indefinitely in memory or injected automatically into model context.

## Lifecycle

- Background start returns after the sandboxed process starts.
- `read_terminal` supports cursor continuation and bounded long-poll until output/status changes.
- Launch follows normal terminal approval; owned reads/stops require no second approval.
- `close_terminal` gracefully terminates the complete process group, force-kills after a bound, and is idempotent.
- Synchronous timeout, run cancellation, gateway shutdown, and app exit terminate process groups.
- Gateway restart reconciles persisted metadata to `interrupted`; it never claims the process survived.
- A run cannot silently finish with active terminals; the harness emits an observation requiring read/close.
- Frontend shows running/completed/failed/timed-out/interrupted/closed states and bounded live output.

## Security

- Another agent/session/run cannot read or close a terminal.
- Output and command metadata follow existing audit redaction/size rules.
- Workspace and sandbox policies are captured at launch and cannot be widened later.
- Child processes remain in the owned process group.

## Tests first

- Immediate background return
- Partial stdout/stderr and non-duplicating cursors
- Long-poll wake on output and completion
- Output truncation and retention
- Zero/non-zero exit
- Timeout and cancellation
- Child-process cleanup
- Ownership isolation
- Idempotent close
- Run completion guard
- Gateway restart reconciliation
- Strict and open sandbox modes

## Acceptance story

Start a long build, read progress twice without duplicated bytes, receive its final exit code, then start and close a process with a child. No process survives close, run cancellation, or gateway exit.

## Done when

The advertised terminal interface works end to end in development, packaged desktop, and Docker, with deterministic process cleanup.
