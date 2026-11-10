# Local Host Hardening Baseline (W7)

Status: BASELINE DELIVERED — the workstream was re-scoped down on operator direction.
What is in scope is listed under "Baseline scope" below; the original
full-scope sections are kept under "Deferred — full boundary work" so the
threat review and requirements remain available when a later workstream
picks them up. This is a hardening plan, not a completed security audit
or authorization to install software, change host firewalls, grant
privileges, or make live probes.

## Baseline Scope (what W7 now means)

Already implemented and fixture-tested:

- `web_fetch` destination policy at the dial point: checked DNS answers,
  pinned IP with original Host/SNI, per-redirect revalidation, bounded
  body, deadline, no ambient proxy/cookie/credential forwarding, and an
  operator exact-host private allowlist.
- Browser explicit-navigation preflight (scheme + destination check);
  Chrome's own in-page traffic is explicitly NOT covered — see Deferred.
- Shared sync execution lifecycle (`sandbox/process.py`): deadline,
  cancellation/timeout cleanup ordering, bounded 4 MiB-per-stream output
  with drain-to-EOF and a `truncated` flag, safe process-group kills.
- Native confinement adapters: Seatbelt scoped workspace/runtime grants,
  bwrap real-profile readiness + allowlisted env, Docker hardened as
  inactive opt-in prototype. OS-native execution stays the default and
  failures are reported, never silently retried elsewhere.
- MCP HTTP traffic through `mcp/transport.PolicyTransport`: every
  SDK-generated request (discovery, registration, token exchange,
  refresh, redirects) dials checked destinations; ambient proxies off;
  literal local/localhost config authorizes its exact origin only;
  cached OAuth resource/issuer/client bindings revalidated before use.
- Child environment hygiene: stdio MCP servers inherit only the SDK
  allowlist plus operator-declared vars; backends pin launch env.

Baseline verification status:

- DONE (macOS, this host): Seatbelt native checks run against synthetic
  directories — workspace R/W + workspace temp allowed; sibling secret
  unreadable directly and via symlink; sibling temp unwritable. The run
  exposed and fixed a real defect: subpath-only file grants abort every
  process in dyld; the profile now uses layered private-tree denies.
- NOT RUN HERE: bwrap (Linux-only) and MXC (Windows-only, experimental)
  native checks — verified only on their own platforms.
- Everything else in the baseline is synthetic-fixture verified.


Operator direction: the default terminal path is OS-native. If it is unavailable
or a command fails, report that result without switching to Docker or another
backend. Docker sandbox setup is future, explicit opt-in work, not a prerequisite
for native terminal execution or a required W7 installation. Existing Docker
hardening is retained as inactive prototype work. Per-agent strict/open policy
is unchanged; native failure must not downgrade strict execution to open.

Delivery scope clarification: enforce the existing agent/tool grants, approval
decisions, workspace restrictions, strict/open mode, and network settings.
Do not introduce a parallel permission system, new grant schema, or scope UI.
Service-specific grant configuration is a separate proposal, not a prerequisite
for consolidating or enforcing the current policy.

## Goal

Protect the operator's machine, files, credentials, and control plane from
agent mistakes, prompt-injected content, and compromised integrations. Preserve
intentional local-service workflows through explicit, narrow authority.

URL checks are one layer, not a machine sandbox. An approval authorizes a
specific operation; it must not disable filesystem, process, or network limits.

## Trust Boundaries And Current Gaps

- Web pages, retrieved documents, model arguments, workspace code, and MCP
  responses are untrusted inputs, not permission or policy authorities.
- CaberOS's credential custody and authenticated operator APIs are trusted
  control-plane components. Terminal workers, browser processes, and MCP
  subprocesses must not inherit their authority.
- Localhost reachability does not bypass API authentication. Conversely,
  authentication alone does not contain arbitrary local process execution.
- Operator installation of an MCP server authorizes a connection, not arbitrary
  discovery destinations, host-file access, or credential forwarding.
- The existing `netpolicy.py` pins fetch dial targets and checks redirects.
  Browser checks only cover explicit navigation before Chrome resolves again;
  frames, subresources, script navigation, WebSockets, and rebinding remain open.
- The current exact-host private allowlist spans ports and schemes. Keep that
  configured meaning, document its breadth, and do not silently replace it with
  a new service-scoped grant model. MCP discovery and refresh now use a checked,
  pinned HTTP transport; isolated SDK-flow verification is still pending.
