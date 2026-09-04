# Platform support

This is the canonical statement of which platforms CaberOS supports and what
works on each. README, release notes and `AGENTS.md` link here rather than
restating it, so there is one place to keep accurate.

## Support tiers

| Tier | Platform | Desktop app | Shell capability | Signed | Auto-update |
|---|---|---|---|---|---|
| **1 — Supported** | macOS ARM64 (Apple Silicon) | Yes (`.dmg`) | Full — Seatbelt | Ad-hoc | Yes |
| **2 — Beta** | Windows x64 | Yes (`-setup.exe`) | Requires WSL2 + bubblewrap | Planned | Yes |
| **3 — Community** | Linux x64 | Not yet | Full — bubblewrap | No | Best effort |
| **4 — Unsupported** | macOS Intel, Windows ARM64 | No | — | — | — |

Tier 1 blocks a release. Tier 2 blocks the beta track. Tier 3 is best-effort and
never blocks a release. Tier 4 platforms can still run CaberOS through Docker or
from source.

## What "shell capability" means

Agents can run shell commands through the `terminal` capability, and CaberOS
only allows that inside a real OS-level sandbox. Where no sandbox exists, the
capability is **explicitly disabled** rather than silently run unprotected.

This affects exactly one of the 22 built-in capabilities. Everything else —
chat, file read/write/search, web search and fetch, all three memory layers,
skills, the Knowledge Vault with citations, sub-agents, MCP tools, all four
external channels, scheduling and observability — is platform-neutral and works
identically everywhere.

### Per-platform detail

| Platform | Sandbox | Notes |
|---|---|---|
| macOS | `sandbox-exec` (Seatbelt) | Built into macOS, nothing to install. |
| Linux | `bubblewrap` | Install with `apt install bubblewrap`. |
| Windows | `bubblewrap` inside WSL2 | WSL2 runs a real Linux kernel, so isolation is genuine. |
| Windows without WSL2 | None | `terminal` is disabled and says why. Everything else works. |

## Enabling shell commands on Windows

```powershell
wsl --install                             # if WSL2 is not present yet
wsl -e sudo apt install bubblewrap        # inside your distribution
```

Then restart CaberOS. **Observability → Health** shows the sandbox state and
names anything still missing.

Known limitation: a sandboxed command cannot launch Windows executables
(`cmd.exe`, `powershell.exe`, anything under `/mnt/c/`). WSL routes those to the
Windows host over a Unix socket, which the sandbox blocks. Commands run against
the workspace, which is what agents need.

## How to tell what your machine has

`GET /api/health` reports the sandbox as:

```json
{
  "sandbox": {
    "kind": "wsl-bwrap",
    "state": "available",
    "reason": null
  }
}
```

- `kind` — `seatbelt`, `bwrap`, `wsl-bwrap`, or `none`
- `state` — `available`, `degraded`, or `unavailable`
- `reason` — what is missing and how to fix it, when not `available`

## Other ways to run CaberOS

Any platform, including Tier 4:

- **Docker** — `./scripts/docker.sh up`, then <http://localhost:8080>. Runs the
  Linux container with bubblewrap, so the shell capability works. On Windows
  this uses Docker Desktop's WSL2 backend.
- **From source** — see the Quick start in `README.md`.
