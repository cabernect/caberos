"""Docker sandbox backend — cross-platform fallback.

Runs the sandboxed command inside a throwaway container instead of a native
OS sandbox. Available on every platform Docker runs on, so it is the fallback
candidate everywhere: behind Seatbelt on macOS, behind bwrap on Linux, and
(until a native Windows backend exists) the primary option on Windows.

Honest limitation: Docker Desktop on Windows commonly runs its own Linux VM
via a WSL2 backend by default, so this does not mean "no WSL anywhere on the
machine" — it means the operator installs one thing (Docker Desktop) instead
of manually running `wsl --install` then `wsl -e sudo apt install bubblewrap`.
"""

import asyncio
import logging
import shutil
import subprocess
import time
import uuid
from pathlib import Path

from .base import SandboxBackend, ShellResult

log = logging.getLogger(__name__)

# Minimal, well-known image with /bin/sh — not a general-purpose dev image.
# Revisit if agents need tools this doesn't have.
_SANDBOX_IMAGE = "alpine:3.20"

# How long a killed container may take to actually stop before we give up
# waiting for it (the kill itself is not best-effort — only the wait is).
_KILL_GRACE = 5

# A first pull of _SANDBOX_IMAGE can take a while on a fresh machine. This
# runs during the probe (see _ensure_image_present), not during a real
# command, specifically so it never eats into a caller's run_command timeout.
_IMAGE_PULL_TIMEOUT = 120


class DockerBackend(SandboxBackend):
    """Run sandboxed commands inside a throwaway Docker container."""

    kind = "docker"

    _probe_cache: bool | None = None
    _reason: str | None = None

    def is_available(self) -> bool:
        if self._probe_cache is not None:
            return self._probe_cache

        if shutil.which("docker") is None:
            self._probe_cache = False
            self._reason = "Docker is not installed. Install Docker Desktop or the Docker Engine."
            return False

        try:
            result = subprocess.run(
                ["docker", "version", "--format", "{{.Server.Version}}"],
                capture_output=True,
                timeout=5,
            )
        except Exception:
            result = None

        if result is None or result.returncode != 0:
            self._probe_cache = False
            self._reason = "Docker is installed but the daemon is not responding. Is it running?"
            return False

        if self._ensure_image_present():
            self._probe_cache = True
            return True

        self._probe_cache = False
        self._reason = f"Docker sandbox image {_SANDBOX_IMAGE!r} could not be pulled."
        return False

    def _ensure_image_present(self) -> bool:
        """Pull the sandbox image now, during the probe, not the first command.

        Without this, the first sandboxed command on a fresh machine pays for
        the image pull out of its own run_command timeout — a slow pull looks
        exactly like a generic "Command timed out", with no hint that the
        sandbox infrastructure, not the command, was the bottleneck.
        """
        try:
            inspect = subprocess.run(
                ["docker", "image", "inspect", _SANDBOX_IMAGE],
                capture_output=True,
                timeout=5,
            )
            if inspect.returncode == 0:
                return True
            pull = subprocess.run(
                ["docker", "pull", _SANDBOX_IMAGE],
                capture_output=True,
                timeout=_IMAGE_PULL_TIMEOUT,
            )
            return pull.returncode == 0
        except Exception:
            return False

    def unavailable_reason(self) -> str | None:
        if self._probe_cache is None:
            self.is_available()
        return None if self._probe_cache else self._reason

    async def run_command(
        self, workspace_path: str, command: str, timeout: int = 30, allow_network: bool = False
    ) -> ShellResult:
        workspace = str(Path(workspace_path).resolve())
        container_name = f"caberos-sandbox-{uuid.uuid4().hex}"
        args = [
            "docker",
            "run",
            "--rm",
            "--name",
            container_name,
            "-v",
            f"{workspace}:/workspace",
            "-w",
            "/workspace",
            # Matches BwrapBackend/SeatbeltBackend: HOME is the workspace, not
            # whatever the image's default user has (root's /root on Alpine).
            "-e",
            "HOME=/workspace",
        ]
        if not allow_network:
            args += ["--network", "none"]
        args += [_SANDBOX_IMAGE, "/bin/sh", "-c", command]

        start = time.monotonic()
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
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
            await self._kill_container(container_name, proc)
            elapsed = int((time.monotonic() - start) * 1000)
            return ShellResult(
                stdout="",
                stderr=f"Command timed out after {timeout}s",
                exit_code=-1,
                duration_ms=elapsed,
            )

    async def _kill_container(self, container_name: str, proc: asyncio.subprocess.Process) -> None:
        """Stop the container itself, not just the local `docker run` client.

        `docker run` in the foreground is a client process talking to the
        Docker daemon; killing it does not stop the container the daemon is
        running. Without this, a timed-out command keeps running inside the
        container — consuming resources — after CaberOS reports it stopped.
        """
        try:
            kill = await asyncio.create_subprocess_exec(
                "docker",
                "kill",
                container_name,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            returncode = await asyncio.wait_for(kill.wait(), timeout=_KILL_GRACE)
            if returncode != 0:
                log.warning(
                    "docker kill %s exited %s (container may already be gone)",
                    container_name,
                    returncode,
                )
        except Exception:
            log.warning(
                "docker kill %s failed — container may have leaked", container_name, exc_info=True
            )

        if proc.returncode is None:
            proc.kill()
        try:
            await asyncio.wait_for(proc.wait(), timeout=_KILL_GRACE)
        except (TimeoutError, ProcessLookupError):
            pass
