# Platform Support — Sandbox Backends

CaberOS runs shell commands in a sandbox to isolate agents from the host filesystem and network. The sandbox backend available on your machine depends on your platform and installed tools.

> **Key principle:** Shell isolation is **opt-in, per-agent**. If no sandbox is available, shell commands are refused with a clear reason, but all other capabilities remain functional — files, web, memory, skills, and MCP tools are unaffected.

## Support tiers

CaberOS defaults to the OS-native terminal path: Seatbelt on macOS, bubblewrap
on Linux, and bundled Microsoft Execution Containers (MXC) on Windows.
If the native backend is unavailable or a command fails, that result is reported
directly. CaberOS does not probe, start, install, or switch to Docker as recovery.
Docker sandbox setup is future explicit opt-in work. Per-agent strict/open
settings are unchanged; a strict-mode failure never enables open execution.

### macOS (Apple Silicon / Intel)

| Candidate | Name | Status | Notes |
|---|---|---|---|
| `seatbelt` | macOS Sandbox (`sandbox-exec`) | ✓ Built-in | Zero install, uses built-in `sandbox-exec`. Fastest option. |
| — | Shell disabled | ✗ Unavailable | Native readiness failed; see the reported reason. |

**Default:** `seatbelt` (built-in) on both Apple Silicon and Intel. No Docker fallback.

### Linux (x86-64 / ARM)

| Candidate | Name | Status | Notes |
|---|---|---|---|
| `bwrap` | Bubblewrap | ✓ Built-in | Zero install on most distros. Run `sudo apt install bubblewrap` (Debian/Ubuntu) or equivalent. |
| — | Shell disabled | ✗ Unavailable | Bubblewrap is missing or cannot provide isolation. |

**Default:** `bwrap` (requires no daemon). If unavailable, strict terminal execution is refused.

### Windows (x86-64, Windows 11 24H2 / build 26100 or newer)

| Candidate | Name | Status | Notes |
|---|---|---|---|
| `mxc` | Microsoft Execution Containers | ⚠ Experimental, bundled | Ships inside the installer. One-time, one-click setup. No Docker, no WSL. |
| — | Shell disabled | ✗ Unavailable | MXC is not set up yet, or the Windows build is too old. |

Docker is deliberately **not** a Windows candidate and WSL2 is not used: the desktop app must work without asking anyone to install either.

**Desktop app:** the installer (`CaberOS_<version>_x64-setup.exe`, per-user, no admin prompt) is built by `npm run desktop:build:windows`. It needs no Python, Docker or WSL. It bundles MXC under `resources/mxc` (`wxc-exec.exe`, `wxc-host-prep.exe`, and the MIT license), fetched at build time from `@microsoft/mxc-sdk` and pinned by SHA-256 in `scripts/fetch-mxc.mjs` — a changed file fails the build. Both binaries are Authenticode-signed by Microsoft.

**First run:** open **Observability → Health**. Until MXC is set up, *Shell sandbox* reads "needs setup" with an **Enable shell sandbox** button. Windows then shows its own permission prompt once, because granting containers access to the system drive needs administrator rights. The grant is persistent: it survives reboots and every later command runs with no prompt. Declining changes nothing; shell simply stays off.

The same setup by hand, from an elevated prompt:

```powershell
& "$env:LOCALAPPDATA\CaberOS\resources\mxc\wxc-host-prep.exe" prepare-system-drive
```

#### What MXC is — and is not

MXC genuinely works (verified by hand, Windows build 26200, `ProcessContainer` / "base-container" tier): commands run inside a container and real files land on the real host disk. But **Microsoft's own SDK says, verbatim: "no MXC profiles should be treated as security boundaries currently."** CaberOS therefore reports it as `state: "experimental"`, never `"available"`, and shows that caveat in the dashboard. It is meaningfully better than running commands unsandboxed, and weaker than Seatbelt or bwrap.

The policy CaberOS applies (confirmed against the real binary's validator, not the SDK's published examples, which differ):

| Area | Behavior |
|---|---|
| Writes | Only the agent's own workspace |
| Reads | Windows directory, plus whatever the container can read by default (e.g. Program Files). **Your user profile is unreadable** (`.ssh`, `.aws`, browser data, etc.) |
| Network | Blocked by default; allowed per command when the agent requests it |
| UI subsystem | Enabled — console programs such as `whoami.exe` and PowerShell fail to start without it |
| Clipboard / input injection | Blocked |

