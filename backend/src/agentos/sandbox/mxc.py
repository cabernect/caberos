"""Microsoft Execution Containers (MXC) sandbox backend — Windows, experimental.

Verified by hand against the real `@microsoft/mxc-sdk` binary (`wxc-exec.exe`)
on Windows build 26200 ("base-container"/ProcessContainer tier). Three things
are true and all matter:

1. It genuinely works, with no Docker and no WSL. A real command executes
   inside the container and a real file lands on the real host filesystem.
   It needs elevation exactly once — `wxc-host-prep.exe prepare-system-drive`
   grants the AppContainer SIDs access to the system-drive root, persists
   across reboots, and every run after that needs zero elevation.

2. Microsoft's own SDK README says, verbatim: "no MXC profiles should be
   treated as security boundaries currently," and policies are known to be
   "overly permissive." So this backend is reported through a distinct
   `"experimental"` state — never `"available"` — see SandboxBackend.trusted.
   Because Windows has no trusted native sandbox, it is still auto-selected
   there: the alternative is no shell at all, and the desktop app must not
   require Docker Desktop or WSL.

3. The policy must enable the UI subsystem (`ui.disable: false`). With the
   SDK default, ordinary console programs (`whoami.exe`, PowerShell) die with
   STATUS_DLL_INIT_FAILED because they initialise win32k. Clipboard and input
   injection stay blocked.

Binary distribution: `wxc-exec.exe` and `wxc-host-prep.exe` ship inside the
CaberOS Windows installer (`resources/mxc`, hash-pinned at build time) and
the desktop shell passes the path in CABEROS_MXC_EXE_PATH. A source checkout
can set that variable itself or put `wxc-exec` on PATH.
"""

import asyncio
import contextlib
import json
import ntpath
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from .base import SandboxBackend, ShellResult, kill_process_group

_PROBE_TIMEOUT = 10


_POLICY_PREFIX = "caberos-mxc-"
_POLICY_MAX_AGE_SECONDS = 3600


def _sweep_stale_policies() -> None:
    """Delete policy files left by spawned terminals that outlived their call.

    spawn_argv hands the file to a process whose lifetime the terminal registry
    owns, so nothing can delete it right after launch. A policy holds only the
    workspace path and an allowlisted environment, no secrets, so an hour of
    lag before cleanup is harmless.
    """
    cutoff = time.time() - _POLICY_MAX_AGE_SECONDS
    for stale in Path(tempfile.gettempdir()).glob(f"{_POLICY_PREFIX}*.json"):
        with contextlib.suppress(OSError):
            if stale.stat().st_mtime < cutoff:
                stale.unlink()


def _find_exe() -> str | None:
    override = os.environ.get("CABEROS_MXC_EXE_PATH")
    if override and Path(override).is_file():
        return override
    return shutil.which("wxc-exec")


def _setup_hint(exe: str) -> str:
    prep = Path(exe).with_name("wxc-host-prep.exe")
    return (
        "One-time setup needed: use 'Enable shell sandbox' in the CaberOS dashboard, "
        f'or run `"{prep}" prepare-system-drive` from an elevated (Run as administrator) '
        "prompt. It is a single persistent grant, not a per-run requirement."
    )


def _ui_policy() -> dict:
    # Console programs initialise win32k, so UI must be enabled for them to start;
    # clipboard and input injection stay shut so a command cannot touch either.
    return {"disable": False, "clipboard": "none", "injection": False}


# With no `process.env`, MXC builds the container's environment from the user's
# persistent environment (found live: a real API key set with `setx` was visible
# inside the container). So the environment is an explicit allowlist instead, and
# `process.env` replaces the default entirely.
_ENV_ALLOWLIST = (
    "SystemRoot",
    "SystemDrive",
    "windir",
    "ComSpec",
    "PATHEXT",
    "OS",
    "PROCESSOR_ARCHITECTURE",
    "NUMBER_OF_PROCESSORS",
    "ProgramFiles",
    "ProgramFiles(x86)",
    "ProgramW6432",
    "CommonProgramFiles",
    "CommonProgramFiles(x86)",
    "CommonProgramW6432",
    "ProgramData",
    "ALLUSERSPROFILE",
    "PUBLIC",
)

