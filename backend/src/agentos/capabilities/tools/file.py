"""File capability implementations — file.read, file.write, file.list.

All paths are validated against the workspace boundary before execution (D29).
"""

import os
from typing import Any

from ...sandbox.workspace import WorkspaceManager


async def file_read(args: dict[str, Any], workspace_path: str, **_kwargs: Any) -> dict[str, Any]:
    """Read a file from the workspace."""
    wm = WorkspaceManager()
    path = wm.validate_path(workspace_path, args["path"])
    if not os.path.isfile(path):
        return {"error": f"File not found: {args['path']}"}
    with open(path, encoding="utf-8", errors="replace") as f:
        content = f.read()
    return {"content": content, "path": args["path"]}


async def file_write(args: dict[str, Any], workspace_path: str, **_kwargs: Any) -> dict[str, Any]:
    """Write a file to the workspace."""
    wm = WorkspaceManager()
    path = wm.validate_path(workspace_path, args["path"])
    os.makedirs(os.path.dirname(path), exist_ok=True) if os.path.dirname(path) else None
    with open(path, "w", encoding="utf-8") as f:
        f.write(args["content"])
    return {"success": True, "path": args["path"], "bytes": len(args["content"])}


async def file_list(args: dict[str, Any], workspace_path: str, **_kwargs: Any) -> dict[str, Any]:
    """List files in a directory within the workspace."""
    wm = WorkspaceManager()
    rel_path = args.get("path", ".")
    path = wm.validate_path(workspace_path, rel_path)
    if not os.path.isdir(path):
        return {"error": f"Directory not found: {rel_path}"}
    entries = []
    for name in sorted(os.listdir(path)):
        full = os.path.join(path, name)
        entries.append(
            {
                "name": name,
                "type": "dir" if os.path.isdir(full) else "file",
                "size": os.path.getsize(full) if os.path.isfile(full) else 0,
            }
        )
    return {"entries": entries, "path": rel_path}
