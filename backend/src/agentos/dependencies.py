"""Optional Tools & Runtimes — dependency readiness (W11 Track B slice).

Readiness only — this module never installs, downloads, or mutates PATH.
Install jobs are a later slice; operators see honest status plus whether a
publisher-verified managed recipe exists for their platform.
"""

from __future__ import annotations

import asyncio
import copy
import json
import logging
import os
import platform
import re
import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from .config import settings

log = logging.getLogger("agentos.dependencies")

_VERSION_RE = re.compile(r"(\d+)\.(\d+)\.(\d+)([-.][\w.+-]*)?")
_CACHE_TTL = 60.0  # seconds (monotonic) per registry instance
_CMD_TIMEOUT = 3.0  # per health command, includes read + wait
_PROBE_DEADLINE = 15.0  # whole status pass
_MAX_STREAM = 4096  # per stdout/stderr stream
_MAX_OUTPUT = 8192  # combined

Runner = Callable[..., Awaitable[tuple[int, bytes, bytes]]]
Finder = Callable[[str], str | None]

# Same candidate roots as the MCP stdio resolver — no PATH mutation.
_SYSTEM_DIRS = [
    "/opt/homebrew/bin",
    "/usr/local/bin",
    os.path.expanduser("~/.local/bin"),
]


class OutputLimitExceeded(RuntimeError):
    """Health output exceeded the bounded stream caps."""


def _platform_key() -> str | None:
    machine = platform.machine().lower()
    arch = {
        "arm64": "arm64",
        "aarch64": "arm64",
        "x86_64": "x64",
        "amd64": "x64",
    }.get(machine)
    system = platform.system().lower()
    if system == "darwin":
        return f"darwin-{arch}" if arch else None
    if system == "windows":
        return f"windows-{arch}" if arch else None
    return None


def _recipes() -> dict:
    path = Path(__file__).parent / "defaults" / "runtime-recipes.json"
    try:
        return json.loads(path.read_text()).get("recipes", {})
    except Exception:
        return {}


def _parse_version(text: str) -> tuple[int, int, int] | None:
    match = _VERSION_RE.search(text)
    return tuple(int(g) for g in match.groups()[:3]) if match else None


def _is_windows() -> bool:
    return platform.system() == "Windows"


def _is_executable(path: Path) -> bool:
    """A file that exists and can plausibly be executed on this platform."""
    if not path.is_file():
        return False
    if _is_windows():
        # X_OK is meaningless on Windows — a resolved .exe/.cmd/.bat or an
        # extension-less executable file counts.
        return path.suffix.lower() in (".exe", ".cmd", ".bat", "")
    return os.access(path, os.X_OK)


def _inside(child: Path, parent: Path) -> bool:
    try:
        return child.resolve().is_relative_to(parent.resolve())
    except (OSError, RuntimeError):
        return False


async def _read_stream(stream: Any, cap: int, total: list[int]) -> bytes:
    """Incremental read — raises OutputLimitExceeded the moment a bound
    is crossed instead of buffering the full stream first."""
    buf = bytearray()
    while True:
        chunk = await stream.read(1024)
        if not chunk:
            return bytes(buf)
        buf += chunk
        total[0] += len(chunk)
        if len(buf) > cap or total[0] > _MAX_OUTPUT:
            raise OutputLimitExceeded("health output exceeded bounds")


async def _default_runner(argv: list[str], env: dict[str, str]) -> tuple[int, bytes, bytes]:
    """Bounded exec — no shell, per-command deadline, capped output. The
    child is always reaped: timeout, cancellation and output overruns all
    kill + await this runner's own process."""
    proc = await asyncio.create_subprocess_exec(
        *argv,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
    )
    total = [0]
    wait_task = asyncio.create_task(proc.wait())
    read_out = asyncio.create_task(_read_stream(proc.stdout, _MAX_STREAM, total))
    read_err = asyncio.create_task(_read_stream(proc.stderr, _MAX_STREAM, total))
    try:
        async with asyncio.timeout(_CMD_TIMEOUT):
            # One gather over wait+readers — an OutputLimitExceeded from a
            # reader propagates immediately, not after the child exits.
            await asyncio.gather(wait_task, read_out, read_err)
        return proc.returncode or 0, read_out.result(), read_err.result()
    finally:
        if proc.returncode is None:
            try:
                proc.kill()
            except ProcessLookupError:
                pass
            try:
                await proc.wait()
            except ProcessLookupError:
                pass
        for task in (wait_task, read_out, read_err):
            task.cancel()
        await asyncio.gather(wait_task, read_out, read_err, return_exceptions=True)