Measured on a real machine: `echo`, `whoami`, PowerShell, directory listing and exit codes all work in roughly 110–530 ms per command; writes to `C:\Windows`, reads of the user profile, and network without permission are all denied.

#### Known limitations (verified by hand)

- **System drive only.** `prepare-system-drive` grants access to the Windows system drive and nothing else. A workspace on another drive fails with "Access is denied"; CaberOS detects this and fails fast with an explanation. The desktop app's default data directory is already on the system drive.
- **Per-user tool installs are invisible.** Because the user profile is unreadable, programs installed under it — for example Python in `%LOCALAPPDATA%\Programs` (`py` reports "No installed Python found") or Node via a version manager — cannot be started. Tools in Program Files and Windows work.
- **`git` fails inside the container.** Git stats every parent directory of the workspace, and the container may not read the user profile that contains it. Agents that need git should run in open sandbox mode.
- **`%TEMP%` is not writable.** MXC always overrides `TEMP`/`TMP` and denies writes there, so tools that stage files in the temp directory fail. Write to the workspace instead.
- **The environment is an allowlist.** Host environment variables, including API keys and tokens, are never forwarded. Only Windows system variables are passed. `HOME`, `USERPROFILE` and `APPDATA` point into the workspace, and `PATH` lists Windows directories first, then host `PATH` entries under Windows or Program Files.
- **Commands run through `cmd.exe /c`**, not a POSIX shell. Agents need Windows syntax; the terminal tool description says so.
- **Timeouts are best-effort:** killing `wxc-exec.exe` is the only lever, and whether it tears down everything it spawned has not been verified.
- **Windows 11 24H2 (build 26100) or newer** for the stable tier. The Insider-only `IsolationSession` backend is not used.

## How to tell what you have

### Check via health endpoint

Query the system health endpoint to see what backend is currently available:

```bash
# Requires operator authentication (use your dashboard password)
curl -H "Authorization: Bearer <session_token>" http://localhost:8081/api/health | jq .sandbox
```

**Response format:**

```json
{
  "kind": "seatbelt",
  "state": "available",
  "reason": null,
  "setup_required": false
}
```

On Windows with MXC working:

```json
{
  "kind": "mxc",
  "state": "experimental",
  "reason": "Commands run in a Windows container that limits file access to the agent workspace ...",
  "setup_required": false
}
```

And when MXC is installed but waiting on its one-time setup:

```json
{
  "kind": "none",
  "state": "unavailable",
  "reason": "No sandbox available. mxc: MXC is present (tier: 'base-container') but not yet set up. One-time setup needed: ...",
  "setup_required": true
}
```

**Field meanings:**

| Field | Value | Meaning |
|---|---|---|
| `kind` | `seatbelt`, `bwrap`, `mxc`, `none` | The default OS-native backend, or unavailable. Docker is not auto-selected. |
| `state` | `available` | Sandbox is ready for shell commands and is a trusted security boundary. |
| `state` | `experimental` | Commands genuinely run, but the backend's own vendor does not yet call it a security boundary (MXC on Windows). See `reason` for the caveat. |
| `state` | `unavailable` | Shell commands will be refused. See `reason`. |
| `reason` | string or null | For `unavailable`: why, listing every candidate tried. For `experimental`: the trust caveat to show the operator. Null only when `state` is `available`. |
| `setup_required` | boolean | `true` when the only thing missing is a one-time, user-approved host setup the desktop app can run (the **Enable shell sandbox** button). `false` when something must be installed instead. |

An `unavailable` result is **not cached**: each health poll and shell call
rechecks native readiness, so finishing native setup can take effect without
restarting the app. Starting Docker does not affect this result.

### Full health response

The `/api/health` endpoint also reports provider and agent counts, and the gateway `version`:

```json
{
  "status": "ok",
  "database": "connected",
  "providers": 2,
  "agents": 3,
  "active_runs": 0,
  "sandbox": {
    "kind": "mxc",
    "state": "experimental",
    "reason": "...",
    "setup_required": false
  },
  "version": "0.1.9",
  "timestamp": "2026-09-17T10:30:45.123456Z"
}
```

## Requirements by backend

### Seatbelt (macOS)

- **Platform:** macOS (any version with `sandbox-exec`)
- **Install:** None — built into macOS
- **Network:** Disabled by default; agents can request `allow_network=True` per-command
- **Readiness:** A cached synthetic self-check must prove workspace read/write
  and sibling-file read/write denial. Failure reports unavailable; CaberOS does
  not retry the old permissive profile.
