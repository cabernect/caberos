"""Sandbox backend abstraction (D28 — process-level sandboxing).

get_backend() never raises. Each platform uses its OS-native backend. If that
backend is unavailable, the terminal capability is refused with a reason;
Docker is reserved for future explicit opt-in setup, never automatic fallback.
"""

import asyncio
import contextlib
import os
import signal
import sys
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

# "unavailable" means shell is refused but the rest of the product works.
# "experimental" means the backend genuinely executed the command — this is
# not a fallback-with-a-caveat state — but its own vendor has not yet
# published it as a real security boundary (see MxcBackend.trusted). It is
# reported distinctly from "available" so CaberOS never silently claims
# isolation strength it cannot back up.
SandboxState = Literal["available", "experimental", "unavailable"]


@dataclass
class ShellResult:
    stdout: str
    stderr: str
    exit_code: int
    duration_ms: int
    truncated: bool = False


@dataclass
class SandboxLaunch:
    """Controller-owned launch identity; never reconstructed from model arguments."""

    argv: list[str]
    env: dict[str, str] | None
    resource_id: str | None = None
    setup_argv: list[str] | None = None


@dataclass
class SandboxProbe:
    """What the operator needs to know about shell isolation on this machine."""

    kind: str
    state: SandboxState
    reason: str | None = None
    # True when the only thing missing is a one-time, operator-approved host
    # setup (e.g. MXC's elevated system-drive grant) that the desktop app can
    # offer to run — as opposed to something the operator must install.
    setup_required: bool = False