class RuntimeDependencyRegistry:
    """Status + resolution for the five fixed optional dependencies."""

    def __init__(
        self,
        *,
        data_dir: Path,
        runner: Runner | None = None,
        finder: Finder | None = None,
        platform_key: str | None = None,
    ) -> None:
        self._root = Path(data_dir)
        self._runner = runner or _default_runner
        self._finder = finder  # tests inject; default uses os.environ PATH
        self._platform_key = platform_key if platform_key is not None else _platform_key()
        self._cache: list[dict] | None = None
        self._cache_at = 0.0
        self._last_paths: dict[str, str] = {}
        self._inflight: asyncio.Task | None = None

    # -- public API -------------------------------------------------------

    async def status(self, force: bool = False) -> list[dict]:
        """Cached health-verified status; coalesces in-flight probes."""
        if not force and self._cache is not None:
            if time.monotonic() - self._cache_at < _CACHE_TTL:
                return copy.deepcopy(self._cache)
        if self._inflight is not None and not self._inflight.done():
            return copy.deepcopy(await asyncio.shield(self._inflight))
        self._inflight = asyncio.create_task(self._probe_all())
        try:
            result = await asyncio.shield(self._inflight)
        finally:
            if self._inflight.done():
                self._inflight = None
        return result

    def clear_cache(self) -> None:
        self._cache = None
        self._cache_at = 0.0

    def resolve(self, command: str) -> str | None:
        """Synchronous resolution to the last health-verified path —
        never spawns a process."""
        return self._last_paths.get(command)

    _CHILD_DEP_ORDER = ("node", "npm", "npx", "uv", "uvx", "git")

    def child_environment(self, env: dict | None = None) -> dict:
        """Caller env copy plus verified runtime dirs — node → uv → git,
        deterministic — prepended to PATH (the caller's own PATH or the
        process PATH when the caller gave none). Caller's keys are
        preserved; no backend secrets are forwarded; os.environ is never
        mutated."""
        out = dict(env or {})
        dirs: list[str] = []
        for cmd in self._CHILD_DEP_ORDER:
            path = self._last_paths.get(cmd)
            if path:
                d = str(Path(path).parent)
                if d not in dirs:
                    dirs.append(d)
        base = out.get("PATH") or os.environ.get("PATH", "")
        out["PATH"] = os.pathsep.join([*dirs, base]) if dirs else base
        return out

    # -- probing ----------------------------------------------------------

    async def _probe_all(self) -> list[dict]:
        try:
            rows = await asyncio.wait_for(self._probe_all_inner(), _PROBE_DEADLINE)
        except TimeoutError:
            rows = [
                self._row(did, status="error", detail="probe timed out") for did in _DEPENDENCIES
            ]
        self._cache = rows
        self._cache_at = time.monotonic()
        # Atomic replace — a failed pass never keeps a stale ready path.
        last: dict[str, str] = {}
        for row in rows:
            if row["status"] == "ready":
                last.update(row["executables"])
        self._last_paths = last
        return copy.deepcopy(rows)

    async def _probe_all_inner(self) -> list[dict]:
        return await asyncio.gather(*(self._probe_dep(did) for did in _DEPENDENCIES))

    async def _probe_dep(self, dep_id: str) -> dict:
        """Evaluate candidate groups in source order; first health-ready
        candidate wins. An explicit-override failure is terminal — never
        silently falls back to a different source."""
        spec = _DEPENDENCIES[dep_id]
        try:
            if dep_id == "chromium":
                return self._chromium_row()
            candidates, hard_error = self._candidates(dep_id, spec)
            if hard_error is not None:
                return self._row(
                    dep_id,
                    status="error",
                    source="override",
                    detail=hard_error,
                )
            if not candidates:
                return self._row(dep_id, status="missing", source="none")
            best_failure: dict | None = None
            best_source = "none"
            best_executables: dict = {}
            for cand in candidates:
                versions = await self._health(dep_id, spec, cand["executables"])
                if versions == "shim_blocked":
                    # Apple git shim without developer tools — skip this
                    # candidate entirely (never probes /usr/bin/git).
                    continue
                if versions is None:
                    failure = {
                        "status": "error",
                        "detail": "health check failed",
                        "version": None,
                    }
                else:
                    status, detail = self._compatible(
                        dep_id, spec, versions, cand.get("declared_version")
                    )
                    if status == "ready":
                        return self._row(
                            dep_id,
                            status="ready",
                            source=cand["source"],
                            executables=cand["executables"],
                            version=versions,
                        )
                    failure = {
                        "status": status,
                        "detail": detail,
                        "version": versions,
                    }
                # Keep the most informative failure: a health-evaluated
                # incompatible beats a generic check error.
                if best_failure is None or (
                    best_failure["status"] == "error" and failure["status"] == "incompatible"
                ):
                    best_failure = failure
                    best_source = cand["source"]
                    best_executables = cand["executables"]
            if best_failure is None:
                return self._row(dep_id, status="missing", source="none")
            return self._row(
                dep_id,
                status=best_failure["status"],
                source=best_source,
                executables=best_executables,
                version=best_failure.get("version"),
                detail=best_failure.get("detail"),
            )
        except Exception:
            log.debug("dependency probe failed: %s", dep_id, exc_info=True)
            return self._row(dep_id, status="error", detail="probe failed")

    # -- candidates --------------------------------------------------------

    def _candidates(self, dep_id: str, spec: dict) -> tuple[list[dict], str | None]:
        commands = spec["commands"]
        overrides = settings.runtime_binary_overrides or {}
        explicit = {c: overrides[c] for c in commands if c in overrides}
        if explicit:
            group, err = self._override_group(commands, explicit)
            if err is not None:
                return [], err
            return [{"executables": group, "source": "override"}], None

        candidates: list[dict] = []
        if len(commands) == 1:
            # Every matching location is a candidate in order — a broken
            # earlier install must not mask a ready later one.
            seen: set[str] = set()
            well_known = (
                _libreoffice_dirs() if dep_id == "libreoffice" else spec.get("well_known", [])
            )
            for path in self._find_all_in_dirs(commands[0], [*self._search_dirs(), *well_known]):
                if path in seen:
                    continue
                seen.add(path)
                candidates.append({"executables": {commands[0]: path}, "source": "system"})
        else:
            for group in self._system_groups(dep_id, commands, spec):
                candidates.append({"executables": group, "source": "system"})
        managed, managed_err = self._managed_candidate(dep_id, spec)
        if managed is not None:
            candidates.append(managed)
        elif managed_err and not candidates:
            return [], managed_err
        return candidates, None

    def _override_group(
        self, commands: list[str], explicit: dict[str, str]
    ) -> tuple[dict, str | None]:
        """Explicit overrides must form one co-installed group: every
        listed path is executable and shares one parent dir; missing
        companions resolve inside that dir only — never a random PATH
        installation."""
        paths: dict[str, Path] = {}
        for cmd, raw in explicit.items():
            candidate = Path(raw).expanduser()
            if not _is_executable(candidate):
                return {}, f"override path for '{cmd}' is not executable"
            paths[cmd] = candidate
        parents = {p.parent for p in paths.values()}
        if len(parents) > 1:
            return {}, "override commands live in different directories"
        parent = next(iter(parents))
        for cmd in commands:
            if cmd in paths:
                continue
            companion = self._companion_in(parent, cmd)
            if companion is None:
                return {}, f"override incomplete — missing '{cmd}' beside {parent}"
            paths[cmd] = companion
        return {c: str(paths[c]) for c in commands}, None

    def _companion_in(self, parent: Path, command: str) -> Path | None:
        for name in self._candidate_names(command):
            candidate = parent / name
            if _is_executable(candidate):
                return candidate
        return None

    def _system_groups(self, dep_id: str, commands: list[str], spec: dict) -> list[dict]:
        """Each directory containing ALL commands of a group is one
        candidate — never mixed parents across installations."""
        well_known = _libreoffice_dirs() if dep_id == "libreoffice" else spec.get("well_known", [])
        dirs = [*self._search_dirs(), *well_known]
        if self._finder is not None:
            found: dict[str, str] = {}
            for cmd in commands:
                path = self._finder(cmd)
                if path is None:
                    return []
                found[cmd] = path
            parents = {str(Path(p).parent) for p in found.values()}
            if len(parents) != 1:
                return []
            return [found]
        groups: list[dict] = []
        groups: list[dict] = []
        seen_groups: set[tuple] = set()
        for d in dirs:
            found = {}
            for cmd in commands:
                path = self._find_in_dirs(cmd, [d])
                if path:
                    found[cmd] = path
            if len(found) == len(commands):
                key = tuple(found[c] for c in commands)
                if key not in seen_groups:
                    seen_groups.add(key)
                    groups.append(found)
        return groups

    def _managed_candidate(self, dep_id: str, spec: dict) -> tuple[dict | None, str | None]:
        """Strict read-only active-pointer validation — bounded read, no
        writes, every path confined inside the managed root."""
        pointer = self._root / dep_id / "active.json"
        if not pointer.is_file():
            return None, None

        def invalid() -> tuple[None, str]:
            return None, "invalid managed runtime pointer"

        # Containment BEFORE reading: the dep root must stay inside the
        # configured registry root and the pointer inside the dep root —
        # a symlinked escape never even opens.
        root_anchor = self._root.resolve()
        dep_base = (self._root / dep_id).resolve()
        resolved_pointer = pointer.resolve()
        if not (_inside(dep_base, root_anchor) and _inside(resolved_pointer, dep_base)):
            return invalid()
        try:
            with open(resolved_pointer, "rb") as fh:
                raw = fh.read(16385)
        except OSError:
            return invalid()
        if len(raw) > 16384:
            return invalid()
        try:
            data = json.loads(raw)
        except (ValueError, UnicodeDecodeError):
            return invalid()
        if not isinstance(data, dict):
            return invalid()
        directory = data.get("directory")
        platform_tag = data.get("platform")
        version = data.get("version")
        for value in (directory, platform_tag, version):
            if not isinstance(value, str) or not value:
                return invalid()
        if platform_tag != self._platform_key:
            return None, "managed runtime built for another platform"
        rel_dir = Path(directory)
        if rel_dir.is_absolute() or ".." in rel_dir.parts:
            return invalid()
        base = (self._root / dep_id).resolve()
        version_dir = base / directory
        if not _inside(version_dir, base) or not version_dir.is_dir():
            return invalid()
        executables = data.get("executables")
        if not isinstance(executables, dict):
            return invalid()
        required = set(spec["commands"])
        if set(executables.keys()) != required:
            return invalid()
        out: dict[str, str] = {}
        for cmd, rel in executables.items():
            if not isinstance(rel, str) or not rel:
                return invalid()
            rel_path = Path(rel)
            if rel_path.is_absolute() or ".." in rel_path.parts:
                return invalid()
            candidate = version_dir / rel
            resolved = candidate.resolve()
            if not _inside(resolved, version_dir) or not _is_executable(resolved):
                return invalid()
            out[cmd] = str(resolved)
        return {
            "executables": out,
            "source": "managed",
            "declared_version": version,
        }, None

    # -- health ------------------------------------------------------------

    async def _health(self, dep_id: str, spec: dict, executables: dict) -> dict | None:
        # macOS git shim guard — xcode-select must succeed before probing
        # /usr/bin/git, or the shim would trigger an Apple install popup.
        if dep_id == "git" and platform.system() == "Darwin":
            if executables.get("git") == "/usr/bin/git":
                try:
                    code, _, _ = await self._runner(
                        ["/usr/bin/xcode-select", "-p"], env=self._child_env({})
                    )
                except Exception:
                    code = 1
                if code != 0:
                    return "shim_blocked"
        env = self._child_env(executables)
        versions: dict[str, dict] = {}
        for cmd in spec["commands"]:
            path = executables.get(cmd)
            args = spec["health"].get(cmd)
            if path is None or args is None:
                return None
            argv = self._health_argv(cmd, path, args, executables)
            if argv is None:
                return None
            try:
                code, out, _err = await self._runner(argv, env=env)
            except Exception:
                return None
            if code != 0:
                return None
            text = out.decode(errors="replace")
            match = _VERSION_RE.search(text)
            versions[cmd] = {
                "version": _parse_version(text),
                "prerelease": bool(match and match.group(4)),
            }
        return versions

    def _health_argv(
        self, command: str, path: str, args: list[str], executables: dict
    ) -> list[str] | None:
        """Fixed health argv only — Windows npm/npx wrappers run through
        the co-installed node.exe + the package's own cli.js, never via
        cmd.exe or an arbitrary shim."""
        p = Path(path)
        if not _is_windows() or p.suffix.lower() not in (".cmd", ".bat"):
            return [path, *args]
        # Only npm/npx have a fixed trusted cli.js entrypoint — any other
        # .cmd/.bat wrapper is never executed (no COMSPEC, no WinError 193).
        if command not in ("npm", "npx"):
            return None
        parent = p.parent
        node = executables.get("node")
        if node is None:
            return None
        node_path = Path(node)
        if node_path.parent != parent:
            return None
        script = parent / "node_modules" / "npm" / "bin" / f"{command}-cli.js"
        try:
            if not script.resolve().is_relative_to(parent.resolve()):
                return None
        except (OSError, RuntimeError):
            return None
        if not script.is_file():
            return None
        return [str(node_path), str(script), *args]

    @staticmethod
    def _child_env(executables: dict) -> dict:
        env = dict(os.environ)
        dirs = {str(Path(p).parent) for p in executables.values()}
        env["PATH"] = os.pathsep.join([*dirs, env.get("PATH", "")])
        env["npm_config_update_notifier"] = "false"
        env["npm_config_audit"] = "false"
        env["npm_config_fund"] = "false"
        env["UV_NO_PROGRESS"] = "1"
        return env

    @staticmethod
    def _compatible(
        dep_id: str,
        spec: dict,
        versions: dict,
        declared_version: str | None = None,
    ) -> tuple[str, str | None]:
        for cmd in spec["commands"]:
            if versions.get(cmd, {}).get("version") is None:
                return "incompatible", "unparseable version"
        if dep_id == "nodejs":
            node = versions["node"]
            if node.get("prerelease"):
                return "incompatible", "prerelease build"
            if node["version"][0] < 22:
                return "incompatible", "Node.js 22+ is the supported baseline"
        if declared_version:
            primary = spec["commands"][0]
            declared = _parse_version(declared_version)
            if declared is None or declared != versions[primary]["version"]:
                return "incompatible", "managed version differs from pointer"
        return "ready", None

    # -- chromium ------------------------------------------------------------

    def _chromium_row(self) -> dict:
        from .browser import runtime as browser_runtime

        status = browser_runtime.runtime_status()
        if status.get("status") == "ok":
            binary = status.get("binary")
            raw_source = status.get("source") or ""
            source = (
                "managed"
                if status.get("managed")
                else ("override" if "override" in raw_source else "system")
            )
            return self._row(
                "chromium",
                status="ready",
                source=source,
                # The static pin is the MANAGED build's version only —
                # never claim it for a different system browser.
                version=status.get("version") if source == "managed" else None,
                executables={"chromium": binary} if binary else {},
            )
        return self._row(
            "chromium",
            status="missing",
            source="none",
            detail=status.get("detail"),
        )

    # -- rows / helpers -------------------------------------------------------

    def _row(
        self,
        dep_id: str,
        *,
        status: str,
        source: str = "none",
        version: Any = None,
        executables: dict | None = None,
        detail: str | None = None,
    ) -> dict:
        spec = _DEPENDENCIES[dep_id]
        managed = spec.get("managed", False)
        if managed:
            recipe = _recipes().get(dep_id)
            managed = bool(
                recipe and self._platform_key and self._platform_key in recipe.get("platforms", {})
            )
        if dep_id == "chromium":
            from .browser import runtime as browser_runtime

            managed = browser_runtime._platform_key() is not None
        return {
            "id": dep_id,
            "label": spec["label"],
            "status": status,
            "source": source,
            "version": self._format_version(version),
            "executables": executables or {},
            "detail": detail,
            "unlocks": spec["unlocks"],
            "managed_recipe_available": managed,
            "guidance_url": spec.get("guidance_url"),
        }

    def _search_dirs(self) -> list[str]:
        path_dirs = [d for d in os.environ.get("PATH", "").split(os.pathsep) if d]
        dirs = list(path_dirs)
        for d in _SYSTEM_DIRS:
            if d not in dirs:
                dirs.append(d)
        custom = os.environ.get("CABEROS_MCP_RUNTIME_PATH")
        if custom and custom not in dirs:
            dirs.append(custom)
        return dirs

    def _find_in_dirs(self, command: str, dirs: list[str]) -> str | None:
        if self._finder is not None:
            return self._finder(command)
        for d in dirs:
            for name in self._candidate_names(command):
                candidate = Path(d) / name
                if candidate.is_file() and _is_executable(candidate):
                    return str(candidate)
        return None

    def _find_all_in_dirs(self, command: str, dirs: list[str]) -> list[str]:
        if self._finder is not None:
            found = self._finder(command)
            return [found] if found else []
        out = []
        for d in dirs:
            for name in self._candidate_names(command):
                candidate = Path(d) / name
                if candidate.is_file() and _is_executable(candidate):
                    out.append(str(candidate))
                    break
        return out

    @staticmethod
    def _candidate_names(command: str) -> list[str]:
        if _is_windows():
            return [f"{command}{ext}" for ext in (".exe", ".cmd", ".bat")] + [command]
        return [command]

    @staticmethod
    def _format_version(versions: Any) -> str | None:
        if isinstance(versions, dict):
            for cmd, entry in versions.items():
                v = entry.get("version") if isinstance(entry, dict) else entry
                if v:
                    return ".".join(str(p) for p in v)
            return None
        return versions


