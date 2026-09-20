# Platform Support — Sandbox Backends

CaberOS runs shell commands in a sandbox to isolate agents from the host filesystem and network. The sandbox backend available on your machine depends on your platform and installed tools.

> **Key principle:** Shell isolation is **opt-in, per-agent**. If no sandbox is available, shell commands are refused with a clear reason, but all other capabilities remain functional — files, web, memory, skills, and MCP tools are unaffected.

## Support tiers

CaberOS tries backends in platform-specific order: native sandboxes first (fastest, zero dependencies), then Docker (cross-platform fallback), then refusal with a clear reason.

### macOS (Apple Silicon / Intel)

| Candidate | Name | Status | Notes |
|---|---|---|---|
| `seatbelt` | macOS Sandbox (`sandbox-exec`) | ✓ Built-in | Zero install, uses built-in `sandbox-exec`. Fastest option. |
| `docker` | Docker Desktop / Engine | ✓ Fallback | If Docker is installed and running. Common via Docker Desktop. |
| — | Shell disabled | ✗ Unavailable | No sandbox found. Install Docker or use Linux. |

**Try first:** `seatbelt` (built-in). If you need to run agents on Intel macOS or prefer Docker, the `docker` fallback works.

### Linux (x86-64 / ARM)

| Candidate | Name | Status | Notes |
|---|---|---|---|
| `bwrap` | Bubblewrap | ✓ Built-in | Zero install on most distros. Run `sudo apt install bubblewrap` (Debian/Ubuntu) or equivalent. |
| `docker` | Docker Engine | ✓ Fallback | If Docker daemon is running. |
| — | Shell disabled | ✗ Unavailable | No sandbox found. Install bubblewrap or Docker Engine. |

**Try first:** `bwrap` (requires no daemon). If not available, Docker works as a fallback.

### Windows (x86-64, Windows 11 Pro / Enterprise)

