"""Installed-tool discovery for local terminal children, not permission policy."""

import ntpath
import os
from pathlib import Path

from .config import settings
from .dependencies import get_dependency_registry
from .runtime_support import runtime_directories, standard_runtime_directories

_RUNTIME_COMMANDS = ("node", "npm", "npx", "uv", "uvx", "git")


def installed_runtime_directories() -> list[str]:
    """Use cached readiness and common locations, without probing executables."""
    registry = get_dependency_registry()
    discovered = [
        str(Path(path).parent)
        for command in _RUNTIME_COMMANDS
        if (path := registry.resolve(command))
    ]
    if settings.runtime_source == "system":
        discovered.extend(runtime_directories())
    elif settings.runtime_source == "auto":
        discovered.extend(standard_runtime_directories())
    return [path for path in discovered if os.path.isabs(path) and Path(path).is_dir()]


def terminal_path(base: str) -> str:
    """Put the verified runtime selection before absolute inherited entries.

    No shell profiles, downloads, health probes or process-global env changes.
    Sandbox backends still decide which of these paths are accessible.
    """
    entries = [*installed_runtime_directories(), *base.split(os.pathsep)]
    result: list[str] = []
    seen: set[str] = set()
    for path in entries:
        if not os.path.isabs(path):
            continue
        key = os.path.normcase(os.path.normpath(path))
        if key not in seen:
            seen.add(key)
            result.append(path)
    return os.pathsep.join(result)


def open_terminal_environment() -> dict[str, str]:
    env = dict(os.environ)
    env["PATH"] = terminal_path(env.get("PATH", os.defpath))
    return env


async def prepare_terminal_runtimes() -> None:
    """Warm the same bounded readiness selection used by MCP; never install."""
    registry = get_dependency_registry()
    await registry.status()
    if any(
        path and not Path(path).is_file()
        for command in _RUNTIME_COMMANDS
        if (path := registry.resolve(command))
    ):
        await registry.status(force=True)


def strict_runtime_roots(workspace: str) -> tuple[str, ...]:
    return get_dependency_registry().managed_runtime_roots(workspace)


def workspace_tool_environment(workspace: str, *, windows: bool = False) -> dict[str, str]:
    """Keep package-manager state within the workspace without creating files."""
    join = ntpath.join if windows else os.path.join
    cache = join(workspace, ".cache")
    return {
        "HOME": workspace,
        "TMPDIR": workspace,
        "TMP": workspace,
        "TEMP": workspace,
        "XDG_CACHE_HOME": cache,
        "npm_config_cache": join(cache, "npm"),
        "npm_config_prefix": join(workspace, ".local"),
        "UV_CACHE_DIR": join(cache, "uv"),
        "PIP_CACHE_DIR": join(cache, "pip"),
    }
