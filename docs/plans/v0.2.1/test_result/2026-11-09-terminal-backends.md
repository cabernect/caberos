# W11 — Terminal backends: local selection + execution seam (2026-11-09)

Scope delivered: plan gates 1–2 — adapter contract tests, `exec.terminal`
binding, explicit local backend selection, admission pinning, Tools card.
Commits `0b704fe` (transport seam) and `8f8a2e2` (binding/selection) on
`feat/v0.2.1`. Remote execution (SSH/Daytona/Modal) is **deferred**, not
partially implemented — the operator has no remote infrastructure to verify
against, and gate 5 requires an isolated fixture host plus real provider
accounts.

## Verified (synthetic)

- `pytest tests/test_terminal_binding.py` — **17 passed** (spec, save-time
  foreign-backend refusal, resolution, pinning, open-mode bypass,
  sync-path parity).
- `pytest tests/test_terminal_transport.py` — **4 passed** (fake remote
  process through start → pump → cursor read → bounded spool → close;
  termination reaches the handle's signal surface).
- Wider sweep (terminal/cleanup/cancellation/bindings/search/speech) —
  **174 passed, 1 failed**: `test_strict_mode_via_backend` is the
  pre-existing Seatbelt `/tmp` deny-root failure, reproduced on HEAD
  before this work — unrelated.
- `ruff check` + `ruff format` clean; frontend `npm run lint` 0 errors,
  `npm run build` clean.
- Dev DB migrated: `terminal_sessions.binding_revision` present.

## The pattern (what a remote driver must satisfy)

Introduced seam, designed so SSH/cloud drivers plug in without touching
registry semantics:

- **`SpawnedProcess` protocol** (`terminal/transport.py`) — the registry's
  minimal view: `stdout`/`stderr` as `asyncio.StreamReader`, `wait()`,
  `returncode`, `pid`, `send_signal(sig)`, `kill()`. A remote driver's
  signal surface is its remote-kill (e.g. `pkill` over the SSH channel);
  `os.getpgid` on a foreign pid fails soft and `send_signal` is the
  fallback — verified by the fake-process contract tests.
- **`TerminalTransport` protocol** — `spawn(argv, *, env, cwd) -> SpawnedProcess`.
  `LOCAL_TRANSPORT` preserves the subprocess path verbatim (process-group
  flags stay inside it, not in the registry). `registry.start(transport=...)`
  injects it; production keeps the default.
- **Backend resolution** (`terminal/resolution.py`) — binding → backend.
  Remote backends extend `LOCAL_BACKEND_OSES`-adjacent maps and
  `backend_named`-style selection; a remote "backend" supplies the launch
  plan while its transport supplies the process. Sandbox activation still
  precedes spawn; remote transports interpret argv/env/cwd on their own
  substrate.
- **Admission pin** — `binding_revision` + resolved `backend_kind` recorded
  per session; setting changes apply only to new sessions.

## Deferred (requires remote infrastructure to verify)

- **W11.3** — encrypted remote connection records, isolation metadata,
  lease records (schema is designed in the plan; not started).
- **W11.4** — bounded transfer manifests, staging, consent, conflict
  handling.
- **W11.5** — SSH driver end to end. Blocked on an isolated fixture host
  (container or throwaway account) — a driver without a verified remote
  kill would be exactly the selector placeholder the plan forbids.
- **W11.6** — Daytona/Modal drivers. Blocked on provider accounts; needs
  their real lifecycle/exec/file APIs verified before any adapter ships.
- **W11.7** — reconciliation, compute receipts, QA.

## Honest gaps in the delivered slice

- `binding_revision` pins provenance only — no revocation enforcement
  yet (plan admits mid-run revocation is W11.7 behavior).
- The card's readiness rows probe live on settings load; there is no
  explicit "test" action for local backends (nothing to test — local
  probes are the test).
- Remote backend names are deliberately absent from the `backend` option
  choices — adding them without drivers would be a selector-only
  placeholder.