| Candidate | Name | Status | Notes |
|---|---|---|---|
| — | WSL2 + bwrap | ✗ Not yet | Planned for future release (PR #31, separate from this branch). |
| `docker` | Docker Desktop | ✓ Only trusted option | Requires Docker Desktop installed and running. |
| `mxc` | Microsoft Execution Containers | ⚠ Experimental, opt-in only | Never auto-selected — see below. Not a substitute for Docker. |
| — | Shell disabled | ✗ Unavailable | No candidate found or usable. |

**Today:** Docker is the only *trusted* sandbox option on Windows. **Important caveat:** Docker Desktop on Windows commonly runs its own Linux VM via WSL2 by default (see below).

> **Note on WSL2:** If you install Docker Desktop on Windows, it typically uses WSL2 internally to run the Linux Docker daemon. Choosing `docker` as the sandbox backend means you're using Docker's container isolation, not "zero WSL anywhere on the machine." To use a native WSL2 sandbox (without Docker), wait for the WSL2+bubblewrap PR to be merged.

#### MXC — genuinely no WSL, but experimental (opt-in only)

[Microsoft Execution Containers](https://github.com/microsoft/mxc) is a real, working Windows-native sandbox with **no WSL involved at all** — verified by hand on this machine (Windows build 26200, `ProcessContainer`/"base-container" tier). Two things are both true:

1. **It works.** A real command executed inside the container and a real file landed on the real host filesystem, with zero elevation needed at runtime.
2. **Microsoft's own SDK says, verbatim: "no MXC profiles should be treated as security boundaries currently."** That directly conflicts with this project's rule that shell must never run unprotected. So CaberOS never auto-selects it, even when it works — an operator must explicitly set `CABEROS_ENABLE_EXPERIMENTAL_MXC=1`, and `GET /api/health` reports it as `state: "experimental"`, never `"available"`, with Microsoft's caveat included in `reason`.

**Setup (one-time, elevated):**

```powershell
# Requires @microsoft/mxc-sdk installed (npm install @microsoft/mxc-sdk);
# there is no standalone installer yet — CaberOS does not bundle this binary.
# From an elevated ("Run as administrator") prompt, once:
wxc-host-prep.exe prepare-system-drive
```

This is a single command, verified to persist without elevation on every run afterward — comparable in cost to WSL2's `wsl --install`, but no reboot and no Linux distribution to configure.

**Known limitation, verified by hand:** `prepare-system-drive` only grants access to the Windows *system drive* (`C:` on virtually every install). A workspace on any other drive (e.g. `D:`) fails with "Access is denied" — CaberOS detects this and fails fast with an explanation instead of the bare OS error, rather than attempting the doomed call.

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
  "reason": null
}
```

Or when no sandbox is available:

```json
{
  "kind": "none",
  "state": "unavailable",
  "reason": "No sandbox available. bwrap: Bubblewrap is not installed. / docker: Docker is installed but the daemon is not responding. Is it running?"
}
```

**Field meanings:**

| Field | Value | Meaning |
|---|---|---|
| `kind` | `seatbelt`, `bwrap`, `docker`, `mxc`, `none` | The backend CaberOS is using (or would use). |
| `state` | `available` | Sandbox is ready for shell commands and is a trusted security boundary. |
| `state` | `experimental` | Commands genuinely run, but the backend's own vendor does not yet call it a security boundary (MXC only, opt-in). See `reason` for the caveat. |
| `state` | `unavailable` | Shell commands will be refused. See `reason`. |
| `reason` | string or null | For `unavailable`: why, listing every candidate tried. For `experimental`: the trust caveat to show the operator. Null only when `state` is `available`. |

### Full health response

The `/api/health` endpoint also reports provider and agent counts:

```json
{
  "status": "ok",
  "database": "connected",
  "providers": 2,
  "agents": 3,
  "active_runs": 0,
  "sandbox": {
    "kind": "docker",
    "state": "available",
    "reason": null
  },
  "timestamp": "2026-09-17T10:30:45.123456Z"
}
```

## Requirements by backend

### Seatbelt (macOS)

- **Platform:** macOS (any version with `sandbox-exec`)
- **Install:** None — built into macOS
- **Network:** Disabled by default; agents can request `allow_network=True` per-command
- **Performance:** Native, ~1ms per sandbox setup
- **Filesystem access:** Read-only to system; writes limited to agent workspace + `/tmp`

### bwrap (Linux)

- **Platform:** Linux (any distribution)
- **Install:** `sudo apt install bubblewrap` (Debian/Ubuntu) or equivalent for your distro
- **Network:** Disabled by default; agents can request `allow_network=True` per-command
- **Performance:** Native namespace-based isolation, ~1ms per sandbox setup
- **Filesystem access:** Read-only to system; writes limited to agent workspace + shared temp dirs
- **Container caveat:** bwrap may not work inside containers or GitHub Actions runners (namespace limitations). Docker is a fallback in those environments.

### MXC (Windows, experimental, opt-in)

- **Platform:** Windows 11 24H2+ (build 26100+) for the stable `ProcessContainer` tier — verified on build 26200. Not Windows Insider-only for this tier (only Microsoft's `IsolationSession` backend requires Insider Preview, and CaberOS does not use it).
- **Enable:** Set `CABEROS_ENABLE_EXPERIMENTAL_MXC=1`. Never auto-selected otherwise.
- **Install:** No standalone installer — `npm install @microsoft/mxc-sdk`, then either add its `bin/<arch>/wxc-exec.exe` to PATH or set `CABEROS_MXC_EXE_PATH` to it directly. CaberOS's Windows desktop packaging does not yet bundle this.
- **One-time setup:** `wxc-host-prep.exe prepare-system-drive`, elevated, once. Verified persistent afterward with zero elevation.
- **Trust:** Not a verified security boundary — Microsoft's own words, not CaberOS's caution. Reported as `state: "experimental"`, never `"available"`.
- **Filesystem access:** System-drive workspaces only (verified limitation of `prepare-system-drive`). A workspace on a different drive is refused with an explanation before ever calling the binary.
- **Network:** Disabled by default (`network.defaultPolicy: "block"`); agents can request `allow_network=True` per-command.
- **Timeout behavior:** Best-effort process kill on timeout — unlike Docker, there is no separate "container kill" verb in this CLI, and whether killing `wxc-exec.exe` reliably tears down everything it spawned has not been verified live.

### Docker (all platforms)

- **Platform:** macOS, Linux, Windows
- **Install:** [Docker Desktop](https://www.docker.com/products/docker-desktop) or Docker Engine
- **Start:** Ensure the Docker daemon is running (`docker ps` should work)
- **Image:** `alpine:3.20` — pulled once during the first probe (not on the first command, so image pulls don't eat into command timeouts)
- **Network:** Disabled by default (`--network none`); agents can request `allow_network=True` per-command
- **Container naming:** `caberos-sandbox-<uuid>` — cleaned up automatically after command completion
- **Performance:** ~100-200ms per sandbox setup (container start + workspace mount). Slower than native backends but more portable.
- **Filesystem access:** Workspace is bind-mounted to `/workspace` inside the container; container sees only its `/workspace` and system libraries
- **Timeout behavior:** On timeout, CaberOS runs `docker kill <container>` to stop the actual container (not just the local `docker run` client process)

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

Seatbelt is built-in. To use Docker as a fallback:

```bash
# Download Docker Desktop from https://www.docker.com/products/docker-desktop
# Or via Homebrew:
brew install docker
```

### Linux (Debian/Ubuntu)

Install bubblewrap:

```bash
sudo apt update && sudo apt install bubblewrap
# Verify:
which bwrap
```

To also support Docker:

```bash
sudo apt install docker.io
sudo systemctl start docker
```

### Windows

Install Docker Desktop (the only sandbox option today):

1. Download [Docker Desktop for Windows](https://www.docker.com/products/docker-desktop)
2. Run the installer and restart Windows
3. Launch Docker Desktop (it starts the daemon automatically)
4. Verify: `docker ps` should work in PowerShell

To check that CaberOS can reach the Docker daemon after installation:

```powershell
# Restart the backend (or wait for the next health check)
# Then query the health endpoint and look for "kind": "docker", "state": "available"
```

## Troubleshooting

### "No sandbox available" on macOS

Seatbelt is built-in, so this should not happen. If it does:

```bash
# Verify sandbox-exec is available:
which sandbox-exec

# If not found, reinstall Xcode Command Line Tools:
xcode-select --install
```

If you prefer Docker, install Docker Desktop and restart the backend.

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

### "Docker is installed but the daemon is not responding" (any platform)

The Docker daemon is not running. Start it:

- **macOS / Windows:** Launch Docker Desktop
- **Linux:** `sudo systemctl start docker`

Then restart the CaberOS backend or wait for the next health check.

### Docker pull times out

If the first health check hangs or times out:

```bash
# Manually pull the image (gives you progress feedback):
docker pull alpine:3.20

# Then restart the backend
```

The probe waits up to 120 seconds for the image pull; if your connection is slow, this is expected.

### Shell commands timeout frequently on Windows

The `docker run` → `alpine` container start sequence on Windows can be slow (200-500ms per command). If commands are timing out, either:

1. Increase `AGENTOS_SANDBOX_TIMEOUT` in your config (default: 30 seconds)
2. Look for a WSL2+bubblewrap option when PR #31 is merged

## Defaults in different setups

| Setup | Native | Fallback | Status |
|---|---|---|---|
| Desktop app (macOS) | seatbelt | docker | Native if Seatbelt works |
| Local dev (macOS) | seatbelt | docker | Native if Seatbelt works |
| Local dev (Linux) | bwrap | docker | Native if bwrap works |
| Docker (any platform) | none (inside container) | docker (host docker socket) | Requires `--network host` or socket mount to reach host Docker |
| CI/CD (Linux, GitHub Actions) | bwrap fails (no namespaces) | docker | Docker only |
| Windows + local dev | none | docker | Docker is the trusted default; MXC available opt-in only |

## See also

- `docs/spec-v0.1.md` — D28 (Sandbox layer) for architecture details
- `backend/src/agentos/sandbox/` — Backend implementations (seatbelt.py, bwrap.py, docker.py, mxc.py, base.py)
- `AGENTS.md` — syscall layer and sandbox integration
