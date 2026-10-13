"""Shared runtime-dependency primitives.

Used by `dependencies.py` (system/detection paths) and
`runtime_installer.py` (managed installs). Pure helpers only — no
policy, I/O orchestration, or job state lives here.
"""

from __future__ import annotations

import os
from pathlib import Path

# Fixed dependency specs — detection order is override → system → managed.
DEPENDENCIES: dict[str, dict] = {
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
    "chromium": {
        "label": "Chromium",
        "commands": ["chromium"],
        "health": {},
        "unlocks": "Browser automation",
        "managed": True,
    },
}


def inside(child: Path, parent: Path) -> bool:
    try:
        return child.resolve().is_relative_to(parent.resolve())
    except (OSError, RuntimeError):
        return False


def is_executable(path: Path, windows: bool) -> bool:
    """A file that exists and can plausibly be executed on this platform."""
    if not path.is_file():
        return False
    if windows:
        # X_OK is meaningless on Windows — a resolved .exe/.cmd/.bat or an
        # extension-less executable file counts.
        return path.suffix.lower() in (".exe", ".cmd", ".bat", "")
    return os.access(path, os.X_OK)


def probe_environment(executables: dict) -> dict:
    """Child env: os.environ copy with dependency dirs prepended to PATH and
    fixed npm/uv noise flags. os.environ itself is never mutated."""
    env = dict(os.environ)
    dirs = {str(Path(p).parent) for p in executables.values()}
    env["PATH"] = os.pathsep.join([*dirs, env.get("PATH", "")])
    env["npm_config_update_notifier"] = "false"
    env["npm_config_audit"] = "false"
    env["npm_config_fund"] = "false"
    env["UV_NO_PROGRESS"] = "1"
    return env


def npm_entrypoint(
    command: str, path: Path, executables: dict, *, root: Path | None = None
) -> tuple[str, Path] | None:
    """Resolve the fixed trusted cli.js for npm/npx wrappers.

    Only npm/npx have a package-owned entrypoint — any other command never
    maps to cli.js. Requires the co-installed node.exe beside the wrapper
    (same parent), the script present under node_modules/npm/bin, and (when
    `root` is given) the resolved script inside that root — symlink escapes
    are refused. Returns (node path, unresolved script path)."""
    if command not in ("npm", "npx"):
        return None
    parent = path.parent
    node = executables.get("node")
    if node is None or Path(node).parent != parent:
        return None
    script = parent / "node_modules" / "npm" / "bin" / f"{command}-cli.js"
    if not inside(script, root if root is not None else parent):
        return None
    if not script.is_file():
        return None
    return node, script
