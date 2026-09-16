"""bwrap sandbox backend (Linux — bubblewrap)."""

import asyncio
import shutil
import time
from pathlib import Path

from .base import SandboxBackend, ShellResult, kill_process_group


class BwrapBackend(SandboxBackend):
    """Linux bubblewrap (bwrap) backend."""

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
                [
                    "bwrap",
                    "--unshare-all",
                    "--die-with-parent",
                    "--new-session",
                    "/bin/sh",
                    "-c",
                    "true",
                ],
                capture_output=True,
                timeout=5,
            )
            self._probe_cache = result.returncode == 0
        except Exception:
            self._probe_cache = False
        return self._probe_cache

    def spawn_argv(
        self, workspace_path: str, command: str, allow_network: bool = False
    ) -> list[str]:
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
        return args

    def spawn_env(self, workspace_path: str) -> dict[str, str] | None:
        # bwrap --clearenv + --setenv already pins the child env.
        return None

    async def run_command(
        self, workspace_path: str, command: str, timeout: int = 30, allow_network: bool = False
    ) -> ShellResult:
        start = time.monotonic()
        proc = await asyncio.create_subprocess_exec(
            *self.spawn_argv(workspace_path, command, allow_network),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=True,
        )
        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            elapsed = int((time.monotonic() - start) * 1000)
            return ShellResult(
                stdout=stdout_bytes.decode("utf-8", errors="replace"),
                stderr=stderr_bytes.decode("utf-8", errors="replace"),
                exit_code=proc.returncode if proc.returncode is not None else -1,
                duration_ms=elapsed,
            )
        except TimeoutError:
            await kill_process_group(proc)
            elapsed = int((time.monotonic() - start) * 1000)
            return ShellResult(
                stdout="",
                stderr=f"Command timed out after {timeout}s",
                exit_code=-1,
                duration_ms=elapsed,
            )
