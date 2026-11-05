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

# Operator-private trees: user homes (keys, browser profiles, repos, agent
# state), per-user temp/cache dirs, and launchd sockets such as SSH agents.
# dyld and every real tool need broad read/exec to launch on modern macOS,
# so confinement works by denying these trees and re-allowing the workspace
# underneath — verified live: SIGABRT at launch under subpath-only grants.
_PRIVATE_DENY_ROOTS = ("/Users", "/private/var/folders", "/private/tmp")


def _build_profile(workspace: str, allow_network: bool) -> str:
    """Deny operator-private trees; confine writes to the workspace."""
    root = Path(workspace).resolve()
    if root == Path(root.anchor) or Path.home().resolve().is_relative_to(root):
        raise ValueError(
            "Strict Seatbelt execution requires a workspace narrower than the home directory."
        )
    if any(
        str(root) == denied or denied.startswith(str(root) + "/") for denied in _PRIVATE_DENY_ROOTS
    ):
        raise ValueError("Strict Seatbelt workspaces cannot contain a private deny root.")
    if any(ord(c) < 32 or ord(c) == 127 for c in str(root)):
        raise ValueError("Strict Seatbelt workspaces cannot contain control characters.")
    workspace = str(root).replace("\\", "\\\\").replace('"', '\\"')
    lines = [
        "(version 1)",
        "(deny default)",
        # Last matching rule wins: broad runtime access first, then the
        # private-tree denies, then the workspace re-allow underneath.
        "(allow file-read-metadata)",
        "(allow sysctl-read)",
        "(allow process-fork)",
        "(allow process-exec*)",
        "(allow file-read*)",
        *(f'(deny file-read* (subpath "{denied}"))' for denied in _PRIVATE_DENY_ROOTS),
        f'(allow file-read* (subpath "{workspace}"))',
        "(deny file-write*)",
        f'(allow file-write* (subpath "{workspace}"))',
        '(allow file-write* (literal "/dev/null"))',
    ]
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
