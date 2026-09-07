"""Windows sandbox backends (D28).

Windows has no userspace equivalent of Seatbelt or bubblewrap. Two backends
cover the platform:

* `WslBwrapBackend` — delegates to bubblewrap inside a WSL2 distribution. WSL2
  runs a real Linux kernel, so this is genuine isolation rather than a
  simulation, and it reuses the same bwrap profile the Linux backend uses.
* `UnavailableBackend` — used when no isolation is possible. It refuses shell
  execution with an explanation instead of raising, because "shell is disabled"
  is a supported configuration; every other capability is unaffected.

Known limitation of the WSL2 path: a sandboxed command cannot launch Windows
binaries (cmd.exe, powershell.exe, anything under /mnt/c/). WSL hands those to
the Windows host over a Unix socket, which the sandbox blocks.
"""

import asyncio
import shutil
import subprocess
import time

from .base import SandboxBackend, ShellResult
from .bwrap import build_bwrap_args, build_probe_args, run_sandboxed

# How long the availability probe may take. WSL2 can be slow to cold-start a
# stopped distribution, so this is deliberately more generous than the native
# Linux probe.
_PROBE_TIMEOUT = 30

# get_backend() builds a fresh WslBwrapBackend for every strict shell call, so
# an instance-local result would be discarded immediately and each command
# would pay for another WSL probe — up to _PROBE_TIMEOUT seconds. The cache
# lives on the module and is cleared through reset_probe_cache().
_probe_cache: bool | None = None
_probe_reason: str | None = None


def reset_probe_cache() -> None:
    """Forget the WSL probe result so the next check runs it again."""
    global _probe_cache, _probe_reason
    _probe_cache = None
    _probe_reason = None


class WslBwrapBackend(SandboxBackend):
    """Run sandboxed commands through bubblewrap inside WSL2."""

    kind = "wsl-bwrap"

    def is_available(self) -> bool:
        global _probe_cache, _probe_reason
        if _probe_cache is not None:
            return _probe_cache

        if shutil.which("wsl.exe") is None:
            _probe_cache = False
            _probe_reason = "WSL2 is not installed. Install it with: wsl --install"
            return False

        # Run the same trivial bwrap probe the Linux backend uses. This single
        # check covers every failure mode that matters: no distribution, a WSL1
        # distribution (no real kernel, so bwrap cannot unshare), bwrap not
        # installed, and bwrap installed but unable to create user namespaces.
        try:
            result = subprocess.run(
                ["wsl.exe", "-e", "bwrap", *build_probe_args(), "/bin/sh", "-c", "true"],
                capture_output=True,
                timeout=_PROBE_TIMEOUT,
            )
            _probe_cache = result.returncode == 0
            if not _probe_cache:
                _probe_reason = (
                    "WSL2 is installed but bubblewrap is not usable inside it. "
                    "Install it in your distribution with: wsl -e sudo apt install bubblewrap"
                )
        except Exception:
            _probe_cache = False
            _probe_reason = "WSL2 did not respond to the sandbox probe."
        return _probe_cache

    def unavailable_reason(self) -> str | None:
        if self.is_available():
            return None
        return _probe_reason

    async def _to_wsl_path(self, windows_path: str) -> str | None:
        """Translate a Windows path to its WSL equivalent, or None on failure."""
        try:
            proc = await asyncio.create_subprocess_exec(
                "wsl.exe",
                "-e",
                "wslpath",
                "-a",
                windows_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout_bytes, _ = await asyncio.wait_for(proc.communicate(), timeout=15)
            if proc.returncode != 0:
                return None
            translated = stdout_bytes.decode("utf-8", errors="replace").strip()
            return translated or None
        except Exception:
            return None

    async def run_command(
        self, workspace_path: str, command: str, timeout: int = 30, allow_network: bool = False
    ) -> ShellResult:
        start = time.monotonic()
        wsl_workspace = await self._to_wsl_path(workspace_path)
        if wsl_workspace is None:
            # A workspace on a network share or a disconnected drive cannot be
            # mapped into WSL. Refuse rather than hand bwrap a bad bind source.
            return ShellResult(
                stdout="",
                stderr=(
                    "Shell command refused: the workspace path could not be mapped into WSL2. "
                    "Move the workspace to a local drive to enable shell commands."
                ),
                exit_code=-1,
                duration_ms=int((time.monotonic() - start) * 1000),
            )

        args = build_bwrap_args(wsl_workspace, allow_network)
        return await run_sandboxed(["wsl.exe", "-e", "bwrap"], command, timeout, args)


class UnavailableBackend(SandboxBackend):
    """No isolation is possible — refuse shell execution, explain why.

    Deliberately not an exception. The project's platform policy is that shell
    "must be explicitly disabled" where no safe sandbox exists, and a disabled
    capability is a state the operator and the model can both read, not a crash
    in the middle of a run.
    """

    kind = "none"

    def __init__(self, reason: str | None = None) -> None:
        self._reason = reason or "No sandbox is available on this platform."

    def is_available(self) -> bool:
        return False

    def unavailable_reason(self) -> str | None:
        return self._reason

    async def run_command(
        self, workspace_path: str, command: str, timeout: int = 30, allow_network: bool = False
    ) -> ShellResult:
        return ShellResult(
            stdout="",
            stderr=(
                f"Shell commands are disabled on this machine. {self._reason} "
                "All other capabilities — files, web, memory, skills, knowledge and "
                "MCP tools — are unaffected."
            ),
            exit_code=-1,
            duration_ms=0,
        )
