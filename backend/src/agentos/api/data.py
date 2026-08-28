"""Data export/import API — migrate data between web and desktop instances.

GET  /api/data/export  — download a ZIP with DB + agent dirs + workspaces
POST /api/data/import  — upload a ZIP; mode=replace (wipe+restore) or merge
POST /api/data/preview — preview archive contents without importing

Backup endpoints:
GET    /api/data/backups                  — list restore points
POST   /api/data/backups                  — create a restore point
POST   /api/data/backups/{name}/restore   — restore from a backup
DELETE /api/data/backups/{name}           — delete a backup

All business logic lives in `services/migration.py` and `services/backups.py`.
This module contains only FastAPI route handlers.

v0.1.3 Trust Bundle: atomic, integrity-checked migration with automatic backups.
"""

import io
import zipfile
from datetime import datetime

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from ..auth import require_operator
from ..models.operator import Operator
from ..services.backups import create_backup, delete_backup, list_backups, restore_backup
from ..services.data_lifecycle import DataResetError, delete_all_local_data
from ..services.migration import (
    do_merge,
    do_replace_validated,
    export_archive_bytes,
    preview_archive,
    validate_archive,
)

router = APIRouter(prefix="/api/data", tags=["data"])


class DeleteAllDataRequest(BaseModel):
    confirmation: str


@router.get("/export")
async def export_data(
    operator: Operator = Depends(require_operator),
) -> StreamingResponse:
    """Export all CaberOS data as a ZIP archive.

    Includes:
    - agentos.db (SQLite database)
    - secret.key (Fernet key for decrypting credentials)
    - agents/ (agent home dirs with MEMORY.md, per-agent skills)
    - workspaces/ (workspace files, attachments)

    Refuses to export if the source database fails integrity_check.
    """
    try:
        archive_bytes = export_archive_bytes()
    except ValueError as e:
        raise HTTPException(status_code=400, detail="Data export failed") from e

    buf = io.BytesIO(archive_bytes)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"caberos-backup-{timestamp}.zip"

    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/preview")
async def preview_data(
    file: UploadFile = File(...),
    operator: Operator = Depends(require_operator),
) -> dict:
    """Preview what's in an archive without importing.

    Returns counts of agents, providers, MCP servers, sessions, messages,
    etc. in the archive, plus what would be added vs skipped in merge mode.
    Also reports database integrity and schema compatibility.
    """
    if not file.filename or not file.filename.endswith(".zip"):
        raise HTTPException(status_code=400, detail="File must be a .zip archive")

    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Empty file")

    try:
        preview = preview_archive(io.BytesIO(content))
    except zipfile.BadZipFile:
        raise HTTPException(status_code=400, detail="Invalid ZIP file")
    except KeyError:
        raise HTTPException(
            status_code=400,
            detail="ZIP must contain agentos.db at the root",
        )

    preview["db_integrity"] = "ok" if preview.get("db_integrity") == "ok" else "failed"
    return preview


@router.post("/import")
async def import_data(
    file: UploadFile = File(...),
    mode: str = Form("replace"),
    operator: Operator = Depends(require_operator),
) -> dict:
    """Import a ZIP archive.

    mode=replace (default): Wipe and restore all data from the archive.
    mode=merge: Keep existing data, add new rows from the archive.
               Encrypted credentials only work if secret keys match.

    Both modes create an automatic backup before modifying data.
    Replace mode validates the archive DB integrity before swapping.
    """
    if mode not in ("replace", "merge"):
        raise HTTPException(status_code=400, detail="mode must be 'replace' or 'merge'")

    if not file.filename or not file.filename.endswith(".zip"):
        raise HTTPException(status_code=400, detail="File must be a .zip archive")

    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Empty file")

    # Validate the archive before doing anything
    is_valid, error = validate_archive(io.BytesIO(content))
    if not is_valid:
        raise HTTPException(status_code=400, detail=error)

    zf = zipfile.ZipFile(io.BytesIO(content))
    names = zf.namelist()

    if mode == "replace":
        # Stop the DB engine so we can replace the file
        from ..db import engine

        await engine.dispose()
        try:
            return do_replace_validated(zf, names)
        except (ValueError, OSError) as e:
            raise HTTPException(status_code=400, detail="Data import failed") from e
    else:
        try:
            return do_merge(zf, names)
        except (ValueError, OSError) as e:
            raise HTTPException(status_code=400, detail="Data import failed") from e


@router.post("/delete-all")
async def delete_all_data(
    request: DeleteAllDataRequest,
    _operator: Operator = Depends(require_operator),
) -> dict:
    if request.confirmation != "DELETE ALL DATA":
        raise HTTPException(status_code=400, detail="Type DELETE ALL DATA to confirm")

    from ..db import engine, init_db
    from ..seed import seed_default_agents, seed_operator_if_needed

    await engine.dispose()
    try:
        delete_all_local_data()
        await init_db()
        await seed_operator_if_needed()
        await seed_default_agents()
    except DataResetError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except OSError as error:
        raise HTTPException(status_code=500, detail="Could not delete all local data") from error
    return {"status": "deleted", "requires_relogin": True}


# --- Backup / restore point endpoints ---


@router.get("/backups")
async def list_backups_endpoint(
    operator: Operator = Depends(require_operator),
) -> dict:
    """List all restore points."""
    return {"status": "ok", "backups": list_backups()}


@router.post("/backups")
async def create_backup_endpoint(
    operator: Operator = Depends(require_operator),
    label: str = Form("manual"),
) -> dict:
    """Create a restore point manually."""
    backup_dir = create_backup(label=label)
    if backup_dir is None:
        raise HTTPException(status_code=404, detail="No data found to backup")
    return {"status": "ok", "backup": backup_dir.name, "message": "Backup created."}


@router.post("/backups/{backup_name}/restore")
async def restore_backup_endpoint(
    backup_name: str,
    operator: Operator = Depends(require_operator),
) -> dict:
    """Restore from a named backup. The DB engine is disposed first."""
    from ..db import engine

    await engine.dispose()
    try:
        return restore_backup(backup_name)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail="Backup not found") from e


@router.delete("/backups/{backup_name}")
async def delete_backup_endpoint(
    backup_name: str,
    operator: Operator = Depends(require_operator),
) -> dict:
    """Delete a named backup."""
    try:
        return delete_backup(backup_name)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail="Backup not found") from e
