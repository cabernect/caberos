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
    """Write a file to the workspace. Returns a unified diff if the file existed."""
    import difflib

    wm = WorkspaceManager()
    path = wm.validate_path(workspace_path, args["path"])
    os.makedirs(os.path.dirname(path), exist_ok=True) if os.path.dirname(path) else None

    # Capture before content for diff (if file exists)
    before_content = None
    if os.path.isfile(path):
        with open(path, encoding="utf-8", errors="replace") as f:
            before_content = f.read()

    # Write the new content
    with open(path, "w", encoding="utf-8") as f:
        f.write(args["content"])

    result: dict[str, Any] = {
        "success": True,
        "path": args["path"],
        "bytes": len(args["content"]),
    }

    # Generate unified diff if the file existed and changed
    if before_content is not None:
        if before_content != args["content"]:
            diff_lines = list(difflib.unified_diff(
                before_content.splitlines(keepends=True),
                args["content"].splitlines(keepends=True),
                fromfile=f"a/{args['path']}",
                tofile=f"b/{args['path']}",
            ))
            result["diff"] = "".join(diff_lines)
            result["action"] = "modified"
        else:
            result["action"] = "unchanged"
    else:
        result["action"] = "created"

    return result


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
