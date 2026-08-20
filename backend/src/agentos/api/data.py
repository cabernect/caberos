"""Data export/import API — migrate data between web and desktop instances.

GET  /api/data/export  — download a ZIP with DB + agent dirs + workspaces
POST /api/data/import  — upload a ZIP; mode=replace (wipe+restore) or merge
"""

import io
import logging
import shutil
import sqlite3
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse

from ..auth import require_operator
from ..config import settings
from ..models.operator import Operator

log = logging.getLogger("agentos.api.data")

router = APIRouter(prefix="/api/data", tags=["data"])

# Tables to merge (row-level INSERT OR IGNORE).
# Excludes SQLite internal tables (sqlite_*) and FTS virtual tables.
# FTS tables are auto-populated from their content tables.
_MERGE_TABLES = [
    "operators",
    "agents",
    "agent_versions",
    "providers",
    "capabilities",
    "sessions",
    "runs",
    "messages",
    "audit_records",
    "approval_requests",
    "elicitation_requests",
    "mcp_servers",
    "mcp_tools",
    "mcp_server_credentials",
    "channel_configs",
    "contacts",
    "memory_triples",
    "memory_fts_data",
    "messages_fts_data",
    "session_summaries_fts_data",
    "alembic_version",
]


def _collect_paths() -> list[tuple[Path, str]]:
    """Collect (absolute_path, archive_path) pairs for export."""
    pairs: list[tuple[Path, str]] = []

    # 1. SQLite database
    db_path = Path(settings.db_path)
    if db_path.exists():
        pairs.append((db_path, "agentos.db"))

    # 2. Secret key (needed to decrypt provider keys, channel tokens, etc.)
    key_path = Path(settings.secret_key_path)
    if key_path.exists():
        pairs.append((key_path, "secret.key"))

    # 3. Agent home dirs (MEMORY.md, per-agent skills, etc.)
    agent_home = Path(settings.agent_home_root)
    if agent_home.exists():
        for item in agent_home.rglob("*"):
            if item.is_file():
                arcname = str(item.relative_to(agent_home.parent))
                pairs.append((item, f"agents/{arcname}"))

    # 4. Workspaces (working files, attachments)
    ws_root = Path(settings.workspace_root)
    if ws_root.exists():
        for item in ws_root.rglob("*"):
            if item.is_file():
                arcname = str(item.relative_to(ws_root.parent))
                pairs.append((item, f"workspaces/{arcname}"))

    return pairs


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
    """
    pairs = _collect_paths()
    if not pairs:
        raise HTTPException(status_code=404, detail="No data found to export")

    # Build the ZIP in memory
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for abs_path, arcname in pairs:
            zf.write(abs_path, arcname)
    buf.seek(0)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"caberos-backup-{timestamp}.zip"

    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _do_replace(zf: zipfile.ZipFile, names: list[str]) -> dict:
    """Replace mode: wipe and restore all data from the archive.

    The caller (async endpoint) must dispose the DB engine before calling this.
    """
    imported: list[str] = []
    for name in names:
        if name.endswith("/"):
            continue
        if name == "agentos.db":
            target = Path(settings.db_path)
        elif name == "secret.key":
            target = Path(settings.secret_key_path)
        elif name.startswith("agents/"):
            rel = name[len("agents/") :]
            target = Path(settings.agent_home_root).parent / rel
        elif name.startswith("workspaces/"):
            rel = name[len("workspaces/") :]
            target = Path(settings.workspace_root).parent / rel
        else:
            log.warning("Skipping unknown file in archive: %s", name)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        with zf.open(name) as src, open(target, "wb") as dst:
            shutil.copyfileobj(src, dst)
        imported.append(name)

    log.info("Replace import: %d files", len(imported))
    return {
        "status": "ok",
        "mode": "replace",
        "imported_files": len(imported),
        "message": "Data replaced. Restart the server for changes to take effect.",
    }


def _do_merge(zf: zipfile.ZipFile, names: list[str]) -> dict:
    """Merge mode: copy rows from the imported DB into the existing one.

    - Database: INSERT OR IGNORE for each table (keeps existing rows, adds new)
    - Secret key: NOT replaced (keep target's key)
    - Agent home dirs: only add files that don't exist (MEMORY.md, etc.)
    - Workspaces: only add files that don't exist
    - Credentials: copied as-is — will only decrypt if secret keys match
    """
    # Extract imported DB to a temp file
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        with zf.open("agentos.db") as src:
            shutil.copyfileobj(src, tmp)
        imported_db_path = tmp.name

    target_db_path = Path(settings.db_path)
    imported_rows = 0
    skipped_rows = 0
    tables_merged: list[str] = []

    try:
        # Attach the imported DB to the target DB and copy rows
        conn = sqlite3.connect(str(target_db_path))
        conn.execute(f"ATTACH DATABASE '{imported_db_path}' AS imported")

        # Get actual tables in the imported DB
        imported_tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM imported.sqlite_master WHERE type='table'"
            ).fetchall()
        }

        for table in _MERGE_TABLES:
            if table not in imported_tables:
                continue
            # Skip FTS virtual tables — they're auto-populated
            if "fts" in table:
                continue

            # Get column list
            cols = [row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()]
            if not cols:
                continue
            col_list = ", ".join(cols)
            placeholders = ", ".join(["?"] * len(cols))

            # Count before
            before = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]

            # INSERT OR IGNORE — keeps existing rows, adds new ones
            try:
                rows = conn.execute(f"SELECT {col_list} FROM imported.{table}").fetchall()
                conn.executemany(
                    f"INSERT OR IGNORE INTO {table} ({col_list}) VALUES ({placeholders})",
                    rows,
                )
                after = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                added = after - before
                imported_rows += added
                skipped_rows += len(rows) - added
                if added > 0:
                    tables_merged.append(f"{table} (+{added})")
            except sqlite3.Error as e:
                log.warning("Merge: skipped table %s: %s", table, e)

        conn.commit()
        conn.close()

        # Merge agent home dirs — only add files that don't exist
        files_added = 0
        for name in names:
            if name.endswith("/") or not (
                name.startswith("agents/") or name.startswith("workspaces/")
            ):
                continue
            if name.startswith("agents/"):
                rel = name[len("agents/") :]
                target = Path(settings.agent_home_root).parent / rel
            else:
                rel = name[len("workspaces/") :]
                target = Path(settings.workspace_root).parent / rel

            if target.exists():
                continue  # keep existing
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(name) as src, open(target, "wb") as dst:
                shutil.copyfileobj(src, dst)
            files_added += 1

        # Check if secret keys match
        key_match = True
        if "secret.key" in names:
            source_key = zf.read("secret.key")
            target_key_path = Path(settings.secret_key_path)
            if target_key_path.exists():
                target_key = target_key_path.read_bytes()
                key_match = source_key == target_key

        log.info(
            "Merge import: %d rows added, %d rows skipped, %d files added",
            imported_rows,
            skipped_rows,
            files_added,
        )

        warnings: list[str] = []
        if not key_match:
            warnings.append(
                "Secret keys differ — imported encrypted credentials (provider keys, "
                "channel tokens) won't decrypt. Re-enter them in the target instance."
            )

        return {
            "status": "ok",
            "mode": "merge",
            "rows_added": imported_rows,
            "rows_skipped": skipped_rows,
            "files_added": files_added,
            "tables_merged": tables_merged,
            "secret_keys_match": key_match,
            "warnings": warnings,
            "message": (
                f"Merged {imported_rows} rows from {len(tables_merged)} tables. "
                + (
                    "Restart the server for changes to take effect."
                    if imported_rows > 0 or files_added > 0
                    else "No new data to merge."
                )
                + (" " + " ".join(warnings) if warnings else "")
            ),
        }
    finally:
        Path(imported_db_path).unlink(missing_ok=True)


@router.post("/preview")
async def preview_data(
    file: UploadFile = File(...),
    operator: Operator = Depends(require_operator),
) -> dict:
    """Preview what's in an archive without importing.

    Returns counts of agents, providers, MCP servers, sessions, messages,
    etc. in the archive, plus what would be added vs skipped in merge mode.
    """
    if not file.filename or not file.filename.endswith(".zip"):
        raise HTTPException(status_code=400, detail="File must be a .zip archive")

    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Empty file")

    try:
        zf = zipfile.ZipFile(io.BytesIO(content))
    except zipfile.BadZipFile:
        raise HTTPException(status_code=400, detail="Invalid ZIP file")

    names = zf.namelist()
    if "agentos.db" not in names:
        raise HTTPException(
            status_code=400,
            detail="ZIP must contain agentos.db at the root",
        )

    # Extract imported DB to a temp file
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        with zf.open("agentos.db") as src:
            shutil.copyfileobj(src, tmp)
        imported_db_path = tmp.name

    # Tables to count and compare
    count_tables = [
        "agents",
        "agent_versions",
        "providers",
        "mcp_servers",
        "mcp_tools",
        "mcp_server_credentials",
        "channel_configs",
        "sessions",
        "runs",
        "messages",
        "contacts",
        "memory_triples",
        "audit_records",
        "approval_requests",
        "elicitation_requests",
        "operators",
    ]

    try:
        target_db_path = Path(settings.db_path)
        conn = sqlite3.connect(str(target_db_path))
        conn.execute(f"ATTACH DATABASE '{imported_db_path}' AS imported")

        table_stats: list[dict] = []
        for table in count_tables:
            # Check if table exists in imported DB
            exists = conn.execute(
                "SELECT name FROM imported.sqlite_master WHERE type='table' AND name=?",
                (table,),
            ).fetchone()
            if not exists:
                continue

            imported_count = conn.execute(f"SELECT COUNT(*) FROM imported.{table}").fetchone()[0]

            # Check if table exists in target DB
            target_exists = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
                (table,),
            ).fetchone()
            target_count = (
                conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] if target_exists else 0
            )

            # For merge mode, count how many would be new (INSERT OR IGNORE)
            # Use the primary key column to detect duplicates
            new_count = imported_count
            if target_exists and imported_count > 0:
                pk_cols = [
                    row[1]
                    for row in conn.execute(f"PRAGMA table_info({table})").fetchall()
                    if row[5]  # pk flag
                ]
                if pk_cols:
                    pk_list = ", ".join(pk_cols)
                    try:
                        new_count = conn.execute(
                            f"SELECT COUNT(*) FROM imported.{table} "
                            f"WHERE ({pk_list}) NOT IN "
                            f"(SELECT {pk_list} FROM {table})"
                        ).fetchone()[0]
                    except sqlite3.Error:
                        new_count = imported_count  # can't determine, assume all new

            table_stats.append(
                {
                    "table": table,
                    "imported_count": imported_count,
                    "target_count": target_count,
                    "new_in_merge": new_count,
                }
            )

        conn.close()
    finally:
        Path(imported_db_path).unlink(missing_ok=True)

    # Count files in archive
    agent_files = [n for n in names if n.startswith("agents/") and not n.endswith("/")]
    workspace_files = [n for n in names if n.startswith("workspaces/") and not n.endswith("/")]
    has_secret_key = "secret.key" in names

    # Check secret key match
    key_match = None
    if has_secret_key:
        source_key = zf.read("secret.key")
        target_key_path = Path(settings.secret_key_path)
        if target_key_path.exists():
            key_match = source_key == target_key_path.read_bytes()

    return {
        "status": "ok",
        "tables": table_stats,
        "agent_files": len(agent_files),
        "workspace_files": len(workspace_files),
        "has_secret_key": has_secret_key,
        "secret_keys_match": key_match,
    }


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
    """
    if mode not in ("replace", "merge"):
        raise HTTPException(status_code=400, detail="mode must be 'replace' or 'merge'")

    if not file.filename or not file.filename.endswith(".zip"):
        raise HTTPException(status_code=400, detail="File must be a .zip archive")

    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Empty file")

    try:
        zf = zipfile.ZipFile(io.BytesIO(content))
    except zipfile.BadZipFile:
        raise HTTPException(status_code=400, detail="Invalid ZIP file")

    names = zf.namelist()
    if "agentos.db" not in names:
        raise HTTPException(
            status_code=400,
            detail="ZIP must contain agentos.db at the root",
        )

    if mode == "replace":
        # Stop the DB engine so we can replace the file
        from ..db import engine

        await engine.dispose()
        return _do_replace(zf, names)
    else:
        return _do_merge(zf, names)
