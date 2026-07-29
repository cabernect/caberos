"""bwrap sandbox backend (Linux — bubblewrap)."""

import asyncio
import shutil
import time
from pathlib import Path

from .base import SandboxBackend, ShellResult


class BwrapBackend(SandboxBackend):
    """Linux bubblewrap (bwrap) backend."""

    def is_available(self) -> bool:
        return shutil.which("bwrap") is not None

    async def run_command(
        self, workspace_path: str, command: str, timeout: int = 30, allow_network: bool = False
    ) -> ShellResult:
        workspace = str(Path(workspace_path).resolve())
        args = [
            "bwrap",
            "--clearenv",
            "--setenv",
            "PATH",
            "/usr/bin:/bin",
            "--setenv",
            "HOME",
            "/workspace",
            "--ro-bind",
            "/usr",
            "/usr",
            "--ro-bind",
            "/bin",
            "/bin",
            "--ro-bind",
            "/lib",
            "/lib",
            "--ro-bind",
            "/lib64",
            "/lib64",
            "--dev",
            "/dev",
            "--proc",
            "/proc",
            "--tmpfs",
            "/tmp",
            "--bind",
            workspace,
            "/workspace",
            "--chdir",
            "/workspace",
            "--unshare-all",
            "--die-with-parent",
            "--new-session",
        ]
        if allow_network:
            args.append("--share-net")
        args.extend(["/bin/sh", "-c", command])

        start = time.monotonic()
        try:
            proc = await asyncio.create_subprocess_exec(
                *args,
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
