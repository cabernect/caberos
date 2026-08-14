"""File capability implementations — read_file, write_file, search_files.

All paths are validated against the workspace boundary before execution (D29).
search_files merges the old file_search (grep), file_glob (find by pattern),
and file_list (list directory) into one tool with a `mode` parameter.
"""

import base64
import fnmatch
import mimetypes
import os
import re
from typing import Any

from ...sandbox.workspace import WorkspaceManager


async def read_file(args: dict[str, Any], workspace_path: str, **kwargs: Any) -> dict[str, Any]:
    """Read a complete file or an inclusive line range from the workspace."""
    wm = WorkspaceManager()
    path = wm.validate_path(workspace_path, args["path"], kwargs.get("sandbox_mode", "strict"))
    if not os.path.isfile(path):
        return {"error": f"File not found: {args['path']}"}

    mime_type, _ = mimetypes.guess_type(path)
    if mime_type and mime_type.startswith("image/"):
        if not kwargs.get("supports_vision", False):
            return {
                "error": "The selected model cannot inspect image files.",
                "path": args["path"],
                "mime_type": mime_type,
            }
        with open(path, "rb") as f:
            encoded = base64.b64encode(f.read()).decode("ascii")
        return {
            "path": args["path"],
            "mime_type": mime_type,
            "bytes": os.path.getsize(path),
            "_model_content": [
                {"type": "text", "text": f"Image file: {args['path']}"},
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:{mime_type};base64,{encoded}"},
                },
            ],
        }

    start_line = args.get("start_line")
    end_line = args.get("end_line")
    if start_line is None and end_line is None:
        with open(path, encoding="utf-8", errors="replace") as f:
            return {"content": f.read(), "path": args["path"]}

    if start_line is None:
        start_line = 1
    if end_line is None:
        end_line = 2**31 - 1
    if not isinstance(start_line, int) or not isinstance(end_line, int):
        return {"error": "start_line and end_line must be integers"}
    if start_line < 1 or end_line < start_line:
        return {"error": "start_line must be at least 1 and end_line must not be before start_line"}

    with open(path, encoding="utf-8", errors="replace") as f:
        lines = f.readlines()

    total_lines = len(lines)
    selected_end = min(end_line, total_lines)
    content = "".join(lines[start_line - 1 : selected_end]) if start_line <= total_lines else ""
    result: dict[str, Any] = {
        "content": content,
        "path": args["path"],
        "start_line": start_line,
        "end_line": selected_end,
        "total_lines": total_lines,
        "has_more": selected_end < total_lines,
    }
    if result["has_more"]:
        result["next_start_line"] = selected_end + 1
    return result


async def write_file(args: dict[str, Any], workspace_path: str, **kwargs: Any) -> dict[str, Any]:
    """Write a file to the workspace (or anywhere if sandbox is open). Returns a unified diff if the file existed."""
    import difflib

    wm = WorkspaceManager()
    path = wm.validate_path(workspace_path, args["path"], kwargs.get("sandbox_mode", "strict"))
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
            diff_lines = list(
                difflib.unified_diff(
                    before_content.splitlines(keepends=True),
                    args["content"].splitlines(keepends=True),
                    fromfile=f"a/{args['path']}",
                    tofile=f"b/{args['path']}",
                )
            )
            result["diff"] = "".join(diff_lines)
            result["action"] = "modified"
        else:
            result["action"] = "unchanged"
    else:
        result["action"] = "created"

    return result


async def search_files(args: dict[str, Any], workspace_path: str, **kwargs: Any) -> dict[str, Any]:
    """Search files in the workspace — three modes:

    - mode="content" (default): grep-like content search. Requires `pattern` (regex).
      Optional: `glob` filter, `ignore_case`, `max_results`.
    - mode="name": find files by glob pattern. Requires `pattern` (glob like "*.py").
      Optional: `max_results`.
    - mode="list": list directory contents. Optional: `path` (default ".").
    """
    wm = WorkspaceManager()
    sandbox_mode = kwargs.get("sandbox_mode", "strict")
    mode = args.get("mode", "content")

    if mode == "list":
        rel_path = args.get("path", ".")
        path = wm.validate_path(workspace_path, rel_path, sandbox_mode)
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
        return {"entries": entries, "path": rel_path, "mode": "list"}

    rel_path = args.get("path", ".")
    root = wm.validate_path(workspace_path, rel_path, sandbox_mode)
    pattern = args.get("pattern", "")
    max_results = args.get("max_results", 50)

    if mode == "name":
        results: list[str] = []
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if not d.startswith(".")]
            for filename in filenames:
                full_path = os.path.join(dirpath, filename)
                rel = os.path.relpath(full_path, workspace_path)
                if fnmatch.fnmatch(rel, pattern) or fnmatch.fnmatch(filename, pattern):
                    results.append(rel)
                    if len(results) >= max_results:
                        return {
                            "files": results,
                            "truncated": True,
                            "count": len(results),
                            "mode": "name",
                        }
        return {"files": results, "truncated": False, "count": len(results), "mode": "name"}

    # mode == "content" (grep)
    glob_filter = args.get("glob", "*")
    ignore_case = args.get("ignore_case", False)
    flags = re.IGNORECASE if ignore_case else 0
    try:
        regex = re.compile(pattern, flags)
    except re.error as e:
        return {"error": f"Invalid regex: {e}"}

    matches: list[dict[str, Any]] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        for filename in filenames:
            if not fnmatch.fnmatch(filename, glob_filter):
                continue
            full_path = os.path.join(dirpath, filename)
            rel = os.path.relpath(full_path, workspace_path)
            try:
                with open(full_path, encoding="utf-8", errors="replace") as f:
                    for line_num, line in enumerate(f, 1):
                        if regex.search(line):
                            matches.append(
                                {
                                    "file": rel,
                                    "line": line_num,
                                    "text": line.rstrip()[:200],
                                }
                            )
                            if len(matches) >= max_results:
                                return {
                                    "matches": matches,
                                    "truncated": True,
                                    "count": len(matches),
                                    "mode": "content",
                                }
            except (OSError, UnicodeDecodeError):
                continue

    return {"matches": matches, "truncated": False, "count": len(matches), "mode": "content"}
