# 06 — Sandbox & Workspace

## Goal

Implement process-level sandboxing for shell and filesystem capabilities using the OS's native sandboxing primitive, and the workspace directory that bounds each agent's file access. No container runtime required — this is the same approach used by Claude Code and Codex.

## Spec references

- **I9** — Shell and filesystem are sandboxed
- **D14** — The agent has real authority, bounded by a sandbox
- **D28** — Shell execution is sandboxed at the process level (sandbox-exec on macOS, bwrap on Linux)
- **D29** — Workspace is a filesystem directory bounded to one agent
- **Stories 19-24** — set workspace, read/write files, run shell, approve dangerous commands, audit files, audit shell

## Dependencies

- [00-project-scaffold.md](00-project-scaffold.md) — needs the Python project
- [05-capabilities.md](05-capabilities.md) — file and shell tools route through the sandbox
- [07-pipeline.md](07-pipeline.md) — the pipeline orchestrates runs that use sandboxed capabilities

## Tasks

### 1. Define the Sandbox interface

`backend/src/agentos/sandbox/base.py`:

```python
class SandboxBackend(ABC):
    """Abstract sandbox backend. v0.1 implements Seatbelt (macOS) and bwrap (Linux)."""

    @abstractmethod
    async def run_command(self, workspace_path: str, command: str, timeout: int,
                          allow_network: bool = False) -> ShellResult:
        """Run a shell command in the sandbox with the workspace mounted."""

    @abstractmethod
    async def read_file(self, workspace_path: str, rel_path: str) -> str:
        """Read a file from the workspace via the sandbox."""

    @abstractmethod
    async def write_file(self, workspace_path: str, rel_path: str, content: str) -> None:
        """Write a file to the workspace via the sandbox."""

    @abstractmethod
    def is_available(self) -> bool:
        """Check if this backend's tool is installed."""

def get_backend() -> SandboxBackend:
    """Return the appropriate backend for the current platform."""
    if sys.platform == "darwin":
        return SeatbeltBackend()
    elif sys.platform.startswith("linux"):
        return BwrapBackend()
    else:
        raise RuntimeError(f"Sandbox not supported on {sys.platform}. Use WSL2 on Windows.")
```

### 2. Implement Seatbelt backend (macOS)

`backend/src/agentos/sandbox/seatbelt.py`:

- Uses `/usr/bin/sandbox-exec` (built into macOS, zero install)
- Generates an SBPL (Seatbelt Profile Language) profile per execution:
  - Deny all file reads and writes by default
  - Allow read/write to the workspace directory only
  - Deny all network access (unless `allow_network=True`)
  - Allow process execution (`/bin/sh`, `/usr/bin/env`, etc.)
  - Allow read access to system binaries (`/usr/bin`, `/bin`, `/usr/lib`)
- Executes: `sandbox-exec -p "<profile>" -- /bin/sh -c "<command>"`
- Captures stdout, stderr, exit code via `asyncio.create_subprocess_exec`
- Enforces timeout via `asyncio.wait_for`
- No host environment variables passed to the subprocess (clean env)
- **Clean environment setup** (Decision 6): set `PATH=/usr/bin:/bin` and `HOME=/workspace` in the subprocess environment. No other env vars. Never include the workspace in PATH.

Example SBPL profile:
```scheme
(version 1)
(deny file-write* (subpath "/"))
(allow file-write* (subpath "{workspace}"))
(deny file-read* (subpath "/Users"))
(allow file-read* (subpath "{workspace}"))
(allow file-read* (subpath "/usr/bin") (subpath "/bin") (subpath "/usr/lib") (subpath "/lib"))
(allow process-exec (subpath "/bin") (subpath "/usr/bin") (subpath "{workspace}"))
(deny network*)
```

### 3. Implement bwrap backend (Linux/WSL2)

`backend/src/agentos/sandbox/bwrap.py`:

