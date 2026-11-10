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
    """List subdirectories of ``path`` (default: home), canonicalized.

    Browse scope is jailed to the operator's home directory — the picker is a
    convenience, not a filesystem API. Outside-home workspaces are still
    configured by typing the path into workspace settings.
    """
    base_str = os.path.realpath(Path.home())
    try:
        raw = os.path.normpath(os.path.expanduser(path)) if path else base_str
    except (OSError, RuntimeError, ValueError) as error:
        raise HTTPException(status_code=400, detail="Path cannot be resolved") from error
    if raw != base_str and not raw.startswith(base_str + os.sep):
        raise HTTPException(status_code=403, detail="Path is outside allowed root")
    try:
        resolved = os.path.realpath(raw)
    except (OSError, RuntimeError, ValueError) as error:
        raise HTTPException(status_code=400, detail="Path cannot be resolved") from error
    if resolved != base_str and not resolved.startswith(base_str + os.sep):
        raise HTTPException(status_code=403, detail="Path is outside allowed root")
    if not os.path.exists(resolved):
        raise HTTPException(status_code=404, detail="Folder does not exist")
    if not os.path.isdir(resolved):
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
                        entries.append(
                            {"name": entry.name, "path": os.path.join(resolved, entry.name)}
                        )
                except OSError:
                    continue
    except PermissionError as error:
        raise HTTPException(status_code=403, detail="Folder is not readable") from error
    entries.sort(key=lambda e: e["name"].lower())
    parent = os.path.dirname(resolved)
    if parent == resolved:
        parent = None
    return {
        "path": resolved,
        "parent": parent,
        "directories": entries,
        "truncated": truncated,
    }


@router.post("/pick-directory")
async def pick_directory(
    operator: Operator = Depends(require_operator),
) -> dict:
    """Open the OS-native folder dialog on the operator's machine.

    Best-effort: macOS uses ``choose folder`` (osascript), Linux zenity or
    kdialog, Windows the FolderBrowserDialog. 501 → callers should fall back
    to the server-side directory browser (headless/unsupported platforms).
    """
    import asyncio
    import shutil
    import sys

    if sys.platform == "darwin":
        cmd = [
            "osascript",
            "-e",
            'POSIX path of (choose folder with prompt "Choose workspace folder")',
        ]
    elif sys.platform.startswith("linux"):
        if shutil.which("zenity"):
            cmd = [
                "zenity",
                "--file-selection",
                "--directory",
                "--title=Choose workspace folder",
            ]
        elif shutil.which("kdialog"):
            cmd = ["kdialog", "--getexistingdirectory"]
        else:
            raise HTTPException(
                status_code=501,
                detail="No native picker — install zenity or kdialog",
            )
    elif sys.platform == "win32":
        cmd = [
            "powershell",
            "-NoProfile",
            "-Command",
            "Add-Type -AssemblyName System.Windows.Forms; "
            "$d = New-Object System.Windows.Forms.FolderBrowserDialog; "
            "if ($d.ShowDialog() -eq 'OK') { $d.SelectedPath }",
        ]
    else:
        raise HTTPException(status_code=501, detail="Native picker unsupported on this platform")

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=300)
    except TimeoutError:
        proc.kill()
        raise HTTPException(status_code=408, detail="Folder picker timed out") from None
    picked = out.decode(errors="replace").strip()
    if proc.returncode != 0 or not picked:
        return {"path": None}  # cancelled — not an error
    return {"path": str(Path(os.path.realpath(picked)))}
