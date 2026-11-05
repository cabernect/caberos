# W7 — Execution lifecycle and MCP transport evidence (2026-11-05)

Scope: two committed slices — `48cde7e` (shared sync execution lifecycle,
bounded output, bwrap readiness hardening) and `92a5901` (MCP HTTP
destination enforcement via PolicyTransport, `netpolicy.resolve_destination`).

## Verified

- `pytest` on the touched modules: 254 passed, 4 skipped (native opt-in
  Seatbelt checks not enabled here). All coverage is synthetic —
  fake process pipes, mock transports, monkeypatched DNS. No host
  processes, real sandbox runs, or live sockets were used.
- `ruff check` + `ruff format --check` clean across 322 backend files.
- Sync `terminal` now retains ≤4 MiB per stream (same cap as background
  spooling), drains to EOF past the cap, and reports `truncated`.
- MCP HTTP requests (endpoint, SDK auth-flow discovery/registration/
  token/refresh, followed redirects) resolve through the shared policy
  and dial checked IPs with original Host/SNI; ambient proxies off,
  keep-alive off, per-request deadline enforced.
- Local-server exception narrowed to the literal configured origin;
  public hostnames no longer gain private access through DNS answers.

## Not verified / open

- Native Seatbelt/bwrap confinement, Docker cleanup, and real-process
  termination still lack an isolated runtime — synthetic only.
- Browser traffic enforcement still covers explicit navigation only;
  subresources, WebSockets, XHR/fetch, and rebinding inside Chrome are
  open and need a proxy/OS-boundary mechanism.
- Local MCP subprocess isolation (filesystem, env, network, resources)
  is untouched.
- CPU/RAM/disk limits on the OS-native path and escaped-descendant
  cleanup guarantees remain open.
- `truncated` on sync results is new interface surface; callers/UI
  should surface it rather than implying complete output.

## Compat notes

- Sync commands now truncate retained output at 4 MiB per stream —
  previously unbounded. Commands depending on larger captures should
  write to workspace files.
- MCP servers that relied on ambient HTTP(S)_PROXY env will now connect
  directly; metadata-advertised private endpoints fail closed.