- The execution inventory in `test_result/2026-11-05-network-policy.md` identifies
  Seatbelt's unrestricted reads/shared temp and Docker's background cleanup and
  resource-limit gaps. A follow-up patch removes implicit Docker image pulls
  during readiness and execution; its regression tests still need an isolated
  runtime. This is partial work, not strict-isolation acceptance.
- A subsequent Seatbelt patch replaces blanket reads/shared-temp access with
  scoped runtime/workspace grants, workspace-local temp variables, and a
  fail-closed synthetic readiness probe. Policy-construction and opt-in native
  tests are written; isolated native verification is still pending.
- Background terminals now persist planned Docker identities before activation,
  clean up through the admitted backend, and retain an orphaned state on
  unconfirmed termination. Docker resource/privilege flags and cached OAuth
  binding checks are implemented, but runtime acceptance remains open.
- Generic fetch now has an operation-wide deadline, stateless cookies,
  public-content-only headers, and identity-only response handling. Wildcard
  grants are rejected rather than rewritten. Browser connection-level
  enforcement is still required; finer-grained grant settings are deferred.
- Native sync execution now uses `sandbox/process.py` for deadline, abort,
  decoding, and bounded output. Sync capture and background spooling share
  the existing 4 MiB-per-stream cap and drain implementation. This does not
  establish CPU/RAM containment or complete descendant termination.

## Threat Model And Limits

Test malicious content inducing local-service requests, secret reads, workspace
escape, destructive commands, unapproved uploads, and metadata-directed token
disclosure. Include compromised child processes and settings/revocation races.

Do not promise protection against an administrator, kernel/hypervisor compromise,
or arbitrary code already running as the operator. A same-user attacker may
access CaberOS's key material; encryption at rest alone does not prevent this.
Public-network access can also exfiltrate workspace data: blocking private
addresses is not a data-loss-prevention policy.

## Existing File Targets

`netpolicy.py`, `sandbox/`, terminal tools and lifecycle registry,
`capabilities/tools/web.py`, `browser/cdp.py`, browser runtime and tool handlers,
`mcp/client.py`, `mcp/oauth.py`, `mcp/registry.py`, settings, and syscall
mediation; authentication, credential injection, and operator audit records.
Inspect installed MCP SDK hooks and metadata validation before assuming checks
cover discovery, registration, token exchange, reconnect, and refresh requests.

## Policy Decisions

Define separately:

- Public web access from agent tools.
- Operator-authorized local services and MCP endpoints.
- OAuth loopback callbacks, which are not arbitrary private-network egress.
- Browser navigation/subresources, which have a different transport from httpx.
- W11 SSH/cloud control-plane connections and authorized workspace transfer.
  Job network access is a separate policy from connecting to the execution service.

Recommend rejecting private/loopback/link-local/reserved destinations for general
web tools unless the operator explicitly grants a narrow exception. Preserve
intentional local MCP use through an explicit endpoint policy, not a blanket ban
or automatic exception for anything described as "local".

Record exception scope, audit visibility, revocation, and compatibility warnings.
Do not silently break approved local integrations or silently grandfather broad
authority. An allowlisted public hostname is not proof its resolved IP is public.

## Deferred — full boundary work

Design note (operator direction, recorded for the follow-up workstream):
the private-destination UX should become a forced approval, not a static
allowlist — a blocked local fetch/navigation surfaces "allow once /
always allow this host" at the syscall approval gate, where "always"
writes the allowlist entry. An implementation spike exists in this
session's history (contextvar grants + mediator retry) and was dropped
as out-of-baseline-scope; the mechanism is sound and cheap to rebuild.


Everything below this heading is OUT of baseline scope. It documents the
complete boundary design (browser-wide traffic enforcement, per-server MCP
sandbox grants, scoped local-service exceptions, control-plane and remote
verification) for a later workstream. The baseline above must not be
described as covering any of it.

## Required Protection Contracts (deferred)

### Execution And Filesystem Isolation

- Execute terminal commands and untrusted code inside an OS-enforced boundary.
  Strict execution defaults to no network, a selected workspace, scratch-local
  HOME/temp/cache, and an explicitly allowlisted environment.
- Do not expose the host home, CaberOS DB/key store, personal browser profiles,
  SSH/cloud credentials, SSH agent, Docker socket, or privileged device mounts.
  Docker provisioning belongs to the trusted controller, not the worker.
- Restrict writes to granted roots; test symlink and traversal escapes, mounts,
  read-only Reviewer access, and descendants/background jobs.
