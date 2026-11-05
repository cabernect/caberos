"""Seatbelt sandbox backend (macOS — sandbox-exec)."""

import asyncio
import shlex
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from .base import SandboxBackend, ShellResult, kill_process_group
from .process import collect_process

# Apple system tools and their runtimes, not arbitrary installed applications,
# Homebrew prefixes, user homes, or the CaberOS data directory.
_SYSTEM_READ_ROOTS = (
    "/System/Library",
    "/usr/bin",
    "/usr/sbin",
    "/usr/lib",
    "/usr/libexec",
    "/usr/share",
    "/bin",
    "/sbin",
    "/Library/Apple",
    "/Library/Developer/CommandLineTools",
    "/Applications/Xcode.app/Contents/Developer",
    "/private/var/db/dyld",
)
_READABLE_DEVICES = ("/dev/null", "/dev/random", "/dev/urandom", "/dev/zero")


def _build_profile(workspace: str, allow_network: bool) -> str:
    """Allow workspace data and a fixed system runtime; deny everything else."""
    root = Path(workspace).resolve()
    if root == Path(root.anchor) or Path.home().resolve().is_relative_to(root):
        raise ValueError(
            "Strict Seatbelt execution requires a workspace narrower than the home directory."
        )
    if any(
        root.is_relative_to(system) or Path(system).is_relative_to(root)
        for system in _SYSTEM_READ_ROOTS
    ):
        raise ValueError("Strict Seatbelt workspaces cannot overlap system runtime directories.")
    if any(ord(c) < 32 or ord(c) == 127 for c in str(root)):
        raise ValueError("Strict Seatbelt workspaces cannot contain control characters.")
    workspace = str(root).replace("\\", "\\\\").replace('"', '\\"')
    lines = [
        "(version 1)",
        "(deny default)",
        # Traversal/stat are needed to reach allowed roots, but do not grant
        # file contents or directory listings outside those roots.
        "(allow file-read-metadata)",
        f'(allow file-read* (subpath "{workspace}"))',
        f'(allow file-write* (subpath "{workspace}"))',
        f'(allow process-exec* (subpath "{workspace}"))',
        '(allow file-write* (literal "/dev/null"))',
        "(allow process-fork)",
        "(allow sysctl-read)",
    ]
    lines.extend(f'(allow file-read* (subpath "{path}"))' for path in _SYSTEM_READ_ROOTS)
    lines.extend(f'(allow process-exec* (subpath "{path}"))' for path in _SYSTEM_READ_ROOTS)
    lines.extend(f'(allow file-read* (literal "{path}"))' for path in _READABLE_DEVICES)
    if allow_network:
        lines.append("(allow network*)")
    return "\n".join(lines)


class SeatbeltBackend(SandboxBackend):
    """macOS sandbox-exec backend — zero install, built into macOS."""

    kind = "seatbelt"

    def __init__(self) -> None:
        self._probe_cache: bool | None = None
        self._reason: str | None = None

    def is_available(self) -> bool:
        if self._probe_cache is not None:
            return self._probe_cache
        self._probe_cache = False
        if shutil.which("sandbox-exec") is None:
            self._reason = "sandbox-exec is not on PATH (unexpected on macOS)."
            return False
        self._reason = (
            "Seatbelt workspace confinement self-check failed. "
            "Strict execution is unavailable; the permissive profile will not be used."
        )
        try:
            with tempfile.TemporaryDirectory(prefix="caberos-seatbelt-probe-") as tmp:
                root = Path(tmp).resolve()
                workspace = root / "workspace"
                workspace.mkdir()
                outside = root / "synthetic-sibling"
                outside.write_text("synthetic-only", encoding="utf-8")
                sibling = shlex.quote(str(outside))
                command = (
                    "printf ok > inside || exit 1; "
                    'test "$(/bin/cat inside)" = ok || exit 1; '
                    f"if /bin/cat {sibling} >/dev/null 2>/dev/null; then exit 1; fi; "
                    f"if (printf changed > {sibling}) 2>/dev/null; then exit 1; fi; "
                    "printf seatbelt-ready"
                )
                result = subprocess.run(
                    self.spawn_argv(str(workspace), command),
                    cwd=workspace,
                    env=self.spawn_env(str(workspace)),
                    capture_output=True,
                    timeout=5,
                    start_new_session=True,
                )
                self._probe_cache = (
                    result.returncode == 0
                    and result.stdout == b"seatbelt-ready"
                    and (workspace / "inside").read_text(encoding="utf-8") == "ok"
                    and outside.read_text(encoding="utf-8") == "synthetic-only"
                )
        except (OSError, ValueError, subprocess.SubprocessError):
            return False
        if self._probe_cache:
            self._reason = None
        return self._probe_cache

    def unavailable_reason(self) -> str | None:
        self.is_available()
        return self._reason

    def spawn_argv(
        self, workspace_path: str, command: str, allow_network: bool = False
    ) -> list[str]:
        profile = _build_profile(workspace_path, allow_network)
        return [
            "/usr/bin/sandbox-exec",
            "-p",
            profile,
            "--",
            "/bin/sh",
            "-c",
            command,
        ]

    def spawn_env(self, workspace_path: str) -> dict[str, str] | None:
        ws_resolved = str(Path(workspace_path).resolve())
        return {
            "PATH": "/usr/bin:/bin",
            "HOME": ws_resolved,
            "TMPDIR": ws_resolved,
            "TMP": ws_resolved,
            "TEMP": ws_resolved,
        }

    async def run_command(
        self, workspace_path: str, command: str, timeout: int = 30, allow_network: bool = False
    ) -> ShellResult:
        ws_resolved = str(Path(workspace_path).resolve())
        start = time.monotonic()
        proc = await asyncio.create_subprocess_exec(
            *self.spawn_argv(ws_resolved, command, allow_network),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=ws_resolved,
            env=self.spawn_env(ws_resolved),
            start_new_session=True,
        )
        return await collect_process(
            proc, timeout=timeout, started_at=start, cleanup=kill_process_group
        )
