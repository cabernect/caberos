"""Workspace management — path validation and workspace creation (D29)."""

import os
from pathlib import Path

from ..config import settings


def resolve_within(base: str | Path, *parts: str | Path) -> Path:
    """Resolve path segments under ``base`` and verify containment.

    Uses ``os.path.realpath`` + ``startswith`` — the canonicalization pattern
    recognized for path-injection sanitization. ``realpath`` normalizes the
    path and resolves symlinks, so neither ``..`` sequences nor symlinked
    intermediate components can escape the base directory.

    Returns the resolved path. Raises ValueError if it escapes ``base``.
    """
    base_real = os.path.realpath(str(base))
    target = os.path.realpath(str(Path(base_real).joinpath(*parts)))
    if target != base_real and not target.startswith(base_real + os.sep):
        raise ValueError(f"Path escapes allowed root: {parts!r}")
    return Path(target)


class WorkspaceManager:
    """Manages agent workspace directories and path validation."""

    def get_workspace_path(self, agent_id: str) -> Path:
        """Get the workspace path for an agent."""
        return settings.workspace_root / agent_id

    def create_workspace(self, agent_id: str) -> Path:
        """Create the workspace directory if it doesn't exist."""
        path = self.get_workspace_path(agent_id)
        path.mkdir(parents=True, exist_ok=True)
        return path

    def validate_path(
        self, workspace_root: str, rel_path: str, sandbox_mode: str = "strict"
    ) -> str:
        """Resolve a path and validate it against the sandbox policy.

        - strict mode: path must stay within workspace_root
        - open mode: absolute paths are allowed anywhere; relative paths
          resolve against workspace_root

        Returns the safe absolute path.
        Raises ValueError if the path escapes the workspace in strict mode.
        """
        # In open mode, allow absolute paths anywhere
        if sandbox_mode == "open":
            p = Path(rel_path)
            if p.is_absolute():
                return str(p.resolve())
            # Relative paths still resolve against workspace
            return str((Path(workspace_root) / rel_path).resolve())

        # Strict mode — enforce workspace boundary via realpath + startswith,
        # which resolves symlinks and '..' before the containment check.
        try:
            return str(resolve_within(workspace_root, rel_path))
        except ValueError:
            raise ValueError(f"Path escapes workspace: {rel_path}") from None