# PATH entries under these roots are readable from inside the container; entries
# elsewhere (the user profile above all) are not, so they are dropped.
_READABLE_ROOT_VARS = (
    "SystemRoot",
    "ProgramFiles",
    "ProgramFiles(x86)",
    "ProgramW6432",
    "ProgramData",
)


# Everything below builds Windows paths for a Windows container, so it uses `ntpath`
# and ";" explicitly rather than the host's `os.path`/`os.pathsep`. That keeps the
# result identical on any OS (CI runs these tests on Linux).
_WINDOWS_PATH_SEP = ";"


def _norm(path: str) -> str:
    return ntpath.normcase(ntpath.normpath(path))


def _is_under(path: str, roots: list[str]) -> bool:
    normalized = _norm(path)
    return any(normalized == root or normalized.startswith(root + "\\") for root in roots)


def _sandbox_path(system_root: str) -> str:
    # Windows' own directories come first so `whoami`, `curl`, `find` and friends
    # resolve to the real tools: a host PATH that leads with Git's MSYS `usr\bin`
    # would otherwise pick MSYS builds, which cannot initialise inside the container.
    ordered = [
        ntpath.join(system_root, "System32"),
        ntpath.join(system_root, "System32", "Wbem"),
        ntpath.join(system_root, "System32", "WindowsPowerShell", "v1.0"),
        system_root,
    ]
    roots = [
        _norm(value)
        for name in _READABLE_ROOT_VARS
        if (value := os.environ.get(name) or (system_root if name == "SystemRoot" else None))
    ]
    for entry in (os.environ.get("PATH") or "").split(_WINDOWS_PATH_SEP):
        if entry and _is_under(entry, roots):
            ordered.append(entry)

    unique: list[str] = []
    seen: set[str] = set()
    for entry in ordered:
        key = _norm(entry)
        if key not in seen:
            seen.add(key)
            unique.append(entry)
    return _WINDOWS_PATH_SEP.join(unique)


def _sandbox_env(workspace: str) -> list[str]:
    """Container environment: allowlisted system variables, HOME set to the workspace."""
    env: dict[str, str] = {}
    for name in _ENV_ALLOWLIST:
        value = os.environ.get(name)
        if value:
            env[name] = value
    system_root = env.setdefault("SystemRoot", "C:\\Windows")
    env["PATH"] = _sandbox_path(system_root)

    # Same contract as Seatbelt/bwrap: HOME is the workspace, never the real profile.
    # Tools that keep config (npm, pip, ...) then write somewhere they can.
    env["HOME"] = workspace
    env["USERPROFILE"] = workspace
    env["APPDATA"] = ntpath.join(workspace, "AppData", "Roaming")
    # MXC requires LOCALAPPDATA to be present and derives the container's private
    # TEMP from it (always overriding TEMP/TMP). It is only a string here — the real
    # directory stays unreadable from inside — so the genuine value is passed.
    env["LOCALAPPDATA"] = os.environ.get("LOCALAPPDATA") or ntpath.join(
        workspace, "AppData", "Local"
    )
    return [f"{name}={value}" for name, value in env.items()]


