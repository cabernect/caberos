"""Local filesystem browsing for folder pickers.

The web dashboard can't open a native directory dialog, so this operator-
authenticated endpoint lists *directory names only* — never file names or
contents. Used to attach existing folders as agent workspaces.
"""

import os
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query

from ..auth import require_operator
from ..models.operator import Operator

router = APIRouter(prefix="/api/fs", tags=["fs"])

_MAX_ENTRIES = 500


@router.get("/directories")
async def list_directories(
    operator: Operator = Depends(require_operator),
    path: str | None = None,
    hidden: bool = Query(default=False),
) -> dict:
    """List subdirectories of ``path`` (default: home), canonicalized."""
    try:
        root = Path(path).expanduser() if path else Path.home()
        resolved = Path(os.path.realpath(root))
    except OSError as error:
        raise HTTPException(status_code=400, detail="Path cannot be resolved") from error
    if not resolved.exists():
        raise HTTPException(status_code=404, detail="Folder does not exist")
    if not resolved.is_dir():
        raise HTTPException(status_code=400, detail="Path is not a folder")
    try:
        entries = []
        truncated = False
        with os.scandir(resolved) as scan:
            for entry in scan:
                if len(entries) >= _MAX_ENTRIES:
                    truncated = True
                    break
                if not hidden and entry.name.startswith("."):
                    continue
                try:
                    if entry.is_dir(follow_symlinks=True):
                        entries.append({"name": entry.name, "path": str(resolved / entry.name)})
                except OSError:
                    continue
    except PermissionError as error:
        raise HTTPException(status_code=403, detail="Folder is not readable") from error
    entries.sort(key=lambda e: e["name"].lower())
    parent = str(resolved.parent) if resolved.parent != resolved else None
    return {
        "path": str(resolved),
        "parent": parent,
        "directories": entries,
        "truncated": truncated,
    }