_DEPENDENCIES: dict[str, dict] = {
    "nodejs": {
        "label": "Node.js",
        "commands": ["node", "npm", "npx"],
        "health": {
            "node": ["--version"],
            "npm": ["--version"],
            "npx": ["--version"],
        },
        "unlocks": "Local MCP servers (stdio)",
        "managed": True,
    },
    "uv": {
        "label": "uv",
        "commands": ["uv", "uvx"],
        "health": {"uv": ["--version"], "uvx": ["--version"]},
        "unlocks": "Python MCP servers and tools",
        "managed": True,
    },
    "git": {
        "label": "Git",
        "commands": ["git"],
        "health": {"git": ["--version"]},
        "unlocks": "Git MCP servers and workspace tooling",
        "managed": True,
    },
    "libreoffice": {
        "label": "LibreOffice",
        "commands": ["soffice"],
        "health": {"soffice": ["--version"]},
        "unlocks": "Layout-faithful Office→PDF export",
        "managed": False,
        "guidance_url": "https://www.libreoffice.org/download/download-libreoffice/",
    },
    "chromium": {
        "label": "Chromium",
        "commands": ["chromium"],
        "health": {},
        "unlocks": "Managed browser automation and previews",
        "managed": True,
    },
}


def _libreoffice_dirs() -> list[str]:
    dirs = [
        "/Applications/LibreOffice.app/Contents/MacOS",
        "/usr/lib/libreoffice/program",
    ]
    for env_key in ("PROGRAMFILES", "PROGRAMFILES(X86)", "PROGRAMW6432"):
        base = os.environ.get(env_key)
        if base:
            dirs.append(os.path.join(base, "LibreOffice", "program"))
    return dirs


_REGISTRY: RuntimeDependencyRegistry | None = None


def get_dependency_registry() -> RuntimeDependencyRegistry:
    global _REGISTRY
    if _REGISTRY is None:
        _REGISTRY = RuntimeDependencyRegistry(data_dir=settings.db_path.parent / "managed-runtimes")
    return _REGISTRY
