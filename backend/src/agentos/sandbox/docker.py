"""Docker sandbox backend — macOS/Linux fallback.

Runs the sandboxed command inside a throwaway container instead of a native
OS sandbox. It is the fallback candidate behind Seatbelt on macOS and bwrap on
Linux. It is deliberately not a Windows candidate: the Windows desktop app must
not require Docker Desktop (which runs its own WSL2 VM) for shell to work —
Windows uses MXC instead, see mxc.py and base._candidates_for().
"""

import asyncio
import logging
import os
import re
import shutil
import subprocess
import time
import uuid
from pathlib import Path

from .base import SandboxBackend, SandboxLaunch, ShellResult, kill_process_group

log = logging.getLogger(__name__)

# Minimal, well-known image with /bin/sh — not a general-purpose dev image.
# Revisit if agents need tools this doesn't have.
_SANDBOX_IMAGE = "alpine:3.20"

# How long a killed container may take to actually stop before we give up
# waiting for it (the kill itself is not best-effort — only the wait is).
_KILL_GRACE = 5


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

        if self._image_present():
            self._probe_cache = True
            return True

        self._probe_cache = False
        self._reason = (
            f"Docker sandbox image {_SANDBOX_IMAGE!r} is missing or cannot be inspected. "
            f"After reviewing the image and download, run: docker pull {_SANDBOX_IMAGE}. "
            "CaberOS does not download sandbox images automatically."
        )
        return False

    def _image_present(self) -> bool:
        """Inspect the local image only; readiness never authorizes a download."""
        try:
            inspect = subprocess.run(
                ["docker", "image", "inspect", _SANDBOX_IMAGE],
                capture_output=True,
                timeout=5,
            )
            return inspect.returncode == 0
        except Exception:
            return False

    def unavailable_reason(self) -> str | None:
        if self._probe_cache is None:
            self.is_available()
        return None if self._probe_cache else self._reason

    def _docker_argv(
        self, workspace_path: str, command: str, allow_network: bool, container_name: str
    ) -> list[str]:
        workspace = str(Path(workspace_path).resolve())
        uid = getattr(os, "getuid", lambda: 65534)() or 65534
        gid = getattr(os, "getgid", lambda: 65534)() or 65534
        args = [
            "docker",
            "run",
            # Also close the race where the image disappears after probing.
            "--pull=never",
            "--rm",
            "--name",
            container_name,
            "--label",
            f"io.caberos.sandbox={container_name}",
            "--user",
            f"{uid}:{gid}",
            "--cap-drop=ALL",
            "--security-opt=no-new-privileges",
            "--read-only",
            "--pids-limit=64",
            "--memory=256m",
            "--memory-swap=256m",
            "--cpus=1",
            "--ulimit",
            "nofile=256:256",
            "--ulimit",
            "fsize=67108864:67108864",
            "--tmpfs",
            "/tmp:rw,nosuid,nodev,noexec,size=32m,mode=1777",
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
        return args

    def spawn_argv(
        self, workspace_path: str, command: str, allow_network: bool = False
    ) -> list[str]:
        """Legacy argv interface; managed backgrounds use plan/activate/cleanup."""
        return self._docker_argv(
            workspace_path, command, allow_network, f"caberos-sandbox-{uuid.uuid4().hex}"
        )

    async def _control(self, *argv: str) -> bytes:
        """Bounded controller command; errors never expose daemon response bodies."""
        proc = await asyncio.create_subprocess_exec(
            "docker",
            *argv,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        try:
            async with asyncio.timeout(_KILL_GRACE):
                if proc.stdout is None:
                    raise RuntimeError("Docker resource output is unavailable.")
                output = await proc.stdout.read(4097)
                if len(output) > 4096 or await proc.wait() != 0:
                    raise RuntimeError("Docker resource operation failed.")
                return output.strip()
        finally:
            if proc.returncode is None:
                proc.kill()
                await asyncio.wait_for(proc.wait(), timeout=_KILL_GRACE)

    def plan_launch(self, workspace_path: str, command: str) -> SandboxLaunch:
        # Create first: stopping an attach client must not race a late container
        # creation. Once acknowledged, removing this resource also stops a late start.
        name = f"caberos-sandbox-{uuid.uuid4().hex}"
        args = self._docker_argv(workspace_path, command, False, name)
        args[1] = "create"
        args.remove("--rm")
        return SandboxLaunch(
            argv=["docker", "start", "--attach", name],
            env=None,
            resource_id=name,
            setup_argv=args[1:],
        )

    async def activate_launch(self, launch: SandboxLaunch) -> None:
        try:
            if launch.setup_argv is None:
                raise RuntimeError("Docker resource plan is missing.")
            resource = await self._control(*launch.setup_argv)
            if re.fullmatch(rb"[0-9a-f]{64}", resource) is None:
                raise RuntimeError("Docker did not confirm resource creation.")
        except BaseException:
            # The request may have reached the daemon before a disconnect.
            await self.cleanup_launch(launch, None)
            raise

    async def cleanup_launch(
        self, launch: SandboxLaunch, proc: asyncio.subprocess.Process | None
    ) -> bool:
        if proc is not None:
            await kill_process_group(proc)
        name = launch.resource_id or ""
        if re.fullmatch(r"caberos-sandbox-[0-9a-f]{32}", name) is None:
            return False
        try:
            try:
                owner = await self._control(
                    "inspect",
                    "--format",
                    '{{ index .Config.Labels "io.caberos.sandbox" }}',
                    name,
                )
            except (OSError, RuntimeError, TimeoutError):
                # A failed inspect alone is not evidence that a resource is gone.
                remaining = await self._control(
                    "ps", "--all", "--filter", f"name=^/{name}$", "--format", "{{.ID}}"
                )
                return remaining == b""
            if owner != name.encode("ascii"):
                return False
            await self._control("rm", "--force", name)
            return True
        except (OSError, RuntimeError, TimeoutError):
            log.warning("Docker launch cleanup could not be confirmed.")
            return False

    async def run_command(
        self, workspace_path: str, command: str, timeout: int = 30, allow_network: bool = False
    ) -> ShellResult:
        container_name = f"caberos-sandbox-{uuid.uuid4().hex}"
        args = self._docker_argv(workspace_path, command, allow_network, container_name)

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
