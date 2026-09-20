"""Microsoft Execution Containers (MXC) sandbox backend — Windows, experimental.

Verified by hand against the real `@microsoft/mxc-sdk` binary (`wxc-exec.exe`)
on this machine (Windows build 26200, "base-container"/ProcessContainer
tier). Two things are true and both matter:

1. It genuinely works. A real command executed inside the container, with a
   real file written to the real host filesystem, and it required
   elevation exactly once — `wxc-host-prep.exe prepare-system-drive` grants
   the AppContainer SIDs read access to the system-drive root, persists
   across reboots, and every run after that succeeded with zero elevation.
   That is a materially better story than WSL2 for CaberOS's Windows users:
   one command instead of `wsl --install` + installing bubblewrap inside a
   distribution.

2. Microsoft's own SDK README says, verbatim: "no MXC profiles should be
   treated as security boundaries currently," and policies are known to be
   "overly permissive." That is not a footnote — it directly contradicts
   this project's own invariant that shell must never run unprotected. This
   backend is therefore never auto-selected (see base.py's opt-in gate) and
   is reported through a distinct `SandboxState.experimental`, never
   `"available"` — see SandboxBackend.trusted.

Binary distribution: `wxc-exec.exe` ships only inside the
`@microsoft/mxc-sdk` npm package, under `bin/<arch>/`. There is no
standalone installer. Until CaberOS's Windows desktop packaging bundles it
at build time, this backend only activates for a developer who has it on
PATH or points CABEROS_MXC_EXE_PATH at it directly — which is honest: it
should never silently claim to work for an end user who has neither.
"""

import asyncio
import json
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from .base import SandboxBackend, ShellResult

_PROBE_TIMEOUT = 10
_SETUP_HINT = (
    "Run `wxc-host-prep.exe prepare-system-drive` once from an elevated "
    "(Run as administrator) prompt. This is a one-time, persistent grant — "
    "verified to survive without elevation on subsequent runs — not a "
    "per-run requirement."
)


def _find_exe() -> str | None:
    override = os.environ.get("CABEROS_MXC_EXE_PATH")
    if override and Path(override).is_file():
        return override
    return shutil.which("wxc-exec")