class MxcBackend(SandboxBackend):
    """Windows ProcessContainer backend via Microsoft Execution Containers."""

    kind = "mxc"
    trusted = False

    _probe_cache: bool | None = None
    _reason: str | None = None
    _needs_setup: bool = False

    def is_available(self) -> bool:
        if self._probe_cache is not None:
            return self._probe_cache

        exe = _find_exe()
        if exe is None:
            self._probe_cache = False
            self._reason = (
                "wxc-exec.exe was not found. It ships inside the CaberOS Windows "
                "installer; from a source checkout, set CABEROS_MXC_EXE_PATH to the "
                "@microsoft/mxc-sdk bin/x64/wxc-exec.exe, or add it to PATH."
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
        self._needs_setup = True
        self._reason = f"MXC is present (tier: {tier!r}) but not yet set up. {_setup_hint(exe)}"
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

    def needs_host_setup(self) -> bool:
        if self._probe_cache is None:
            self.is_available()
        return self._needs_setup

    def experimental_notice(self) -> str | None:
        return (
            "Commands run in a Windows container that limits file access to the agent "
            "workspace and blocks the network unless allowed. Microsoft does not yet "
            "call MXC a security boundary, so it is weaker than bwrap or Seatbelt on "
            "other platforms."
        )

    def _refusal(self, workspace_path: str, workspace: str) -> str | None:
        """Why this workspace cannot be sandboxed, or None when it can."""
        # `prepare-system-drive` grants the AppContainer SIDs access to the
        # Windows system drive only (verified by hand: works flawlessly for a
        # workspace on C:, fails with a bare "Access is denied" for one on
        # D:). is_available()'s probe runs under %TEMP%, which is virtually
        # always on the system drive, so it cannot catch this per-call - fail
        # fast with a real explanation instead of the opaque OS error.
        system_drive = (os.environ.get("SystemDrive") or "C:").rstrip("\\").upper()
        workspace_drive = (
            ntpath.splitdrive(workspace_path)[0] or ntpath.splitdrive(workspace)[0]
        ).upper()
        if workspace_drive and workspace_drive != system_drive:
            return (
                f"MXC (experimental) cannot access workspaces outside the system drive "
                f"({system_drive}\\) - this workspace is on {workspace_drive}\\. "
                "wxc-host-prep.exe prepare-system-drive only grants rights to the system "
                "drive root, with no per-drive option. Keep agent workspaces on the "
                "system drive (the desktop app's default data directory already is)."
            )
        return None

    def spawn_argv(
        self, workspace_path: str, command: str, allow_network: bool = False
    ) -> list[str]:
        """Argv for `wxc-exec.exe <policy.json>`; the policy file is swept on later calls.

        Raises RuntimeError rather than returning an argv when the command cannot be
        sandboxed, so a terminal never starts unconfined.
        """
        exe = _find_exe()
        if exe is None:
            raise RuntimeError("MXC backend selected but wxc-exec.exe disappeared.")
        workspace = str(Path(workspace_path).resolve())
        refusal = self._refusal(workspace_path, workspace)
        if refusal:
            raise RuntimeError(refusal)
        _sweep_stale_policies()
        config = _build_config(workspace, command, allow_network)
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, prefix=_POLICY_PREFIX
        ) as f:
            json.dump(config, f)
        return [exe, f.name]

    async def run_command(
        self, workspace_path: str, command: str, timeout: int = 30, allow_network: bool = False
    ) -> ShellResult:
        start = time.monotonic()
        try:
            argv = self.spawn_argv(workspace_path, command, allow_network)
        except RuntimeError as exc:
            return ShellResult(stdout="", stderr=str(exc), exit_code=-1, duration_ms=0)

        try:
            proc = await asyncio.create_subprocess_exec(
                *argv,
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
                # "container kill" verb exposed by this CLI - killing the
                # wxc-exec.exe tree is the only lever available, and
                # whether that reliably tears down whatever it spawned
                # inside the ProcessContainer has not been verified live.
                await kill_process_group(proc, grace=5)
                elapsed = int((time.monotonic() - start) * 1000)
                return ShellResult(
                    stdout="",
                    stderr=f"Command timed out after {timeout}s",
                    exit_code=-1,
                    duration_ms=elapsed,
                )
        finally:
            Path(argv[1]).unlink(missing_ok=True)


def _build_config(workspace: str, command: str, allow_network: bool) -> dict:
    """Build the MXC policy JSON.

    Schema confirmed by hand against the real binary's --dry-run validator —
    the SDK's published docs examples did not match the actual accepted
    fields (e.g. network.allowOutbound/timeoutMs are both rejected; the real
    fields are network.defaultPolicy: "allow"|"block" and there is no
    top-level timeout — this backend enforces its own via asyncio.wait_for).
    """
    system_root = os.environ.get("SystemRoot") or "C:\\Windows"
    return {
        "version": "0.6.0-alpha",
        "filesystem": {
            "readwritePaths": [workspace],
            "readonlyPaths": [system_root, ntpath.join(system_root, "System32")],
        },
        "network": {"defaultPolicy": "allow" if allow_network else "block"},
        "ui": _ui_policy(),
        "process": {
            "commandLine": f'cmd.exe /c cd /d "{workspace}" && {command}',
            "env": _sandbox_env(workspace),
        },
    }