- Uses `bwrap` (bubblewrap) — `apt install bubblewrap` or equivalent
- Executes:
```bash
bwrap \
  --clearenv \
  --setenv PATH /usr/bin:/bin \
  --setenv HOME /workspace \
  --ro-bind /usr /usr \
  --ro-bind /bin /bin \
  --ro-bind /lib /lib \
  --ro-bind /lib64 /lib64 \
  --dev /dev \
  --proc /proc \
  --tmpfs /tmp \
  --bind {workspace} /workspace \
  --chdir /workspace \
  --unshare-all \
  --share-net \  # only if allow_network=True, otherwise omit
  --die-with-parent \
  --new-session \
  /bin/sh -c "{command}"
```
- `--clearenv` clears all host environment variables (Decision 6); `--setenv` sets clean `PATH` and `HOME`
- `--unshare-all` creates new mount, user, PID, IPC namespaces
- `--bind {workspace} /workspace` mounts the workspace read-write
- Without `--share-net`, network is fully isolated
- Captures stdout, stderr, exit code via `asyncio.create_subprocess_exec`
- Enforces timeout via `asyncio.wait_for`

### 4. Implement workspace management

`backend/src/agentos/sandbox/workspace.py`:

```python
class WorkspaceManager:
    def create_workspace(self, agent_id: str, path: str | None = None) -> str:
        """Create workspace directory. Default: ~/agentos/workspaces/{agent_id}/"""

    def validate_path(self, workspace_root: str, path: str) -> str:
        """Resolve path relative to workspace root. Reject if it escapes."""

    def delete_workspace(self, agent_id: str) -> None:
        """Remove workspace directory (with confirmation)."""
```

Path validation (D29):
- Resolve `path` relative to `workspace_root`
- Check the resolved path is still inside `workspace_root` (no `../` escape, no absolute paths)
- Reject symlinks that point outside the workspace
- Return the safe absolute path

### 5. Wire file and shell tools to the sandbox

Update `backend/src/agentos/capabilities/tools/file.py` and `shell.py`:
- `file.read(path)` → `workspace.validate_path()` → `sandbox.read_file()`
- `file.write(path, content)` → `workspace.validate_path()` → `sandbox.write_file()`
- `file.list(path)` → `workspace.validate_path()` → list directory in sandbox
- `shell.run(command)` → `sandbox.run_command()`

### 6. Record shell audit trail

Each shell command execution records:
- The full command string
- stdout and stderr (truncated if oversized)
- Exit code
- Duration
- Written to the Run's audit record (D26 — "what did my agent do to my machine")

### 7. Create API routes for workspace management

`backend/src/agentos/api/workspace.py`:
- `GET /api/agents/{id}/workspace` — workspace path, size, file count
- `GET /api/agents/{id}/workspace/files` — list files in workspace
- `GET /api/agents/{id}/workspace/files/{path}` — read a file from workspace
- `DELETE /api/agents/{id}/workspace` — clear workspace (with confirmation)

## Files to create

- `backend/src/agentos/sandbox/__init__.py`
- `backend/src/agentos/sandbox/base.py`
- `backend/src/agentos/sandbox/seatbelt.py`
- `backend/src/agentos/sandbox/bwrap.py`
- `backend/src/agentos/sandbox/workspace.py`
- `sandbox/seatbelt_profile.sb` (template SBPL profile)
- `sandbox/bwrap_defaults.sh` (template bwrap invocation)
- `backend/src/agentos/api/workspace.py`
- `backend/tests/test_sandbox.py`

## Verification

- `sandbox-exec` is available at `/usr/bin/sandbox-exec` on macOS
- `shell.run("echo hello")` in sandbox → returns "hello", exit code 0
- `shell.run("cat /etc/passwd")` → blocked (not visible in sandbox)
- `shell.run("curl http://example.com")` → blocked (no network by default)
- `file.read("../etc/passwd")` → rejected by path validation before sandbox sees it
- `file.write("test.txt", "hello")` then `file.read("test.txt")` → returns "hello"
- Symlink in workspace pointing outside → rejected
- Shell command times out after configured duration → timeout error recorded
- Shell command and output appear in audit record
- Workspace created on agent creation, removed on agent deletion
- `is_available()` returns True on macOS, checks for bwrap on Linux
- `shell.run("python3 -c 'import os; print(os.listdir(\"/Users\"))'")` → should fail or return empty (filesystem blocked at kernel level)
- `shell.run("echo $PATH")` → returns `/usr/bin:/bin` (clean env verified)
- `shell.run("echo $HOME")` → returns `/workspace`
- Verify workspace is not in PATH (agent can't plant binaries)
- `uv run pytest tests/test_sandbox.py` passes
