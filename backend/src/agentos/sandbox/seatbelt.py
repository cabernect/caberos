"""Seatbelt sandbox backend (macOS — sandbox-exec)."""

import asyncio
import shutil
import time
from pathlib import Path

from .base import SandboxBackend, ShellResult


def _build_profile(workspace: str, allow_network: bool) -> str:
    """Generate an SBPL profile for sandbox-exec.

    Strategy: allow all reads (the shell needs to read system libraries),
    deny all writes except to the workspace + a few system paths that
    Python/shell need to function, deny network by default.
    """
    workspace = str(Path(workspace).resolve())
    workspace = workspace.replace("\\", "\\\\").replace('"', '\\"')
    lines = [
        "(version 1)",
        '(deny file-write* (subpath "/"))',
        f'(allow file-write* (subpath "{workspace}"))',
        # /dev/null — needed for shell redirection (2>/dev/null, etc.)
        '(allow file-write* (literal "/dev/null"))',
        # /tmp (symlink → /private/tmp) — Python needs it for cache files,
        # xcrun, tempfile, etc.  Without this, python3 fails to start.
        '(allow file-write* (subpath "/private/tmp"))',
        # /dev/dtracehelper — used by DTrace instrumentation in Python
        '(allow file-write* (literal "/dev/dtracehelper"))',
        "(allow file-read*)",
        # Allow executing binaries from anywhere — /usr/bin/python3 on macOS
        # is a stub that spawns xcodebuild from /Applications/Xcode.app/...,
        # and other tools may live in /Library, /opt, etc.  The real sandbox
        # boundary is file-write restrictions + network denial, not exec paths.
        "(allow process-exec*)",
        "(allow process-fork)",
    ]
    if not allow_network:
        lines.append("(deny network*)")
    return "\n".join(lines)


class SeatbeltBackend(SandboxBackend):
    """macOS sandbox-exec backend — zero install, built into macOS."""

    def is_available(self) -> bool:
        return shutil.which("sandbox-exec") is not None

    async def run_command(
        self, workspace_path: str, command: str, timeout: int = 30, allow_network: bool = False
    ) -> ShellResult:
        profile = _build_profile(workspace_path, allow_network)
        ws_resolved = str(Path(workspace_path).resolve())
        start = time.monotonic()
        try:
            proc = await asyncio.create_subprocess_exec(
                "/usr/bin/sandbox-exec",
                "-p",
                profile,
                "--",
                "/bin/sh",
                "-c",
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=ws_resolved,
                env={"PATH": "/usr/bin:/bin", "HOME": ws_resolved, "TMPDIR": "/tmp"},
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
