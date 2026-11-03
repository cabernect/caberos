"""Workspace management — path validation, root resolution, creation (D29)."""

import os
from pathlib import Path
from typing import Any

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

    def resolve_agent_root(self, agent_id: str, configured: str | None) -> Path:
        """The agent's default root for NEW sessions: the configured external
        directory, or the CaberOS-managed workspace when unset."""
        if configured and configured.strip():
            return Path(os.path.realpath(os.path.expanduser(configured.strip())))
        return Path(os.path.realpath(str(self.get_workspace_path(agent_id))))

    def resolve_session_root(self, session: Any, agent_id: str, configured: str | None) -> Path:
        """The root a session's work actually happens in.

        A pinned session keeps its recorded root forever — changing the
        agent's default only affects sessions created afterward. Legacy
        unpinned rows resolve the current default (the pre-pin behavior,
        which is also where their files demonstrably were written).
        """
        pinned = getattr(session, "workspace_path", None)
        if pinned:
            return Path(pinned)
        return self.resolve_agent_root(agent_id, configured)

    def is_managed_root(self, agent_id: str, path: str | Path) -> bool:
        """Whether a path resolves to this agent's managed workspace."""
        return os.path.realpath(str(path)) == os.path.realpath(
            str(self.get_workspace_path(agent_id))
        )

    def validate_external_root(self, path: str) -> str:
        """Canonicalize an operator-selected directory for attachment.

        Existing directories only — selecting a folder never creates one,
        and the stored value is the realpath so later config reads and
        containment checks agree on one location.
        """
        raw = path.strip()
        if not raw:
            raise ValueError("workspace path is empty")
        real = os.path.realpath(os.path.expanduser(raw))
        if not os.path.isdir(real):
            raise ValueError(f"not an existing directory: {path}")
        return real

    async def resolve_api_root(self, db: Any, agent_id: str, session_id: str | None = None) -> Path:
        """Resolve the workspace root for file/browse/ingest APIs.

        A session's pinned root wins; absent or unpinned, the agent's
        current default. An unknown or foreign session raises LookupError —
        never a silent fallback to another directory.
        """
        from ..agent_service import get_active_config
        from ..models.session import Session

        if session_id:
            session = await db.get(Session, session_id)
            if session is None or session.agent_id != agent_id:
                raise LookupError(f"session {session_id} not found for agent {agent_id}")
            if session.workspace_path:
                return Path(session.workspace_path)
        config = await get_active_config(db, agent_id)
        return self.resolve_agent_root(agent_id, config.workspace if config else "")

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