async def kill_process_group(proc: asyncio.subprocess.Process, grace: float = 3.0) -> None:
    """Terminate the process's whole tree (SIGTERM then SIGKILL; `taskkill /T /F` on Windows).

    On POSIX the process must have been spawned with start_new_session=True so
    its group contains the whole tree. Windows has no process groups in that
    sense, so the tree is walked and killed instead. Safe on an already-exited
    process.
    """
    if proc.returncode is not None:
        return
    if sys.platform == "win32":
        with contextlib.suppress(Exception):
            killer = await asyncio.create_subprocess_exec(
                "taskkill",
                "/T",
                "/F",
                "/PID",
                str(proc.pid),
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            try:
                await asyncio.wait_for(killer.wait(), timeout=grace)
            except TimeoutError:
                killer.kill()
                await asyncio.wait_for(killer.wait(), timeout=grace)
        with contextlib.suppress(ProcessLookupError):
            proc.kill()
        with contextlib.suppress(Exception):
            await asyncio.wait_for(proc.wait(), timeout=grace)
        return
    try:
        pgid = os.getpgid(proc.pid)
    except (ProcessLookupError, PermissionError):
        pgid = None
    if pgid is not None and (pgid <= 1 or pgid != proc.pid):
        # Only a child launched in its own session owns its group. Never
        # signal the gateway's or another inherited process group.
        pgid = None

    def _kill(sig: int) -> None:
        try:
            if pgid is not None:
                os.killpg(pgid, sig)
            else:
                proc.send_signal(sig)
        except (ProcessLookupError, PermissionError):
            pass

    _kill(signal.SIGTERM)
    try:
        await asyncio.wait_for(proc.wait(), timeout=grace)
        return
    except TimeoutError:
        pass
    _kill(signal.SIGKILL)
    with contextlib.suppress(Exception):
        await asyncio.wait_for(proc.wait(), timeout=grace)


class SandboxBackend(ABC):
    """Abstract sandbox backend.

    Default implementations: Seatbelt (macOS), bwrap (Linux), MXC (Windows,
    experimental), and Unavailable. The Docker prototype is not auto-selected.
    """

    # Short identifier surfaced through the health endpoint.
    kind: str = "unknown"

    # False means: this backend genuinely runs commands, but its own vendor
    # has not published it as a real security boundary yet. A working
    # backend is not automatically a trusted one — see MxcBackend.
    trusted: bool = True

    @abstractmethod
    async def run_command(
        self, workspace_path: str, command: str, timeout: int = 30, allow_network: bool = False
    ) -> ShellResult:
        """Run a shell command in the sandbox with the workspace mounted."""

    @abstractmethod
    def spawn_argv(
        self, workspace_path: str, command: str, allow_network: bool = False
    ) -> list[str]:
        """Argv to launch `command` under this sandbox.

        Used by the terminal registry to spawn long-running processes whose
        lifecycle it manages itself (process group, spooled output, kill).
        """

    def spawn_env(self, workspace_path: str) -> dict[str, str] | None:
        """Env for a spawned sandbox process; None = inherit parent env."""
        return None

    def plan_launch(self, workspace_path: str, command: str) -> SandboxLaunch:
        """Choose an owned identity without creating processes or external resources."""
        return SandboxLaunch(
            argv=self.spawn_argv(workspace_path, command),
            env=self.spawn_env(workspace_path),
        )

    async def activate_launch(self, launch: SandboxLaunch) -> None:
        """Create a resource only after the controller has persisted its identity."""

    async def prepare_launch(self, workspace_path: str, command: str) -> SandboxLaunch:
        """Convenience for callers that do not need durable admission."""
        launch = self.plan_launch(workspace_path, command)
        await self.activate_launch(launch)
        return launch

    async def cleanup_launch(
        self, launch: SandboxLaunch, proc: asyncio.subprocess.Process | None
    ) -> bool:
        """Stop an owned launch; False means termination could not be confirmed."""
        if proc is None:
            return True
        await kill_process_group(proc)
        return proc.returncode is not None

    @abstractmethod
    def is_available(self) -> bool:
        """Check if this backend's tool is installed and usable."""

    def unavailable_reason(self) -> str | None:
        """Why this backend cannot isolate, when it cannot. None when it can."""
        return None

    def experimental_notice(self) -> str | None:
        """Caveat to surface for a working but untrusted (trusted=False) backend."""
        return None

    def needs_host_setup(self) -> bool:
        """True when this backend is installed but waiting on a one-time host setup."""
        return False


class UnavailableBackend(SandboxBackend):
    """No isolation is possible — refuse shell execution, explain why.

    Deliberately not an exception. Shell being disabled is a supported
    configuration the operator and the model can both read, not a crash in
    the middle of a run.
    """

    kind = "none"

    def __init__(self, reason: str | None = None, setup_required: bool = False) -> None:
        self._reason = reason or "No sandbox is available on this platform."
        self._setup_required = setup_required

    def is_available(self) -> bool:
        return False

    def unavailable_reason(self) -> str | None:
        return self._reason

    def needs_host_setup(self) -> bool:
        return self._setup_required

    def spawn_argv(
        self, workspace_path: str, command: str, allow_network: bool = False
    ) -> list[str]:
        raise RuntimeError(f"Shell commands are disabled on this machine. {self._reason}")

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


# Explicit terminal-backend picks the operator can make in Settings → Tools →
# Terminal ("auto" resolves through get_backend instead). Each value names the
# OS the backend is native to — a foreign pick refuses rather than falling
# back. Remote transports (SSH/Daytona/Modal) join this map with their drivers.
LOCAL_BACKEND_OSES: dict[str, str] = {
    "seatbelt": "macOS",
    "bwrap": "Linux",
    "mxc": "Windows",
}


def _local_makers() -> dict[str, Callable[[], SandboxBackend]]:
    """Local backends constructible on this platform, keyed by pick name."""
    if sys.platform == "win32":
        from .mxc import MxcBackend

        return {"mxc": MxcBackend}
    if sys.platform == "darwin":
        from .seatbelt import SeatbeltBackend

        return {"seatbelt": SeatbeltBackend}
    if sys.platform.startswith("linux"):
        from .bwrap import BwrapBackend

        return {"bwrap": BwrapBackend}
    return {}


def backend_named(name: str) -> SandboxBackend:
    """Instantiate an explicitly selected local backend — never falls back.

    An unknown name, a backend foreign to this OS, or a missing tool returns
    an UnavailableBackend so the refusal reads exactly like an unavailable
    auto backend instead of crashing differently.
    """
    if name not in LOCAL_BACKEND_OSES:
        return UnavailableBackend(reason=f"Unknown terminal backend {name!r}.")
    make = _local_makers().get(name)
    if make is None:
        return UnavailableBackend(
            reason=f"The {name} backend is native to {LOCAL_BACKEND_OSES[name]} — "
            f"this machine runs {sys.platform}."
        )
    backend = make()
    if backend.is_available():
        return backend
    return UnavailableBackend(
        reason=f"{name}: {backend.unavailable_reason() or 'not available'}",
        setup_required=backend.needs_host_setup(),
    )


@dataclass
class BackendStatus:
    """One row of the Terminal card's per-backend readiness table."""

    name: str
    os_requirement: str
    supported_here: bool
    available: bool
    experimental: bool
    auto: bool  # what Auto resolves to on this machine
    reason: str | None = None


def backend_catalog() -> list[BackendStatus]:
    """Readiness for every local backend pick — OS support, availability,
    isolation strength (experimental), and what Auto resolves to.

    Probing instantiates each backend and may spawn a subprocess; callers run
    it off the event loop (asyncio.to_thread) and only on operator-facing
    reads, never on mediation.
    """
    auto_kind = get_backend().kind
    makers = _local_makers()
    rows: list[BackendStatus] = []
    for name, requirement in LOCAL_BACKEND_OSES.items():
        make = makers.get(name)
        if make is None:
            rows.append(
                BackendStatus(
                    name=name,
                    os_requirement=requirement,
                    supported_here=False,
                    available=False,
                    experimental=False,
                    auto=False,
                    reason=f"requires {requirement}",
                )
            )
            continue
        backend = make()
        available = backend.is_available()
        rows.append(
            BackendStatus(
                name=name,
                os_requirement=requirement,
                supported_here=True,
                available=available,
                experimental=available and not backend.trusted,
                auto=auto_kind == backend.kind,
                reason=None if available else backend.unavailable_reason(),
            )
        )
    return rows


def _candidates_for(platform: str) -> list[Callable[[], SandboxBackend]]:
    """Only the OS-native backend; Docker setup is future, explicit opt-in."""
    if platform == "win32":
        # Windows has no trusted native sandbox, and the desktop app must not
        # ask a user to install Docker Desktop or WSL for shell to work. MXC
        # ships inside the installer; it is reported as "experimental" (never
        # "available") because Microsoft does not yet call it a security boundary.
        from .mxc import MxcBackend

        return [MxcBackend]

    candidates: list[Callable[[], SandboxBackend]] = []
    if platform == "darwin":
        from .seatbelt import SeatbeltBackend

        candidates.append(SeatbeltBackend)
    elif platform.startswith("linux"):
        from .bwrap import BwrapBackend

        candidates.append(BwrapBackend)
    return candidates


# Keyed by sys.platform rather than a single slot: a real machine's platform
# never changes at runtime, so this caches exactly one entry in production,
# but tests that monkeypatch sys.platform across calls still get a correct,
# independent resolution per platform value instead of a stale one.
_backend_cache: dict[str, SandboxBackend] = {}


def get_backend(refresh: bool = False) -> SandboxBackend:
    """Return the OS-native backend for the current platform.

    Never raises. If the native backend is unavailable, returns an
    UnavailableBackend naming the reason. Docker is never probed or selected
    automatically, even if its daemon and sandbox image are already available.

    Cached: every strict-mode shell call goes through this function, and
    constructing a fresh backend each time re-runs its availability probe
    every time too — some probes spawn a subprocess. Pass refresh=True to
    force a new probe (e.g. after the operator installs a missing dependency).
    """
    platform = sys.platform
    if not refresh and platform in _backend_cache:
        return _backend_cache[platform]

    tried_reasons: list[str] = []
    setup_required = False
    backend: SandboxBackend | None = None
    for make_backend in _candidates_for(platform):
        candidate = make_backend()
        if candidate.is_available():
            backend = candidate
            break
        reason = candidate.unavailable_reason()
        if reason:
            tried_reasons.append(f"{candidate.kind}: {reason}")
        setup_required = setup_required or candidate.needs_host_setup()

    if backend is None:
        if tried_reasons:
            reason = "No sandbox available. " + " / ".join(tried_reasons)
        else:
            reason = f"No sandbox implementation for platform {platform!r}."
        # Native setup may finish while the gateway is running. Recheck
        # failures instead of requiring a restart to notice recovery.
        return UnavailableBackend(reason=reason, setup_required=setup_required)

    _backend_cache[platform] = backend
    return backend


_probe_cache: SandboxProbe | None = None


def probe(refresh: bool = False) -> SandboxProbe:
    """Describe shell-isolation availability on this machine.

    Cached: probing can spawn a subprocess, so this must not run on every
    tool call. Pass refresh=True after the operator installs a dependency.
    """
    global _probe_cache
    if _probe_cache is not None and not refresh:
        return _probe_cache

    backend = get_backend(refresh=refresh)
    if backend.is_available():
        if backend.trusted:
            _probe_cache = SandboxProbe(kind=backend.kind, state="available")
        else:
            _probe_cache = SandboxProbe(
                kind=backend.kind,
                state="experimental",
                reason=backend.experimental_notice(),
            )
        return _probe_cache

    # Mirrors get_backend(): an unavailable result is never cached, so the
    # health endpoint reflects a dependency (e.g. Docker Desktop) coming up
    # without requiring an app restart.
    return SandboxProbe(
        kind=backend.kind,
        state="unavailable",
        reason=backend.unavailable_reason(),
        setup_required=backend.needs_host_setup(),
    )