- Enforce supported CPU, memory, process, disk/output, and wall-clock limits.
  Report actual limits per backend/platform. No privileged containers, silent
  elevation, automatic runtime installation, or fallback to open host execution.
- If a required boundary cannot be enforced, mark strict mode unavailable and
  refuse dispatch. Any intentionally less-isolated mode needs separate explicit
  operator consent and must never be labeled strict.
- W11 owns backend drivers, transfers, and remote lifecycle; W7 owns this
  protection contract and verification. SSH connectivity is not remote isolation.

### Browser And HTTP Network Enforcement

- Keep fetch checks at the actual dial target, with original Host/TLS identity,
  mixed-answer rejection, per-redirect validation, and bounded decompressed
  bodies, DNS/connect time, and total operation time.
- Prevent caller headers, cookies, proxy settings, or connection reuse from
  bypassing destination policy. Cross-origin redirects must not forward secrets;
  generic fetch must never inherit provider credentials or operator sessions.
- Select a supported browser enforcement mechanism before implementation:
  restricted egress proxy plus OS/container/VM rules, or equivalent enforceable
  isolation. Proxy configuration alone is not containment.
- Cover top-level and script navigation, redirects, frames, workers, service
  workers, fetch/XHR, images, WebSockets, downloads, and new targets/popups.
  Block direct DNS/UDP/QUIC/WebRTC or other proxy-bypass paths unless equivalent
  policy is enforced. CDP URL interception alone is not a rebinding boundary.
- Block unsupported traffic classes or gate affected browser execution with an
  explicit unavailable reason. Listing a known bypass is not passing this gate.
- Keep isolated browser profiles, download staging, and narrowly scoped uploads.
  Do not import the operator's personal cookies or expose arbitrary host files.

### Local-Service Exceptions And Revocation

- Enforce the existing exact-host network allowlist alongside existing agent/
  tool authorization. Host-wide permission remains host-wide; do not invent
  per-tool, scheme, port, or address-scope settings in this implementation.
- Normalize hostnames/IPs consistently; reject wildcard expansion, ambiguous
  entries, URL credentials, and malformed or silently truncated configuration.
  A public hostname without an exception must not gain private access when its
  DNS changes. Document that an explicit private-host exception currently
  admits eligible loopback/RFC1918/ULA addresses for that host.
- Link-local, metadata, multicast, unspecified, and reserved targets remain
  denied under ordinary private-service exceptions. OAuth loopback callbacks
  are a separate narrowly bound listener, not arbitrary local egress authority.
- Protect administrative/control-plane destinations separately; a broad LAN
  exception must not expose CaberOS operator APIs.
- Recheck existing policy at connection and redirects. Removing an allowlist
  entry denies subsequent checked connections; do not claim that this closes
  every already-established stream. Immediate active-stream revocation and
  policy/grant versioning remain separate, unfinished design work.
- A configured literal local/localhost MCP endpoint authorizes its exact
  origin, not every private metadata/token destination. Other private names
  require the existing explicit host allowlist. Report compatibility failures
  rather than silently broadening authority.
- Consumer/scheme/port/address-specific grants and their configuration UX are
  deferred. Any future design must reuse the permission model, not compete
  with it.

### Credentials And MCP/OAuth

- Keep credentials in the trusted controller; inject only the specific secret
  needed for an admitted operation. Child environments start empty, not from
  inherited host variables. Test reads, errors, logs, exports, and audit redaction.
- Sandbox local MCP subprocesses with per-server filesystem/network grants,
  resource limits, and lifecycle cleanup. Do not require a blanket private-IP
  ban that breaks intentionally configured local HTTP servers.
- Trace actual SDK requests for protected-resource and authorization metadata,
  registration, token exchange, refresh, and reconnect. Validate resource and
  issuer relationships and approved endpoint identities, not just URL syntax.
- Permit legitimate cross-origin authorization servers only through validated,
  explicitly scoped relationships. Do not send tokens/client secrets to an
  arbitrary metadata-advertised origin or follow credential-bearing redirects.
- Bound metadata bodies/time/redirects; test hostile or inconsistent issuers,
  stored metadata replacement, endpoint substitution, and refresh after restart.
  Browser OAuth consent is not a substitute for backchannel destination checks.
- Preserve state/PKCE, exact callback binding, token audience/resource scope,
  secure storage, and redacted errors. Inspect SDK guarantees instead of
  duplicating or assuming them.

### Control Plane, Damage Limits, And Recovery

