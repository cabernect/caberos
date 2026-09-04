"""Shell capability implementation — shell_run.

Executes in the sandbox (D28 — sandbox-exec on macOS, bwrap on Linux).
In open sandbox mode, runs directly without the sandbox wrapper.
"""

import asyncio
import sys
import time
from typing import Any

from ...sandbox import get_backend


def _open_mode_shell(command: str) -> list[str]:
    """Argv for running a command unsandboxed, per platform.

    Open mode deliberately bypasses the sandbox, so the only platform concern
    here is which shell actually exists: Windows has no /bin/sh.
    """
    if sys.platform == "win32":
        return ["cmd.exe", "/c", command]
    return ["/bin/sh", "-c", command]


async def shell_run(
    args: dict[str, Any], workspace_path: str, timeout: int = 30, **kwargs: Any
) -> dict[str, Any]:
    """Execute a shell command. Sandboxed in strict mode, direct in open mode."""
    sandbox_mode = kwargs.get("sandbox_mode", "strict")

    if sandbox_mode == "open":
        # Run directly without sandbox wrapper — agent has full system access
        start = time.monotonic()
        try:
            proc = await asyncio.create_subprocess_exec(
                *_open_mode_shell(args["command"]),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=workspace_path,
            )
            stdout_bytes, stderr_bytes = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            elapsed = int((time.monotonic() - start) * 1000)
            return {
                "stdout": stdout_bytes.decode("utf-8", errors="replace"),
                "stderr": stderr_bytes.decode("utf-8", errors="replace"),
                "exit_code": proc.returncode if proc.returncode is not None else -1,
                "duration_ms": elapsed,
            }
        except TimeoutError:
            elapsed = int((time.monotonic() - start) * 1000)
            return {
                "stdout": "",
                "stderr": f"Command timed out after {timeout}s",
                "exit_code": -1,
                "duration_ms": elapsed,
            }

    # Strict mode — use sandbox backend
    backend = get_backend()
    result = await backend.run_command(
        workspace_path=workspace_path,
        command=args["command"],
        timeout=timeout,
        allow_network=False,
    )
    return {
        "stdout": result.stdout,
        "stderr": result.stderr,
        "exit_code": result.exit_code,
        "duration_ms": result.duration_ms,
    }
