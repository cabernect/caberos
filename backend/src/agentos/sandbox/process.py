"""Shared completion and abort handling for an already-launched command.

Adapters own launch configuration and resource-specific termination. This
module owns the deadline, output decoding, result shape, and abort ordering.
"""

import asyncio
import time
from collections.abc import Awaitable, Callable

from .base import ShellResult

# The existing background-terminal retention policy, shared by both paths.
OUTPUT_CAP_BYTES = 4 * 1024 * 1024


async def drain_output(
    stream: asyncio.StreamReader | None,
    write: Callable[[bytes], object] | None,
    *,
    limit: int = OUTPUT_CAP_BYTES,
    progress: Callable[[int, bool], None] | None = None,
) -> bool:
    """Retain at most the cap, but drain to EOF even after a sink failure."""
    if stream is None:
        return False
    retained = 0
    truncated = False
    while chunk := await stream.read(65536):
        keep = chunk[: max(0, limit - retained)]
        if keep and write is not None:
            try:
                write(keep)
                retained += len(keep)
            except (OSError, ValueError):
                write = None
        truncated = truncated or len(keep) < len(chunk) or write is None
        if progress is not None:
            progress(len(chunk), truncated)
    return truncated


async def collect_process(
    proc: asyncio.subprocess.Process,
    *,
    timeout: float,
    started_at: float,
    cleanup: Callable[[asyncio.subprocess.Process], Awaitable[None]],
) -> ShellResult:
    """Collect a command, requesting adapter cleanup on timeout or interruption.

    Cancellation is propagated only after cleanup has been requested. A cleanup
    request is not a claim that every descendant or native container stopped.
    """
    stdout = bytearray()
    stderr = bytearray()
    tasks = [
        asyncio.create_task(drain_output(proc.stdout, stdout.extend, limit=OUTPUT_CAP_BYTES)),
        asyncio.create_task(drain_output(proc.stderr, stderr.extend, limit=OUTPUT_CAP_BYTES)),
        asyncio.create_task(proc.wait()),
    ]
    completion = asyncio.gather(*tasks)
    try:
        # Readers stay active during abort cleanup, so a full pipe cannot
        # prevent asyncio from reaping the terminated child.
        output = await asyncio.wait_for(asyncio.shield(completion), timeout=timeout)
    except TimeoutError:
        await cleanup(proc)
        return ShellResult(
            stdout="",
            stderr=f"Command timed out after {timeout}s",
            exit_code=-1,
            duration_ms=int((time.monotonic() - started_at) * 1000),
        )
    except BaseException:
        await cleanup(proc)
        raise
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(completion, *tasks, return_exceptions=True)
    return ShellResult(
        stdout=stdout.decode("utf-8", errors="replace"),
        stderr=stderr.decode("utf-8", errors="replace"),
        exit_code=proc.returncode if proc.returncode is not None else -1,
        duration_ms=int((time.monotonic() - started_at) * 1000),
        truncated=bool(output[0] or output[1]),
    )
