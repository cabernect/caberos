# Local And Remote Terminal Backends

Status: gates 1–2 delivered (execution-transport seam, `exec.terminal`
binding, local backend selection + admission pin — see
[test_result/2026-11-09-terminal-backends.md](test_result/2026-11-09-terminal-backends.md)).
Gates 3–7 (remote connections, transfers, SSH/Daytona/Modal drivers,
reconciliation) deferred — they require verifiable remote infrastructure;
no selector-only placeholders ship. Backend configuration
does not authorize connections, workspace uploads, cloud provisioning, or commits.

## Product Decision

Settings -> Tools -> Terminal owns backend selection, connection credentials,
options, readiness, and explicit connection tests. Both local and remote execution
are in scope; remote execution is not a selector-only placeholder.

Keep `terminal`, `read_terminal`, and `close_terminal` as the agent-facing tools.
Backend choice never grants authority, disables approval, or changes sandbox mode.
Reuse Provider records/encryption from [W9](09-search-services.md) for remote
credentials, configured inline in Tools, not a separate store or Providers section.

## Scope And Existing Evidence

| Backend | Release scope |
|---|---|
| Auto (local only) | OS-native only; never choose Docker or remote implicitly |
| Seatbelt | Explicit macOS selection and readiness |
| Bubblewrap | Explicit Linux selection and readiness |
| Docker | Future explicit opt-in setup; not a current default or fallback |
| MXC | Windows selection, retaining experimental status and explicit host-setup consent |
| SSH | New remote adapter with pinned host identity and an authorized execution root |
| Daytona | New remote sandbox adapter; verify actual lifecycle/filesystem/exec APIs |
| Modal | New remote sandbox adapter; verify actual lifecycle/filesystem/exec APIs |

Current Auto is Seatbelt on macOS, Bubblewrap on Linux, and MXC on Windows.
An unavailable native terminal is reported unavailable; it never probes Docker
or asks the operator to install/start it as recovery. Docker remains a prototype
for future explicit setup, not part of the current automatic selection path.
Explicit backend failure must not fall back to Auto, another backend, or open
host execution.

The current `SandboxBackend` exposes command execution and local spawn arguments;
`TerminalRegistry` owns a local subprocess/process group. Merely implementing
`spawn_argv` does not provide cloud execution, remote kill, file transfer, or
restart reconciliation. Both synchronous and background paths need integration.

## Configuration And Admission

- Offer Auto/local/remote selection and only relevant fields. Show operating
  system support, isolation strength, unavailable reasons, and experimental
  status separately from connection reachability.
- SSH: host, port, user, encrypted authentication material, pinned host-key
  fingerprint, and authorized remote root. No trust-on-first-use without explicit
  operator verification, disabled host checking, ambient SSH-agent forwarding,
  port forwarding, or arbitrary client SSH options.
- Cloud: named encrypted connection, reviewed service endpoint, explicit region,
  supported template/image, resource limits, and lease/idle limits where supported.
  Never infer that an API key approves spending or project-data upload.
- Save/open performs local validation only. Test connection is explicit, bounded,
  and does not upload a workspace or create billable compute by default. If an
  execution probe needs a resource, disclose it and require separate consent.
- One global binding supplies defaults. At session admission, pin its revision,
  resolved backend, isolation mode, connection identity, and workspace mapping.
  Local Auto resolves to an actual local backend, not a mutable token.
- Setting changes apply to new sessions, not already admitted commands,
  approval waits, or background terminals. Incompatible revocation causes an
  explicit failure, not transparent migration. Existing local sessions receive
  a compatible local pin; never migrate them to remote on startup.
- Run manifests and terminal records identify the actual backend/remote resource,
  source workspace, and connection revision without persisting secrets.
- `read_terminal`/`close_terminal` retain existing agent/session/run ownership.
  A remote handle or provider ID is not sufficient authorization.

## Workspace Mapping And Transfer

The pinned local workspace remains authoritative. First remote support uses an
explicit staged working copy, not a claimed shared mount or invisible two-way sync.
Remote terminal output must clearly say when local file tools see stale bytes.

1. Before remote admission, show destination, selected relative paths, total size,
   exclusions, and retention. Require explicit operator authorization of upload
   scope; first use cannot silently send an entire repository.
2. Build a bounded manifest from contained files. Default-deny identity/memory,
   credentials, `.env`/private keys, `.git`, dependency trees, and platform data.
   Include only explicit selected paths; ignore patterns are not a secret scanner
   or permission boundary. Symlink escapes and special files are refused.
3. Stage in a dedicated per-session remote root. Record source hashes, approved
   paths, remote identity, and generation so sessions cannot overwrite each
   other's staging. Re-upload/new paths require an authorized transfer scope.
4. Expose an explicit output retrieval/synchronization action. Fetch bounded,
   approved paths into owned local staging first; validate traversal, symlinks,
   archive entries, actual sizes, and destination authorization before publishing.
5. Present changes/conflicts and require approval before applying them locally.
   Compare original hashes; do not overwrite edits by the user/another agent.
   No deletion propagation, whole-tree mirroring, or automatic binary adoption.
6. Remote downloads do not automatically become tracked artifacts. Publish
   deliverables through the existing artifact path with revision/provenance;
   ordinary returned working files remain working files.

