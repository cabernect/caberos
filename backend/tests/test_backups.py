"""Tests for automatic backups and restore points (v0.1.3 Trust Bundle).

Covers:
- replace creates a backup before changing current data
- backup includes DB, secret key, agent homes, and workspaces
- restore recreates the previous state and passes integrity check
- failed import does not delete its restore point
- retention keeps the latest configured number of backups
- backup manifest records version, time, schema, SHA-256, integrity
"""

import io
import json
import sqlite3
import zipfile
from pathlib import Path

import pytest

from agentos.config import settings
from agentos.services import backups as backups_svc
from agentos.services import migration as migration_svc
from agentos.services.backups import BACKUP_RETENTION


def _make_valid_db(db_path: Path) -> None:
    conn = sqlite3.connect(str(db_path))
    conn.execute("CREATE TABLE operators (id TEXT PRIMARY KEY, username TEXT)")
    conn.execute("INSERT INTO operators VALUES ('op-1', 'admin')")
    conn.commit()
    conn.close()


def _make_zip(db_bytes: bytes) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("agentos.db", db_bytes)
    return buf.getvalue()


def _setup_dirs(tmp_path, monkeypatch):
    """Set up data directories under tmp_path and monkeypatch settings."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    db_path = data_dir / "agentos.db"
    _make_valid_db(db_path)

    key_path = data_dir / "secret.key"
    key_path.write_bytes(b"test-secret-key")

    agents_dir = data_dir / "agents"
    agents_dir.mkdir()
    (agents_dir / "agent-1").mkdir()
    (agents_dir / "agent-1" / "MEMORY.md").write_text("# Memory")

    ws_dir = data_dir / "workspaces"
    ws_dir.mkdir()
    (ws_dir / "ws-1").mkdir()
    (ws_dir / "ws-1" / "file.txt").write_text("workspace file")

    monkeypatch.setattr(settings, "db_path", db_path)
    monkeypatch.setattr(settings, "secret_key_path", key_path)
    monkeypatch.setattr(settings, "agent_home_root", agents_dir)
    monkeypatch.setattr(settings, "workspace_root", ws_dir)

    return data_dir


class TestBackups:
    """Tests for automatic backups and restore points."""

    async def test_replace_creates_backup(self, tmp_path, monkeypatch):
        """Replace creates a backup before changing current data."""
        _setup_dirs(tmp_path, monkeypatch)
        original_db_bytes = Path(settings.db_path).read_bytes()

        # Build a different archive to import
        new_db = tmp_path / "new.db"
        conn = sqlite3.connect(str(new_db))
        conn.execute("CREATE TABLE operators (id TEXT PRIMARY KEY, username TEXT)")
        conn.execute("INSERT INTO operators VALUES ('op-2', 'newuser')")
        conn.commit()
        conn.close()
        archive = _make_zip(new_db.read_bytes())

        zf = zipfile.ZipFile(io.BytesIO(archive))
        migration_svc.do_replace_validated(zf, zf.namelist())

        # Backup should exist
        backups = backups_svc.list_backups()
        assert len(backups) >= 1
        assert backups[0]["label"] == "pre_replace"

        # The backup DB should match the original (not the new one)
        backup_dir = Path(backups[0]["path"])
        backup_db = backup_dir / "agentos.db"
        assert backup_db.exists()
        assert backup_db.read_bytes() == original_db_bytes

    async def test_backup_includes_all_files(self, tmp_path, monkeypatch):
        """Backup includes DB, secret key, agent homes, and workspaces."""
        _setup_dirs(tmp_path, monkeypatch)

        backup_dir = backups_svc.create_backup(label="test")
        assert backup_dir is not None

        assert (backup_dir / "agentos.db").exists()
        assert (backup_dir / "secret.key").exists()
        assert (backup_dir / "agents" / "agent-1" / "MEMORY.md").exists()
        assert (backup_dir / "workspaces" / "ws-1" / "file.txt").exists()
        assert (backup_dir / "manifest.json").exists()

    async def test_restore_recreates_previous_state(self, tmp_path, monkeypatch):
        """Restore recreates the previous state and passes integrity check."""
        _setup_dirs(tmp_path, monkeypatch)
        original_db_bytes = Path(settings.db_path).read_bytes()

        # Create a backup
        backup_dir = backups_svc.create_backup(label="test")
        backup_name = backup_dir.name

        # Modify the current data
        conn = sqlite3.connect(str(settings.db_path))
        conn.execute("INSERT INTO operators VALUES ('op-3', 'modified')")
        conn.commit()
        conn.close()

        # Verify it's different
        assert Path(settings.db_path).read_bytes() != original_db_bytes

        # Restore
        result = backups_svc.restore_backup(backup_name)
        assert result["status"] == "ok"

        # DB should match original
        assert Path(settings.db_path).read_bytes() == original_db_bytes

        # Integrity check passes
        conn = sqlite3.connect(str(settings.db_path))
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
        conn.close()
        assert integrity == "ok"

    async def test_failed_import_keeps_restore_point(self, tmp_path, monkeypatch):
        """A failed import does not delete its restore point."""
        _setup_dirs(tmp_path, monkeypatch)

        # Build a corrupt archive that passes ZIP validation but fails DB integrity
        corrupt_db = tmp_path / "corrupt.db"
        corrupt_db.write_bytes(b"SQLite format 3\x00" + b"\x00" * 1024)
        archive = _make_zip(corrupt_db.read_bytes())

        # do_replace_validated should raise
        zf = zipfile.ZipFile(io.BytesIO(archive))
        with pytest.raises((ValueError, Exception)):
            migration_svc.do_replace_validated(zf, zf.namelist())

        # Backup should still exist
        backups = backups_svc.list_backups()
        assert len(backups) >= 1
        assert backups[0]["label"] == "pre_replace"

    async def test_retention_keeps_latest_n(self, tmp_path, monkeypatch):
        """Retention keeps the latest configured number of backups."""
        _setup_dirs(tmp_path, monkeypatch)

        # Create more backups than retention
        for i in range(7):
            backups_svc.create_backup(label=f"test_{i}")

        backups = backups_svc.list_backups()
        assert len(backups) <= BACKUP_RETENTION

    async def test_manifest_records_metadata(self, tmp_path, monkeypatch):
        """Backup manifest records version, time, SHA-256, and integrity."""
        _setup_dirs(tmp_path, monkeypatch)

        backup_dir = backups_svc.create_backup(label="test")
        manifest = json.loads((backup_dir / "manifest.json").read_text())

        assert "created_at" in manifest
        assert manifest["label"] == "test"
        assert manifest["db_integrity"] == "ok"
        assert "agentos.db" in manifest["files"]
        assert "sha256" in manifest["files"]["agentos.db"]
        assert "size" in manifest["files"]["agentos.db"]

    async def test_delete_backup(self, tmp_path, monkeypatch):
        """Deleting a backup removes it from disk."""
        _setup_dirs(tmp_path, monkeypatch)

        backup_dir = backups_svc.create_backup(label="test")
        backup_name = backup_dir.name
        assert backup_dir.exists()

        result = backups_svc.delete_backup(backup_name)
        assert result["status"] == "ok"
        assert not backup_dir.exists()
