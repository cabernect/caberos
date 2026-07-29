"""Shell capability implementation — shell.run.

Executes in the sandbox (D28 — sandbox-exec on macOS, bwrap on Linux).
"""

from typing import Any

from ...sandbox import get_backend


async def shell_run(
    args: dict[str, Any], workspace_path: str, timeout: int = 30, **_kwargs: Any
) -> dict[str, Any]:
    """Execute a shell command in the sandbox."""
    backend = get_backend()
    result = await backend.run_command(
        workspace_path=workspace_path,
        command=args["command"],
        timeout=timeout,
        allow_network=False,  # v0.1: network denied by default
    )
    return {
        "stdout": result.stdout,
        "stderr": result.stderr,
        "exit_code": result.exit_code,
        "duration_ms": result.duration_ms,
    }