- Verify authentication plus appropriate Origin/CSRF/Host protections for the
  browser-facing control plane, including loopback/DNS-rebinding scenarios.
  Do not pass operator tokens/cookies to workers or integration processes.
- Keep write/delete/upload/spend authority separate from network configuration.
  Public-only egress is not permission to upload private workspace content.
- Provide bounded attempts/spend and an operator stop action that terminates
  owned descendants, browser sessions, MCP jobs, and remote resources where
  supported. Lost termination evidence must be reported as unknown/orphaned.
- Preserve recoverable workspace revisions/backups outside agent write access.
  Offer dedicated-account/VM deployment guidance; do not silently change the
  host account, firewall, backup policy, or install system services.

## Focused Threat Review

- URL credentials, unexpected schemes/ports, malformed hostnames, IPv4/IPv6 and
  mapped addresses, trailing dots, IDNA, and alternate IP representations.
- DNS rebinding and mixed public/private answers; redirects and proxy behavior.
- Browser subresources, frames, script-driven navigation, WebSockets, downloads,
  and redirects: top-level URL validation alone is insufficient.
- MCP resource metadata, authorization-server metadata, issuer consistency,
  endpoint substitutions, registration/token calls, and cross-origin redirects.
- Authorization headers/tokens must not follow untrusted destinations. Separate
  provider/MCP credential context from generic fetching.
- Body/time/redirect limits, metadata parse failures, and redaction of errors.
- Remote terminal host-key verification, scoped private-host authorization,
  credential forwarding, transfer/archive traversal, and remote enforcement of
  strict filesystem/process/network limits. SSH connectivity alone is not isolation.
- Cloud lease/provisioning consent, termination evidence after disconnect/restart,
  and cleanup authorization limited to CaberOS-owned resource IDs.

## Implementation Units And Delivery Order

Each unit is a candidate coherent commit, not authorization to commit.

1. Inventory request/process/secret paths and supported host backends. Record
   current evidence versus gaps, choose enforcement mechanisms, and build a
   per-platform capability matrix. Do not enable broader restrictions blindly.
2. Enforce strict worker filesystem/environment/process boundaries with W11.
   Test unavailable-backend refusal and no open-execution fallback.
3. Harden the shared destination policy and service-scoped exception contract;
   add authenticated, audited grants, revocation, and compatibility handling.
4. Route browser traffic through the chosen enforced boundary. Prove direct
   bypass is denied, or mark affected paths unavailable.
5. Enforce MCP process isolation and SDK discovery/token endpoint policy,
   including saved metadata, refresh, reconnect, and legitimate local services.
6. Verify control-plane separation, stop/cleanup behavior, secret redaction,
   resource limits, and recovery. Add operator-facing readiness and host guidance.
7. Re-run integrated attack fixtures after W9 search, W10 speech, and W11
   terminals are complete. W7 starts early and remains a cross-workstream gate;
   final release acceptance is W12 (integration and release), last.

## Verification

Use local synthetic HTTP/DNS/redirect fixtures and mocked SDK transport; do not
scan real private networks or send real credentials. Test default deny, narrowly
allowed localhost service, revocation, redirect-to-private, mixed DNS results,
browser subrequests, hostile metadata, endpoint mismatch, and refresh.

Document the actual enforcement mechanism and unresolved risks. A passing URL
parser test is not evidence of browser-level or connection-level enforcement.

Use isolated OS-enforced test environments with dummy credentials, bounded
resources, sanitized environments, and no real external egress. A browser network
test must observe allowed and denied connections at the actual boundary, not
merely assert that a validation function was called. Exercise each claimed
platform/backend; mark unavailable platforms not run, not passed.

Required evidence maps to S01-S10 in the acceptance matrix: fetch/dial policy;
browser traffic and bypass attempts; scoped exceptions/revocation; hostile MCP
metadata/refresh; worker filesystem/network/environment isolation; credential
custody; control-plane separation; resource/stop/recovery behavior; platform
readiness; and W9-W11 integration.

## Exit And Release Gate

W7 closes only when each included execution path has an enforced, tested
boundary or is explicitly unavailable. A documented exploitable bypass is a
blocker for that path, not an accepted security guarantee. Record residual risks
and product scope decisions separately from passing tests. Full-suite counts
alone cannot mark security scenarios passed.

The initial results in `test_result/2026-11-05-network-policy.md` are partial
evidence only. No blanket host-security, browser-isolation, or MCP-safety claim
is supported by that record.
