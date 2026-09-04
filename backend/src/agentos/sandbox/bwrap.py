"""bwrap sandbox backend (Linux — bubblewrap)."""

import asyncio
import shutil
import time
from pathlib import Path

from .base import SandboxBackend, ShellResult

# The workspace is always mounted at this path inside the sandbox, regardless of
# where it lives on the host. Keeps the agent's view of its workspace stable.
WORKSPACE_MOUNT = "/workspace"


def build_probe_args() -> list[str]:
    """Arguments for the availability probe.

    bwrap can be installed yet unusable — containers without permission to
    create user namespaces, or WSL1, which has no real kernel. The only honest
    check is to actually run something.

    The probe uses the *same* profile as a real command, because bwrap starts
    from an empty root: a probe that omits the system bind mounts fails with
    "execvp /bin/sh: No such file or directory" even where the sandbox works
    perfectly, which would report every healthy machine as unavailable.
    """
    return build_bwrap_args("/tmp", allow_network=False)


def build_bwrap_args(workspace_mount_source: str, allow_network: bool) -> list[str]:
    """Build the bwrap argument vector, excluding the leading `bwrap` itself.

    `workspace_mount_source` is the workspace path as the Linux side sees it —
    a native path on Linux, or a /mnt/... path when called through WSL2. Shared
    by the Linux backend and the Windows WSL2 delegate so the isolation profile
    is defined in exactly one place.
    """
    args = [
        "--clearenv",
        "--setenv",
        "PATH",
        "/usr/bin:/bin",
        "--setenv",
        "HOME",
        WORKSPACE_MOUNT,
        "--ro-bind",
        "/usr",
        "/usr",
        "--ro-bind",
        "/bin",
        "/bin",
        "--ro-bind",
        "/lib",
        "/lib",
        # --ro-bind-try, not --ro-bind: /lib64 does not exist on every distro
        # (notably arm64 and musl systems). A hard bind makes bwrap fail to
        # start there, which the probe would then report as "no sandbox
        # available" and refuse the terminal capability outright - even though
        # /lib alone is sufficient on those systems.
        "--ro-bind-try",
        "/lib64",
        "/lib64",
        "--dev",
        "/dev",
        "--proc",
        "/proc",
        "--tmpfs",
        "/tmp",
        "--bind",
        workspace_mount_source,
        WORKSPACE_MOUNT,
        "--chdir",
        WORKSPACE_MOUNT,
        "--unshare-all",
        "--die-with-parent",
        "--new-session",
    ]
    if allow_network:
        args.append("--share-net")
    return args


async def run_sandboxed(
    argv: list[str], command: str, timeout: int, args: list[str]
) -> ShellResult:
    """Execute `argv + args + [sh -c command]` and normalise the result.

    Shared by the Linux backend and the Windows WSL2 delegate; `argv` is the
    launcher prefix (`["bwrap"]` locally, `["wsl.exe", "-e", "bwrap"]` via WSL2).
    """
    full = [*argv, *args, "/bin/sh", "-c", command]
    start = time.monotonic()
    try:
        proc = await asyncio.create_subprocess_exec(
            *full,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout_bytes, stderr_bytes = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        elapsed = int((time.monotonic() - start) * 1000)
        return ShellResult(
            stdout=stdout_bytes.decode("utf-8", errors="replace"),
            stderr=stderr_bytes.decode("utf-8", errors="replace"),
            exit_code=proc.returncode if proc.returncode is not None else -1,
            duration_ms=elapsed,
        )
    except TimeoutError:
        elapsed = int((time.monotonic() - start) * 1000)
        return ShellResult(
            stdout="",
            stderr=f"Command timed out after {timeout}s",
            exit_code=-1,
            duration_ms=elapsed,
        )


class BwrapBackend(SandboxBackend):
    """Linux bubblewrap (bwrap) backend."""

    kind = "bwrap"

    _probe_cache: bool | None = None

    def is_available(self) -> bool:
        if self._probe_cache is not None:
            return self._probe_cache
        if shutil.which("bwrap") is None:
            self._probe_cache = False
            return False
        # Probe: bwrap may be installed but fail in containers (e.g. GitHub
        # Actions) because loopback can't be created. Run a trivial command.
        import subprocess

        try:
            result = subprocess.run(
                ["bwrap", *build_probe_args(), "/bin/sh", "-c", "true"],
                capture_output=True,
                timeout=5,
            )
            self._probe_cache = result.returncode == 0
        except Exception:
            self._probe_cache = False
        return self._probe_cache

    def unavailable_reason(self) -> str | None:
        if self.is_available():
            return None
        if shutil.which("bwrap") is None:
            return "bubblewrap is not installed. Install it with: apt install bubblewrap"
        return "bubblewrap is installed but cannot create user namespaces here."

    async def run_command(
        self, workspace_path: str, command: str, timeout: int = 30, allow_network: bool = False
    ) -> ShellResult:
        workspace = str(Path(workspace_path).resolve())
        args = build_bwrap_args(workspace, allow_network)
        return await run_sandboxed(["bwrap"], command, timeout, args)