Selecting a remote terminal does not relocate agent identity, memory, chat
history, or credential custody. Multiple agents sharing local files do not
implicitly share remote credentials, leases, or transfer consent.

## Execution And Isolation Contract

- Introduce a small execution-session interface for start, bounded incremental
  read, wait/status, cancel/close, and reconciliation. Adapt existing local
  subprocess behavior before adding provider-specific drivers; do not rewrite
  unrelated sandbox policy or duplicate terminal registries.
- Preserve synchronous results and background terminal IDs, cursor/truncation
  semantics, output limits, and syscall call/run correlation on every adapter.
- Identify remote OS/shell explicitly in tool guidance. Do not use the gateway's
  `sys.platform` to describe an SSH/cloud shell. Quote transport arguments
  separately from the intentionally executable command.
- Strict mode must have enforced filesystem/process/network constraints.
  SSH plus `cd <root>` is not isolation; a container/remote sandbox or equivalent
  verified enforcement is required. Refuse unsupported strict execution.
- Broader remote-host access, if supported at all, requires a separate explicit
  operator open-mode choice and warning. Selecting SSH must not enable it.
- Distinguish gateway-to-service control-plane egress from network access inside
  the remote job. A network-disabled command must still be enforceably disabled
  remotely; reject unsupported policies rather than silently ignoring them.
- Configuration tests, provisioning, upload, command execution, and retrieval
  have separate consent/effect accounting. Agent calls always cross mediation;
  operator setup actions use authenticated, scoped, audited endpoints.

## Lifecycle, Cancellation, And Spend

- Leases identify resources CaberOS created versus operator-owned SSH hosts or
  preexisting resources. Close owned processes/resources only; never delete an
  arbitrary remote directory, VM, project, or user file during cleanup.
- Enforce timeouts, concurrency/resource/lease limits, and output bounds. No
  automatic cloud creation or paid retry after ambiguous dispatch. Freeze the
  remote resource ID and use idempotency/reconciliation where available.
- Disconnecting an SSH client does not prove the remote command stopped.
  Confirm remote process-tree/resource termination; report unknown/orphaned state
  when it cannot be verified. Do not call a timed-out command completed.
- On restart, reconcile persisted remote leases/status before claiming liveness.
  Mark local processes interrupted per existing behavior. Surface outstanding
  remote resources and cost risk with explicit reconnect/cleanup actions.
- Credentials revoked while work runs may prevent cleanup; show that failure
  and any expiring lease, not a fake successful close.
- Bound cleanup to explicitly authorized owned resource IDs/paths and lease
  policy. Never remove user-owned hosts/data as part of a connection test.
- Record resource/session/request correlation, timing, billed/measured units,
  and available cost provenance. Remote compute is not an LLM model call.
  Unknown compute/transfer charges remain unknown, not free.

## Security And Implementation Gates

Private SSH hosts can be intentional: use a scoped operator-authorized endpoint,
not the generic web-fetch exception or a blanket private-network bypass. Review
DNS/host-key changes, service redirects, proxy/metadata endpoints, credential
redaction, remote environment leakage, and archive/path handling before enabling
each remote adapter. Do not install runtimes or request elevated access silently.

1. Inventory local terminal/sandbox paths and add behavior-preserving adapter
   contract tests for sync, background, read, close, and output limits.
2. Add `exec.terminal` binding, pinning, Tools controls, and explicit local
   backend selection with platform/readiness/migration tests.
3. Reuse encrypted tool connections; add authenticated endpoint tests, isolation
   policy metadata, lease records, and both DB-backend migrations as needed.
4. Implement bounded transfer manifests, consent, staging, retrieval/conflict
   handling, and trusted artifact publication with filesystem attack fixtures.
5. Implement SSH end to end against an isolated fixture host, including verified
   isolation and remote process termination; no real host access without consent.
6. Verify official Daytona/Modal APIs and implement each end to end with scripted
   transport/lifecycle fixtures. Document supported templates/regions/policies;
   no unsupported adapter appears ready.
7. Add restart/revocation/orphan reconciliation, compute receipts/spend inspection,
   integrated browser/desktop QA, and consented bounded live checks where needed.

Existing targets: backend `sandbox/base.py` and platform adapters,
`terminal/registry.py`, `models/terminal.py`, `capabilities/tools/terminal.py`,
`capabilities/bindings.py`, `syscall/mediator.py`, workspace/admission services,
settings/encryption/DB backends; frontend Tools in `pages/ProvidersSettings.tsx`,
conversation workspace/terminal status, API/types, and related tests.
Proposed: execution-session drivers, encrypted remote connections, transfer
manifests, lease persistence, and compute receipts. Reconcile actual module names
before implementing; keep SDK quirks behind the driver interface.

## Acceptance

Both local and remote paths execute, incrementally read, terminate, and report
status honestly. Backend edits never reroute pinned work. Remote upload is
explicit, local edits survive retrieval conflicts, and cleanup affects only
authorized owned resources. Credentials remain encrypted/redacted. Isolation and
network limits are enforced or requests fail clearly. Real cloud costs require
explicit consent; fixture tests do not provision or connect to real services.
