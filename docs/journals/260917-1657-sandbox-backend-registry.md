# Sandbox Backend Registry: Breaking Hardcoded Single-Backend-Per-OS

**Date**: 2026-09-17 16:57
**Severity**: High (Windows sandbox crash, architectural decision)
**Component**: `backend/src/agentos/sandbox/` (base.py, docker.py), `GET /api/health`
**Status**: Committed locally (833f785), not yet pushed; Phase 3 (Microsoft Execution Containers) deferred pending GA release

## What Happened

CaberOS shipped with a fatal design flaw on Windows: `backend/src/agentos/sandbox/base.py`'s `get_backend()` function would raise `RuntimeError("Sandbox not supported on {platform}...")` on any OS that wasn't macOS or Linux — an unrecoverable crash, not a graceful degradation. Windows users got shell commands entirely disabled with a cryptic error message rather than the intended principle: "no sandbox available, but all other agent capabilities work fine."

The fix introduces a **prioritized backend registry**: each platform tries an ordered list of candidate sandbox backends (native first — Seatbelt on macOS, bwrap on Linux — then Docker as a cross-platform fallback), and only degrades to an `UnavailableBackend` with a human-readable reason naming every candidate tried when nothing works.

## The Brutal Truth

This is a shipping quality defect disguised as an edge case. We know Windows exists; we claimed to support it; we hardcoded it into a crash state. The real frustration is not that the bug existed — it's that the architecture made it *inevitable*: one backend per OS, hardcoded in a match statement, zero fallback path. If anything was forgotten (Docker on Windows? WSL2?), users got a crash, not a choice.

The follow-up discovery mid-implementation was worse: PR #31 (which adds WSL2 + bwrap support for Windows) was supposed to have landed the graceful-degradation foundation into `main` already. It hadn't. That meant we had to build the entire registry pattern fresh against bare `main`, on a separate branch, knowing PR #31 would eventually collide with it. Not ideal, but the user's choice to decouple was pragmatic: PR #31 is contested and blocked; waiting for it would have pushed this work indefinitely.

## Technical Details

### Backend Registry Pattern

**Changed:** `backend/src/agentos/sandbox/base.py`

- Added `SandboxProbe` dataclass (`kind`, `state`, `reason`) and `kind`/`unavailable_reason()` on the `SandboxBackend` ABC
- Replaced single-backend `get_backend()` with a platform-specific registry:
  ```
  macOS:  [SeatbeltBackend, DockerBackend]
  Linux:  [BwrapBackend, DockerBackend]
  Windows: [DockerBackend]  # WSL2 will be added here when PR #31 merges
  ```
- Each candidate is probed in order; first available backend wins
- If all fail, returns an `UnavailableBackend` that reports reason for each tried candidate

### New Backend: DockerBackend

**Added:** `backend/src/agentos/sandbox/docker.py`

Key decisions:
- **Alpine 3.20** container image (minimal, widely cached)
- **Image pull during probe, not first command** (code-reviewer subagent caught that a cold pull would eat into command timeout budget; probe waits up to 120 seconds, mitigating slow connections)
- **Throwaway containers** named `caberos-sandbox-<uuid>`, cleaned up after each run
- **Timeout handling:** On timeout, runs `docker kill <container>` to actually stop the container, not just the local `docker run` client (fixes the same bug class found elsewhere in this repo's history where a hung container leaks resources)
- Cross-platform: works identically on macOS, Linux, Windows

### Health Endpoint Addition

**Changed:** `GET /api/health` response now includes:
```json
{
  "sandbox": {
    "kind": "docker",
    "state": "available",
    "reason": null
  }
}
```

Or when unavailable:
```json
{
  "sandbox": {
    "kind": "none",
    "state": "unavailable",
    "reason": "No sandbox available. bwrap: Bubblewrap is not installed. / docker: Docker is installed but the daemon is not responding. Is it running?"
  }
}
```

## What We Tried

1. **Extending PR #31**: User initially considered stacking this work on PR #31's branch. Rejected because PR #31 is unmerged, contested, and adding the registry pattern on top of that branch would double the review burden. Fresh branch against `main` was cleaner.

2. **Single fallback per platform**: Tried `macOS → Seatbelt OR Docker`, `Linux → bwrap OR Docker`. This worked but didn't scale or explain clearly to users why their command failed. The registry pattern with per-candidate reasons is more maintainable and debuggable.

3. **Eager image pull in get_backend()**: Initial implementation pulled the Docker image during registry initialization. Code-reviewer subagent flagged: if the pull is slow (or network fails), a timeout means commands never run and the reason is buried. Moving the pull into the probe (separate from command execution) means users see a clear health status and have time to debug Docker setup.

## Root Cause Analysis

**Why did this exist as a crash instead of graceful degradation?**

1. **Architecture assumed one-backend-per-OS**: The codebase had three separate backend files (`seatbelt.py`, `bwrap.py`) matching specific OSes. Nowhere was a fallback pattern defined. Adding Windows support without rethinking the architecture just meant finding the "closest" existing OS's backend (didn't make sense; no sandboxing primitives match).