- **Filesystem access:** The W7 worktree uses a default-deny profile. File data
  and execution are permitted only in the workspace and fixed Apple runtime/
  developer-tool directories. Only the workspace and `/dev/null` are writable.
  Global path metadata lookup is allowed, not arbitrary file contents.
- **Temporary files:** HOME, TMPDIR, TMP, and TEMP point to the selected
  workspace, not shared host `/tmp`. Agents sharing that workspace also share
  those files; this is not per-run private storage.
- **Compatibility:** Filesystem root, the operator home and its ancestors, and
  system-runtime-overlapping workspaces are refused. Arbitrary applications,
  Homebrew installations, and user-level runtime directories are not implicitly
  readable or executable. Tools depending on them may be unavailable.
- **Verification:** This new profile still needs isolated native macOS regression
  verification. The startup self-check is a narrow readiness check, not proof
  of complete host isolation or resource-limit enforcement.

### bwrap (Linux)

- **Platform:** Linux (any distribution)
- **Install:** `sudo apt install bubblewrap` (Debian/Ubuntu) or equivalent for your distro
- **Network:** Disabled by default; agents can request `allow_network=True` per-command
- **Performance:** Native namespace-based isolation, ~1ms per sandbox setup
- **Filesystem access:** Read-only to system; writes limited to agent workspace + shared temp dirs
- **Container caveat:** bwrap may not work inside containers or GitHub Actions
  runners (namespace limitations). Strict terminal execution then reports
  unavailable; there is no nested Docker fallback or host-socket recovery.

### MXC (Windows, experimental)

- **Platform:** Windows 11 24H2+ (build 26100+) for the stable `ProcessContainer` tier — verified on build 26200. Not Windows Insider-only for this tier.
- **Install:** None for end users — bundled in the installer. From a source checkout, set `CABEROS_MXC_EXE_PATH` to the `@microsoft/mxc-sdk` package's `bin/x64/wxc-exec.exe`, or put `wxc-exec` on PATH. The desktop shell sets this variable automatically from its resources.
- **One-time setup:** `wxc-host-prep.exe prepare-system-drive`, elevated, once — the dashboard button runs exactly this. Persistent afterward.
- **Trust:** Not a verified security boundary — Microsoft's words, not CaberOS's caution. Reported as `state: "experimental"`, never `"available"`.
- **Filesystem access:** Writes only to the agent workspace; user profile unreadable; system-drive workspaces only.
- **Network:** Disabled by default (`network.defaultPolicy: "block"`); agents can request `allow_network=True` per-command.
- **Performance:** ~110–530 ms per command; no VM and no daemon.
- **Timeout behavior:** Best-effort process kill — unlike Docker there is no separate "container kill" verb in this CLI.

### Docker Prototype (Future Explicit Opt-In)

This prototype is not connected to automatic terminal selection. Installing
Docker does not enable it. The following describes retained implementation
work, not a requirement for OS-native terminal execution or current setup UI.

