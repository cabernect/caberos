"""File search capabilities — file.search (grep) and file.glob (find by pattern).

Both operate within the workspace boundary (D29).
"""

import fnmatch
import os
import re
from typing import Any

from ...sandbox.workspace import WorkspaceManager


async def file_search(args: dict[str, Any], workspace_path: str, **_kwargs: Any) -> dict[str, Any]:
    """Search file contents within the workspace (like grep).

    Args:
        pattern: Regular expression or literal string to search for
        path: Directory to search in (default: ".")
        glob: Optional file pattern filter (e.g. "*.py")
        max_results: Maximum number of matches to return (default: 50)
        ignore_case: Case-insensitive search (default: false)
    """
    wm = WorkspaceManager()
    rel_path = args.get("path", ".")
    root = wm.validate_path(workspace_path, rel_path)
    pattern = args["pattern"]
    glob_filter = args.get("glob", "*")
    max_results = args.get("max_results", 50)
    ignore_case = args.get("ignore_case", False)

    flags = re.IGNORECASE if ignore_case else 0
    try:
        regex = re.compile(pattern, flags)
    except re.error as e:
        return {"error": f"Invalid regex: {e}"}

    matches: list[dict[str, Any]] = []
    for dirpath, dirnames, filenames in os.walk(root):
        # Skip hidden directories (e.g. .git, .venv)
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
                            matches.append({
                                "file": rel,
                                "line": line_num,
                                "text": line.rstrip()[:200],  # truncate long lines
                            })
                            if len(matches) >= max_results:
                                return {
                                    "matches": matches,
                                    "truncated": True,
                                    "count": len(matches),
                                }
            except (OSError, UnicodeDecodeError):
                continue  # skip binary/unreadable files

    return {"matches": matches, "truncated": False, "count": len(matches)}


async def file_glob(args: dict[str, Any], workspace_path: str, **_kwargs: Any) -> dict[str, Any]:
    """Find files by name pattern within the workspace (like find/glob).

    Args:
        pattern: Glob pattern (e.g. "*.py", "**/test_*.py", "src/**/*.ts")
        path: Directory to search in (default: ".")
        max_results: Maximum number of files to return (default: 100)
    """
    wm = WorkspaceManager()
    rel_path = args.get("path", ".")
    root = wm.validate_path(workspace_path, rel_path)
    pattern = args["pattern"]
    max_results = args.get("max_results", 100)

    # Normalize the pattern — handle ** for recursive matching
    results: list[str] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        for filename in filenames:
            full_path = os.path.join(dirpath, filename)
            rel = os.path.relpath(full_path, workspace_path)
            # Match against both the relative path and just the filename
            if fnmatch.fnmatch(rel, pattern) or fnmatch.fnmatch(filename, pattern):
                results.append(rel)
                if len(results) >= max_results:
                    return {
                        "files": results,
                        "truncated": True,
                        "count": len(results),
                    }

    return {"files": results, "truncated": False, "count": len(results)}
