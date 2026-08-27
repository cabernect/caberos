"""Backup service — create, list, restore, delete restore points.

Pure business logic for managing CaberOS data backups.
The API layer in `api/data.py` calls these functions; this module
has no FastAPI dependencies.

v0.1.3 Trust Bundle: automatic backups and restore points.
"""

import hashlib
import json
import logging
import re
import shutil
from pathlib import Path

from ..config import settings
from ._utils import check_db_integrity, get_app_version

log = logging.getLogger("agentos.services.backups")

# Maximum retention for automatic backups.
BACKUP_RETENTION = 5


def backups_dir() -> Path:
    """Return the backups directory under the app data dir."""
    db_path = Path(settings.db_path)
    return db_path.parent / "backups"


def _sha256(path: Path) -> str:
    """Compute SHA-256 of a file."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def create_backup(label: str = "pre_import") -> Path | None:
    """Create a restore point before a destructive operation.

    Copies DB, secret key, agent homes, and workspaces into a timestamped
    directory under <data_dir>/backups/. Returns the backup path or None
    if there's nothing to back up.
    """
    from datetime import UTC, datetime

    backup_root = backups_dir()
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    backup_dir = backup_root / f"{timestamp}_{label}"
    backup_dir.mkdir(parents=True, exist_ok=True)

    manifest: dict = {
        "version": get_app_version(),
        "created_at": timestamp,
        "label": label,
        "files": {},
        "db_integrity": None,
    }

    # Backup DB
    db_path = Path(settings.db_path)
    if db_path.exists():
        integrity = check_db_integrity(db_path)
        manifest["db_integrity"] = integrity
        if integrity == "ok":
            dst = backup_dir / "agentos.db"
            shutil.copy2(db_path, dst)
            manifest["files"]["agentos.db"] = {
                "sha256": _sha256(dst),
                "size": dst.stat().st_size,
            }
        # Remove stale WAL/SHM from backup (they're part of the live DB state)
        for suffix in ("-wal", "-shm"):
            stale = backup_dir / f"agentos.db{suffix}"
            if stale.exists():
                stale.unlink()

    # Backup secret key
    key_path = Path(settings.secret_key_path)
    if key_path.exists():
        dst = backup_dir / "secret.key"
        shutil.copy2(key_path, dst)
        manifest["files"]["secret.key"] = {
            "sha256": _sha256(dst),
            "size": dst.stat().st_size,
        }

    # Backup agent home dirs
    agent_home = Path(settings.agent_home_root)
    if agent_home.exists():
        agents_dst = backup_dir / "agents"
        shutil.copytree(agent_home, agents_dst, dirs_exist_ok=True)

    # Backup workspaces
    ws_root = Path(settings.workspace_root)
    if ws_root.exists():
        ws_dst = backup_dir / "workspaces"
        shutil.copytree(ws_root, ws_dst, dirs_exist_ok=True)

    # Write manifest
    (backup_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))

    # Enforce retention
    enforce_backup_retention()

    log.info("Created backup: %s", backup_dir)
    return backup_dir


def enforce_backup_retention(retention: int = BACKUP_RETENTION) -> None:
    """Keep only the latest N backups, delete older ones."""
    backup_root = backups_dir()
    if not backup_root.exists():
        return
    backups = sorted(
        [d for d in backup_root.iterdir() if d.is_dir()],
        key=lambda d: d.name,
        reverse=True,
    )
    for old in backups[retention:]:
        shutil.rmtree(old, ignore_errors=True)
        log.info("Removed old backup: %s", old)


def list_backups() -> list[dict]:
    """List all restore points with manifest info."""
    backup_root = backups_dir()
    if not backup_root.exists():
        return []
    backups = []
    for d in sorted(backup_root.iterdir(), key=lambda d: d.name, reverse=True):
        if not d.is_dir():
            continue
        manifest_path = d / "manifest.json"
        manifest = {}
        if manifest_path.exists():
            try:
                manifest = json.loads(manifest_path.read_text())
            except (json.JSONDecodeError, OSError):
                pass
        backups.append(
            {
                "name": d.name,
                "path": str(d),
                "created_at": manifest.get("created_at", ""),
                "label": manifest.get("label", ""),
                "version": manifest.get("version", "unknown"),
                "db_integrity": manifest.get("db_integrity"),
                "files": manifest.get("files", {}),
            }
        )
    return backups


def _backup_path(backup_name: str) -> Path:
    """Resolve a backup name to a direct child of the backups directory."""
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", backup_name):
        raise FileNotFoundError("Backup not found")
    root = backups_dir().resolve()
    candidate = (root / backup_name).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as error:
        raise FileNotFoundError("Backup not found") from error
    return candidate


def restore_backup(backup_name: str) -> dict:
    """Restore from a named backup directory.

    The caller must dispose the DB engine before calling this.
    """
    backup_dir = _backup_path(backup_name)
    if not backup_dir.exists() or not backup_dir.is_dir():
        raise FileNotFoundError("Backup not found")

    manifest_path = backup_dir / "manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError("Backup manifest not found")

    manifest = json.loads(manifest_path.read_text())

    # Restore DB
    src_db = backup_dir / "agentos.db"
    if src_db.exists():
        tgt_db = Path(settings.db_path)
        # Remove stale WAL/SHM before restoring
        for suffix in ("-wal", "-shm"):
            stale = tgt_db.parent / f"agentos.db{suffix}"
            if stale.exists():
                stale.unlink()
        shutil.copy2(src_db, tgt_db)

    # Restore secret key
    src_key = backup_dir / "secret.key"
    if src_key.exists():
        shutil.copy2(src_key, Path(settings.secret_key_path))

    # Restore agent home dirs
    src_agents = backup_dir / "agents"
    if src_agents.exists():
        tgt_agents = Path(settings.agent_home_root)
        if tgt_agents.exists():
            shutil.rmtree(tgt_agents)
        shutil.copytree(src_agents, tgt_agents)

    # Restore workspaces
    src_ws = backup_dir / "workspaces"
    if src_ws.exists():
        tgt_ws = Path(settings.workspace_root)
        if tgt_ws.exists():
            shutil.rmtree(tgt_ws)
        shutil.copytree(src_ws, tgt_ws)

    log.info("Restored backup: %s", backup_dir)
    return {
        "status": "ok",
        "restored_from": backup_name,
        "manifest": manifest,
        "message": "Backup restored. Restart the server for changes to take effect.",
    }


def delete_backup(backup_name: str) -> dict:
    """Delete a named backup directory."""
    backup_dir = _backup_path(backup_name)
    if not backup_dir.exists() or not backup_dir.is_dir():
        raise FileNotFoundError("Backup not found")
    shutil.rmtree(backup_dir)
    return {"status": "ok", "deleted": backup_name}