- **Platform:** macOS, Linux. Not used on Windows.
- **Install:** [Docker Desktop](https://www.docker.com/products/docker-desktop) or Docker Engine
- **Start:** Ensure the Docker daemon is running (`docker ps` should work)
- **Image:** `alpine:3.20` must already be installed locally. Readiness checks
  inspect it without downloading; execution uses `--pull=never`. A missing or
  uninspectable image reports unavailable rather than triggering a download.
- **Network:** Disabled by default (`--network none`); agents can request `allow_network=True` per-command
- **Container naming:** `caberos-sandbox-<uuid>` — cleaned up automatically after command completion
- **Performance:** ~100-200ms per sandbox setup (container start + workspace mount). Slower than native backends but more portable.
- **Filesystem access:** Workspace is bind-mounted to `/workspace` inside the container; container sees only its `/workspace` and system libraries
- **Timeout behavior:** On timeout, CaberOS runs `docker kill <container>` to stop the actual container (not just the local `docker run` client process)
- **Background lifecycle (W7 worktree):** The controller records a generated
  resource name before creating and attaching to a container. Close/cancel/
  shutdown and restart reconciliation remove only the recorded, ownership-
  labeled resource. Failed confirmation reports `orphaned`, not `closed`.
  Native daemon and migration verification remain pending.
- **Requested resource limits:** 256 MiB memory with no additional swap, one
  CPU, 64 PIDs, 256 file descriptors, 64 MiB per file, and a private 32 MiB
  noexec temp mount. The image is read-only and capabilities are dropped.
  The host-mapped user is non-root; root controllers select UID/GID 65534 and
  may encounter workspace permission failures. CaberOS does not chmod the
  workspace or weaken isolation to recover. Total workspace disk quotas and
  live daemon enforcement remain unverified/open.

## What happens when no sandbox is available

When `GET /api/health` shows `state: "unavailable"`, running shell commands returns this error:

```
Shell commands are disabled on this machine. No sandbox available. ...
All other capabilities — files, web, memory, skills, knowledge and MCP tools — are unaffected.
```

The agent can still:

- Read and write files via `file_read` / `file_write`
- Search the web via `web_search` / `web_fetch`
- Load and use skills
- Query memory
- Call MCP tools
- Run sub-agents

Only the `terminal` / `shell` capability is refused.

## Installation quick-start

### macOS

Seatbelt is built-in. No Docker installation or daemon is required. If native
readiness fails, inspect the reported reason; there is no automatic substitute.

### Linux (Debian/Ubuntu)

Install bubblewrap:

```bash
sudo apt update && sudo apt install bubblewrap
# Verify:
which bwrap
```

If bubblewrap cannot run in this environment, strict terminal execution remains
unavailable. Docker setup is deferred, not an installation recovery step.

### Windows

Nothing to install beyond CaberOS itself:

1. Run `CaberOS_<version>_x64-setup.exe`
2. Open CaberOS → **Observability → Health**
3. Click **Enable shell sandbox** and approve the Windows permission prompt (once)
4. *Shell sandbox* now reads `mxc (experimental)`

To verify from a terminal instead:

```powershell
# Look for "kind": "mxc", "state": "experimental" under "sandbox"
curl.exe -H "Authorization: Bearer <session_token>" http://127.0.0.1:51718/api/health
```

## Troubleshooting

### "No sandbox available" on macOS

Seatbelt is built-in, but its readiness check can still fail. Inspect the
reported reason and verify that the OS executable is available:

```bash
# Verify sandbox-exec is available:
which sandbox-exec
```

Failure is reported directly; CaberOS does not switch backends or weaken the
native profile.

### "bwrap: Bubblewrap is not installed" on Linux

```bash
# Install bubblewrap for your distro:
# Debian/Ubuntu:
sudo apt install bubblewrap

# Fedora/RHEL:
sudo dnf install bubblewrap

# Alpine:
apk add bubblewrap

# Verify:
which bwrap
bwrap --version
```

### Docker Is Installed But Native Terminal Is Still Unavailable

This is expected: native terminal health does not probe Docker. Starting its
daemon or installing an image does not enable a fallback. Explicit Docker
sandbox setup is future work; it is not needed to use the OS-native terminal.

### "MXC is present … but not yet set up" (Windows)

Click **Enable shell sandbox** in Observability → Health, or run the elevated command shown under *Windows → First run*. If you dismissed the Windows permission prompt, click the button again.

### "wxc-exec.exe was not found" (Windows)

Installed builds bundle it, so this means a damaged install — reinstall CaberOS. From a source checkout, set `CABEROS_MXC_EXE_PATH` to the SDK's `bin/x64/wxc-exec.exe`.

### "cannot access workspaces outside the system drive" (Windows)

MXC's one-time grant covers only the system drive. Keep agent workspaces on `C:` (the default data directory is).

### A command works in PowerShell but "is not recognized" inside CaberOS (Windows)

The container cannot read your user profile, so per-user installs (Python, Node version managers, `~\bin`) are not visible. Use tools installed system-wide.

## Defaults in different setups

| Setup | Native | Fallback | Status |
|---|---|---|---|
| Desktop app (macOS) | seatbelt | none | Native, or an explained unavailable state |
| Desktop app (Windows) | mxc (bundled) | none | Experimental; one-time setup; no Docker or WSL |
| Local dev (macOS) | seatbelt | none | Native, or an explained unavailable state |
| Local dev (Linux) | bwrap | none | Native, or an explained unavailable state |
| Local dev (Windows) | mxc | none | Needs `CABEROS_MXC_EXE_PATH` and the one-time setup |
| Docker deployment | Linux bwrap when supported | none | No host Docker socket or nested fallback |
| CI/CD (Linux, GitHub Actions) | bwrap when namespaces are supported | none | Otherwise strict terminal execution is unavailable |

## See also

- `docs/spec-v0.1.md` — D28 (Sandbox layer) for architecture details
- `backend/src/agentos/sandbox/` — Backend implementations (seatbelt.py, bwrap.py, docker.py, mxc.py, base.py)
- `scripts/fetch-mxc.mjs` — how the Windows installer's MXC binaries are fetched and verified
- `AGENTS.md` — syscall layer and sandbox integration