class MxcBackend(SandboxBackend):
    """Windows ProcessContainer backend via Microsoft Execution Containers."""

    kind = "mxc"
    trusted = False

    _probe_cache: bool | None = None
    _reason: str | None = None

    def is_available(self) -> bool:
        if self._probe_cache is not None:
            return self._probe_cache

        exe = _find_exe()
        if exe is None:
            self._probe_cache = False
            self._reason = (
                "wxc-exec.exe not found. MXC ships only inside the @microsoft/mxc-sdk "
                "npm package (no standalone installer) — set CABEROS_MXC_EXE_PATH to "
                "its bin/<arch>/wxc-exec.exe, or add it to PATH."
            )
            return False

        try:
            probe = subprocess.run(
                [exe, "--probe"], capture_output=True, timeout=_PROBE_TIMEOUT, text=True
            )
            tier = json.loads(probe.stdout or "{}").get("tier") if probe.returncode == 0 else None
        except Exception:
            tier = None

        if not tier:
            self._probe_cache = False
            self._reason = "MXC's own capability probe reports no usable containment tier here."
            return False

        # --probe alone can't tell us whether the one-time host setup has
        # run — that shows up only as "Access is denied" on a real attempt.
        if self._one_time_setup_done(exe):
            self._probe_cache = True
            return True

        self._probe_cache = False
        self._reason = f"MXC is present (tier: {tier!r}) but not yet set up. {_SETUP_HINT}"
        return False

    def _one_time_setup_done(self, exe: str) -> bool:
        """Try a trivial real command — the only reliable signal available.

        `wxc-host-prep.exe` exposes no "is this machine prepared?" query, so
        this is genuinely the cheapest accurate check: run something that
        does nothing except prove the container can touch its own workspace.
        """
        with tempfile.TemporaryDirectory(prefix="caberos-mxc-probe-") as tmp:
            config_path = Path(tmp) / "probe.json"
            config_path.write_text(
                json.dumps(_build_config(tmp, "cmd.exe /c exit 0", allow_network=False))
            )
            try:
                result = subprocess.run(
                    [exe, str(config_path)], capture_output=True, timeout=_PROBE_TIMEOUT
                )
                return result.returncode == 0
            except Exception:
                return False

    def unavailable_reason(self) -> str | None:
        if self._probe_cache is None:
            self.is_available()
        return None if self._probe_cache else self._reason

    def experimental_notice(self) -> str | None:
        return (
            "MXC executes commands for real, but Microsoft's own SDK states its "
            "profiles are not yet a real security boundary. Treat this like running "
            "without a sandbox, not like bwrap/Seatbelt/Docker isolation."
        )

    async def run_command(
        self, workspace_path: str, command: str, timeout: int = 30, allow_network: bool = False
    ) -> ShellResult:
        exe = _find_exe()
        if exe is None:
            return ShellResult(
                stdout="",
                stderr="MXC backend selected but wxc-exec.exe disappeared.",
                exit_code=-1,
                duration_ms=0,
            )

        workspace = str(Path(workspace_path).resolve())

        # `prepare-system-drive` grants the AppContainer SIDs access to the
        # Windows system drive only (verified by hand: works flawlessly for a
        # workspace on C:, fails with a bare "Access is denied" for one on
        # D:). is_available()'s probe runs under %TEMP%, which is virtually
        # always on the system drive, so it cannot catch this per-call — fail
        # fast here with a real explanation instead of the opaque OS error.
        system_drive = (os.environ.get("SystemDrive") or "C:").rstrip("\\").upper()
        workspace_drive = Path(workspace).drive.upper()
        if workspace_drive and workspace_drive != system_drive:
            return ShellResult(
                stdout="",
                stderr=(
                    f"MXC (experimental) cannot access workspaces outside the system drive "
                    f"({system_drive}\\) — this workspace is on {workspace_drive}\\. "
                    "wxc-host-prep.exe prepare-system-drive only grants rights to the system "
                    "drive root, with no per-drive option. Move the workspace to the system "
                    "drive, or use a trusted backend (Docker/bwrap/Seatbelt) instead."
                ),
                exit_code=-1,
                duration_ms=0,
            )

        config = _build_config(workspace, command, allow_network)

        start = time.monotonic()
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, prefix="caberos-mxc-"
        ) as f:
            json.dump(config, f)
            config_path = f.name

        try:
            proc = await asyncio.create_subprocess_exec(
                exe,
                config_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                stdout_bytes, stderr_bytes = await asyncio.wait_for(
                    proc.communicate(), timeout=timeout
                )
                elapsed = int((time.monotonic() - start) * 1000)
                return ShellResult(
                    stdout=stdout_bytes.decode("utf-8", errors="replace"),
                    stderr=stderr_bytes.decode("utf-8", errors="replace"),
                    exit_code=proc.returncode if proc.returncode is not None else -1,
                    duration_ms=elapsed,
                )
            except TimeoutError:
                # Best-effort: unlike DockerBackend there is no separate
                # "container kill" verb exposed by this CLI — killing the
                # wxc-exec.exe process is the only lever available, and
                # whether that reliably tears down whatever it spawned
                # inside the ProcessContainer has not been verified live.
                if proc.returncode is None:
                    proc.kill()
                try:
                    await asyncio.wait_for(proc.wait(), timeout=5)
                except (TimeoutError, ProcessLookupError):
                    pass
                elapsed = int((time.monotonic() - start) * 1000)
                return ShellResult(
                    stdout="",
                    stderr=f"Command timed out after {timeout}s",
                    exit_code=-1,
                    duration_ms=elapsed,
                )
        finally:
            Path(config_path).unlink(missing_ok=True)


def _build_config(workspace: str, command: str, allow_network: bool) -> dict:
    """Build the MXC policy JSON.

    Schema confirmed by hand against the real binary's --dry-run validator —
    the SDK's published docs examples did not match the actual accepted
    fields (e.g. network.allowOutbound/timeoutMs are both rejected; the real
    fields are network.defaultPolicy: "allow"|"block" and there is no
    top-level timeout — this backend enforces its own via asyncio.wait_for).
    """
    readonly = ["C:\\Windows", "C:\\Windows\\System32"]
    return {
        "version": "0.6.0-alpha",
        "filesystem": {
            "readwritePaths": [workspace],
            "readonlyPaths": readonly,
        },
        "network": {"defaultPolicy": "allow" if allow_network else "block"},
        "process": {"commandLine": f'cmd.exe /c cd /d "{workspace}" && {command}'},
    }
