"""bwrap sandbox backend (Linux — bubblewrap)."""

import asyncio
import shlex
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from ..terminal_environment import strict_runtime_roots, terminal_path, workspace_tool_environment
from .base import SandboxBackend, ShellResult, kill_process_group
from .process import collect_process


class BwrapBackend(SandboxBackend):
    """Linux bubblewrap (bwrap) backend."""

    kind = "bwrap"

    _probe_cache: bool | None = None

    def is_available(self) -> bool:
        if self._probe_cache is not None:
            return self._probe_cache
        binary = shutil.which("bwrap")
        if binary is None:
            self._probe_cache = False
            return False
        try:
            with tempfile.TemporaryDirectory(prefix="caberos-bwrap-probe-") as directory:
                root = Path(directory)
                workspace = root / "workspace"
                workspace.mkdir()
                sibling = root / "synthetic-sibling"
                sibling.write_text("outside")
                outside = shlex.quote(str(sibling))
                command = (
                    "printf ok > inside && "
                    f"if cat {outside} >/dev/null 2>&1; then exit 7; fi; "
                    f"if (printf changed > {outside}) 2>/dev/null; then exit 8; fi; "
                    'test "$(cat inside)" = ok && printf bwrap-ready'
                )
                args = self.spawn_argv(str(workspace), command)
                args[0] = binary
                result = subprocess.run(
                    args,
                    env=self.spawn_env(str(workspace)),
                    capture_output=True,
                    timeout=5,
                )
                self._probe_cache = (
                    result.returncode == 0
                    and result.stdout == b"bwrap-ready"
                    and (workspace / "inside").read_text() == "ok"
                    and sibling.read_text() == "outside"
                )
        except Exception:
            self._probe_cache = False
        return self._probe_cache

    def unavailable_reason(self) -> str | None:
        if self.is_available():
            return None
        if shutil.which("bwrap") is None:
            return "bubblewrap is not installed. Install it with: apt install bubblewrap"
        return "bubblewrap is installed but its confined workspace self-check failed here."

    def spawn_argv(
        self, workspace_path: str, command: str, allow_network: bool = False
    ) -> list[str]:
        workspace = str(Path(workspace_path).resolve())
        runtimes = strict_runtime_roots(workspace)
        args = [shutil.which("bwrap") or "bwrap", "--clearenv"]
        env = {**self.spawn_env(workspace_path), **workspace_tool_environment("/workspace")}
        for key, value in env.items():
            args.extend(["--setenv", key, value])
        args.extend(
            [
                "--ro-bind",
                "/usr",
                "/usr",
                "--ro-bind",
                "/bin",
                "/bin",
                "--ro-bind-try",
                "/lib",
                "/lib",
                "--ro-bind-try",
                "/lib64",
                "/lib64",
                "--dev",
                "/dev",
                "--proc",
                "/proc",
                "--tmpfs",
                "/tmp",
                "--bind",
                workspace,
                "/workspace",
                "--chdir",
                "/workspace",
                "--unshare-all",
                "--die-with-parent",
                "--new-session",
            ]
        )
        for runtime in runtimes:
            args.extend(["--ro-bind", runtime, runtime])
        if allow_network:
            args.append("--share-net")
            # Public resolver/trust configuration only, never the whole host /etc.
            for path in (
                "/etc/resolv.conf",
                "/etc/hosts",
                "/etc/nsswitch.conf",
                "/etc/ssl/certs",
                "/etc/pki/tls/certs",
                "/etc/pki/ca-trust/extracted",
            ):
                args.extend(["--ro-bind-try", path, path])
        args.extend(["/bin/sh", "-c", command])
        return args

    def spawn_env(self, workspace_path: str) -> dict[str, str]:
        # --clearenv protects the command; this also protects the launcher.
        workspace = str(Path(workspace_path).resolve())
        # Discovery must not create new host mounts or expose home directories.
        path = terminal_path("/usr/bin:/bin")
        roots = (*strict_runtime_roots(workspace), "/usr", "/bin", "/lib", "/lib64")
        path = ":".join(
            entry
            for entry in path.split(":")
            if any(Path(entry).is_relative_to(root) for root in roots)
        )
        return {"PATH": path, **workspace_tool_environment(workspace)}

    async def run_command(
        self, workspace_path: str, command: str, timeout: int = 30, allow_network: bool = False
    ) -> ShellResult:
        start = time.monotonic()
        proc = await asyncio.create_subprocess_exec(
            *self.spawn_argv(workspace_path, command, allow_network),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=self.spawn_env(workspace_path),
            start_new_session=True,
        )
        return await collect_process(
            proc, timeout=timeout, started_at=start, cleanup=kill_process_group
        )
