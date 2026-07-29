"""Workspace management — path validation and workspace creation (D29)."""

from pathlib import Path

from ..config import settings


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

    def validate_path(self, workspace_root: str, rel_path: str) -> str:
        """Resolve a path relative to the workspace root. Reject if it escapes.

        Returns the safe absolute path.
        Raises ValueError if the path escapes the workspace.
        """
        root = Path(workspace_root).resolve()
        # Join and resolve — if the result is not under root, it escaped
        target = (root / rel_path).resolve()
        if not str(target).startswith(str(root)):
            raise ValueError(f"Path escapes workspace: {rel_path}")
        return str(target)