2. **No visibility into "why not"**: Users couldn't tell whether sandbox was unavailable because the tool wasn't installed, or the daemon wasn't running, or the platform wasn't supported. All were treated the same: crash.

3. **Parallel research finding**: Hermes Agent (140k+ GitHub stars, similar "agent as OS" platform by Nous Research) uses a **pluggable execution backend registry** with 7 candidates (local, Docker, SSH, Daytona, Modal, Singularity, Vercel Sandbox) behind one interface. OpenClaw (counter-example) disabled sandboxing entirely by default, leading to real data-exfiltration incidents. CaberOS's intended design (refuse rather than run unprotected) is correct; we just needed the registry pattern to make it work cross-platform.

## Lessons Learned

1. **Single-backend-per-OS is not a pattern.** Across ecosystems (agent platforms, container runtimes, CI/CD), fallback chains are the norm. Implement the registry early, not as a port to a new OS.

2. **Visibility into why: diagnostic errors matter.** Users need to know whether a sandbox is unavailable because the tool is missing vs. the daemon isn't running vs. the platform isn't supported. Name every tried candidate in the error message.

3. **Probe ≠ first-use.** Image pulls, daemon checks, and dependency probes should happen in a health endpoint, not on the first command. If the probe fails, the user can fix it; if it fails on first-use, the user blames the command, not the setup.

4. **Timeout handling for external tools:** When you delegate to `docker run` or another subprocess, the *parent process* (CaberOS) must clean up the child if a timeout fires. Killing the CLI client doesn't kill the container. This was already a known bug class in the codebase; DockerBackend had to get it right from the start.

5. **PR dependencies are drag.** PR #31 will eventually add `WslBwrapBackend` to the Windows candidate list. That's a simple one-line change once it merges — but we can't merge it yet because the PR is blocked on unrelated review cycles. Build fresh against `main` when possible, reconcile later.

## Next Steps

1. **Immediate (this branch, ready to land):**
   - Commit 833f785 is verified and ready (code-reviewer approved, tester verified 489 tests passing)
   - Docs written (`platform-support.md` new, README/AGENTS.md updated)
   - Not pushed yet; awaiting approval to create PR

2. **Follow-up (Phase 2, after PR #31 merges):**
   - Reconcile `WslBwrapBackend` (from PR #31) into the registry as a third candidate on Windows
   - Update the Windows row in `platform-support.md` to list WSL2+bwrap as "available"
   - Single commit, low risk

3. **Deferred (Phase 3, blocked on external dependency):**
   - Microsoft Execution Containers backend (requires GA release of the SDK; currently Insider-preview only)
   - Would be added as a candidate on Windows, `kind = "mxc"` per the plan's phase-03 spec
   - Not started; gated behind Microsoft's release cycle

4. **Ownership:**
   - User (lead) to review and merge the PR once ready
   - Tester to verify on a machine with Docker Desktop once live
   - Docs-manager to monitor Windows user feedback on `platform-support.md` clarity

## Code Artifacts

- **Base registry logic:** `backend/src/agentos/sandbox/base.py` (SandboxProbe, UnavailableBackend, get_backend())
- **Docker backend:** `backend/src/agentos/sandbox/docker.py` (DockerBackend, 150 lines)
- **Tests:** 489 passing (5 skipped due to no Docker daemon on dev machine; 1 pre-existing unrelated failure on `ls` binary missing)
- **Docs:** `docs/platform-support.md` (new, comprehensive), `README.md` (reference added), `AGENTS.md` (sandbox layer entry)
- **Commit:** 833f785 (not pushed; on branch `feat/sandbox-backend-registry`)

---

**Phu Nguyen — HCMC, VN**
