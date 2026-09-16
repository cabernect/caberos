"""Terminal capability executors — terminal / read_terminal / close_terminal.

Sync mode runs the command to completion (sandboxed in strict mode via the
sandbox backend, direct in open mode). Async mode goes through the
process-wide TerminalRegistry, which owns the spawned process group and
spools output to bounded files.
"""

import asyncio
import time
from typing import Any

from ...sandbox import get_backend
from ...sandbox.base import kill_process_group


async def terminal_run(
    args: dict[str, Any], workspace_path: str, timeout: int = 30, **kwargs: Any
) -> dict[str, Any]:
    """terminal(command, async?) — sync returns output; async returns a terminal_id."""
    if args.get("async"):
        registry = kwargs["terminal_registry"]
        return await registry.start(
            kwargs["db"],
            command=args["command"],
            workspace_path=workspace_path,
            sandbox_mode=kwargs.get("sandbox_mode", "strict"),
            agent_id=kwargs["agent_id"],
            session_id=kwargs.get("session_id"),
            run_id=kwargs["run_id"],
            db_lock=kwargs.get("db_lock"),
        )
    return await _run_sync(
        args["command"], workspace_path, kwargs.get("sandbox_mode", "strict"), timeout
    )


async def read_terminal(args: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
    """read_terminal(terminal_id, offset?, max_chars?, wait_ms?) — incremental output."""
    registry = kwargs["terminal_registry"]
    return await registry.read(
        args["terminal_id"],
        agent_id=kwargs["agent_id"],
        session_id=kwargs.get("session_id"),
        run_id=kwargs["run_id"],
        offset=int(args.get("offset") or 0),
        max_chars=min(int(args.get("max_chars") or 8192), 65536),
        wait_ms=min(int(args.get("wait_ms") or 0), 30_000),
    )


async def close_terminal(args: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
    """close_terminal(terminal_id) — terminate the group, return unread output."""
    registry = kwargs["terminal_registry"]
    return await registry.close(
        args["terminal_id"],
        agent_id=kwargs["agent_id"],
        session_id=kwargs.get("session_id"),
        run_id=kwargs["run_id"],
    )


async def _run_sync(
    command: str, workspace_path: str, sandbox_mode: str, timeout: int
) -> dict[str, Any]:
    """Run a command to completion — the terminal capability's sync path."""
    if sandbox_mode == "open":
        start = time.monotonic()
        proc = await asyncio.create_subprocess_exec(
            "/bin/sh",
            "-c",
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=workspace_path,
            start_new_session=True,
        )
        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            elapsed = int((time.monotonic() - start) * 1000)
            return {
                "stdout": stdout_bytes.decode("utf-8", errors="replace"),
                "stderr": stderr_bytes.decode("utf-8", errors="replace"),
                "exit_code": proc.returncode if proc.returncode is not None else -1,
                "duration_ms": elapsed,
            }
        except TimeoutError:
            await kill_process_group(proc)
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
        command=command,
        timeout=timeout,
        allow_network=False,
    )
    return {
        "stdout": result.stdout,
        "stderr": result.stderr,
        "exit_code": result.exit_code,
        "duration_ms": result.duration_ms,
    }
