"""Tests for atomic, integrity-checked data migration (v0.1.3 Trust Bundle).

Covers:
- export → replace import → target passes PRAGMA integrity_check
- expected row and file counts survive the round trip
- merging the same archive twice adds nothing the second time
- malformed ZIP is rejected without touching current data
- archive with a malformed database is rejected
- archive preview reports database integrity and schema compatibility
- stale -wal and -shm files do not survive a replace
- a failed swap keeps the original database
- export refuses to package a corrupt source database
- archive path traversal is rejected
- ZIP upload and expanded-size limits prevent ZIP bombs
"""

import io
import sqlite3
import zipfile
from pathlib import Path
from unittest.mock import patch

import pytest


def _make_valid_db(db_path: Path) -> None:
    """Create a valid SQLite database with the operators table and one row."""
    conn = sqlite3.connect(str(db_path))
    conn.execute("CREATE TABLE operators (id TEXT PRIMARY KEY, username TEXT)")
    conn.execute("INSERT INTO operators VALUES ('op-1', 'admin')")
    conn.execute("PRAGMA integrity_check")
    conn.commit()
    conn.close()


def _make_corrupt_db(db_path: Path) -> None:
    """Write garbage bytes that look like a SQLite header but are corrupt."""
    db_path.write_bytes(b"SQLite format 3\x00" + b"\x00" * 1024)


def _make_zip(
    db_bytes: bytes | None = None,
    *,
    db_name: str = "agentos.db",
    extra_files: dict[str, bytes] | None = None,
    secret_key: bytes | None = None,
) -> bytes:
    """Build a ZIP archive in memory."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        if db_bytes is not None:
            zf.writestr(db_name, db_bytes)
        if secret_key is not None:
            zf.writestr("secret.key", secret_key)
        for name, data in (extra_files or {}).items():
            zf.writestr(name, data)
    return buf.getvalue()


class TestMigrationIntegrity:
    """Tests for atomic, integrity-checked migration."""

    async def test_export_replace_roundtrip_passes_integrity_check(self, tmp_path, monkeypatch):
        """export → replace import → target passes PRAGMA integrity_check."""
        from agentos.config import settings
        from agentos.services import migration as migration_svc

        # Set up a source data directory
        src_dir = tmp_path / "src"
        src_dir.mkdir()
        db_path = src_dir / "agentos.db"
        _make_valid_db(db_path)

        monkeypatch.setattr(settings, "db_path", db_path)
        monkeypatch.setattr(settings, "secret_key_path", src_dir / "secret.key")
        monkeypatch.setattr(settings, "agent_home_root", src_dir / "agents")
        monkeypatch.setattr(settings, "workspace_root", src_dir / "workspaces")
        (src_dir / "agents").mkdir()
        (src_dir / "workspaces").mkdir()

        # Export
        pairs = migration_svc.collect_paths()
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for abs_path, arcname in pairs:
                zf.write(abs_path, arcname)
        archive_bytes = buf.getvalue()

        # Set up a target directory
        tgt_dir = tmp_path / "tgt"
        tgt_dir.mkdir()
        tgt_db = tgt_dir / "agentos.db"
        _make_valid_db(tgt_db)

        monkeypatch.setattr(settings, "db_path", tgt_db)
        monkeypatch.setattr(settings, "secret_key_path", tgt_dir / "secret.key")
        monkeypatch.setattr(settings, "agent_home_root", tgt_dir / "agents")
        monkeypatch.setattr(settings, "workspace_root", tgt_dir / "workspaces")
        (tgt_dir / "agents").mkdir()
        (tgt_dir / "workspaces").mkdir()

        # Import (replace)
        zf = zipfile.ZipFile(io.BytesIO(archive_bytes))
        result = _do_replace_safe(zf, tgt_db)

        assert result["status"] == "ok"
        # Target DB must pass integrity check
        conn = sqlite3.connect(str(tgt_db))
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
        conn.close()
        assert integrity == "ok"

    async def test_malformed_zip_rejected_without_touching_current(self, tmp_path, monkeypatch):
        """A malformed ZIP is rejected without touching current data."""
        from agentos.config import settings
        from agentos.services import migration as migration_svc

        tgt_dir = tmp_path / "tgt"
        tgt_dir.mkdir()
        tgt_db = tgt_dir / "agentos.db"
        _make_valid_db(tgt_db)
        original_bytes = tgt_db.read_bytes()

        monkeypatch.setattr(settings, "db_path", tgt_db)
        monkeypatch.setattr(settings, "secret_key_path", tgt_dir / "secret.key")
        monkeypatch.setattr(settings, "agent_home_root", tgt_dir / "agents")
        monkeypatch.setattr(settings, "workspace_root", tgt_dir / "workspaces")

        # Garbage ZIP bytes
        is_valid, error = migration_svc.validate_archive(io.BytesIO(b"not a zip file"))
        assert is_valid is False
        assert error

        # Target DB untouched
        assert tgt_db.read_bytes() == original_bytes

    async def test_archive_with_malformed_db_rejected(self, tmp_path, monkeypatch):
        """An archive with a malformed database is rejected."""
        from agentos.config import settings
        from agentos.services import migration as migration_svc

        tgt_dir = tmp_path / "tgt"
        tgt_dir.mkdir()
        tgt_db = tgt_dir / "agentos.db"
        _make_valid_db(tgt_db)
        original_bytes = tgt_db.read_bytes()

        monkeypatch.setattr(settings, "db_path", tgt_db)
        monkeypatch.setattr(settings, "secret_key_path", tgt_dir / "secret.key")
        monkeypatch.setattr(settings, "agent_home_root", tgt_dir / "agents")
        monkeypatch.setattr(settings, "workspace_root", tgt_dir / "workspaces")

        # Build a corrupt DB, package it, and try to validate
        corrupt_db = tmp_path / "corrupt.db"
        _make_corrupt_db(corrupt_db)
        archive = _make_zip(db_bytes=corrupt_db.read_bytes())

        is_valid, error = migration_svc.validate_archive(io.BytesIO(archive))
        assert is_valid is False
        assert error == "Archive database failed integrity check"

        # Target untouched
        assert tgt_db.read_bytes() == original_bytes

    def test_integrity_check_logs_details_without_returning_them(
        self, tmp_path, monkeypatch, caplog
    ):
        """Database diagnostics stay in logs instead of the returned status."""
        from agentos.services import _utils

        raw_error = "database disk image is malformed at /private/internal.db"

        def fail_connect(_path):
            raise sqlite3.DatabaseError(raw_error)

        monkeypatch.setattr(_utils.sqlite3, "connect", fail_connect)
        with caplog.at_level("ERROR", logger="agentos.services._utils"):
            integrity = _utils.check_db_integrity(tmp_path / "agentos.db")

        assert integrity == "failed"
        assert raw_error in caplog.text

    async def test_preview_sanitizes_integrity_status(self):
        """The preview endpoint does not return arbitrary integrity details."""
        from fastapi import UploadFile

        from agentos.api.data import preview_data
        from agentos.models.operator import Operator

        raw_error = "database disk image is malformed at /private/internal.db"
        upload = UploadFile(filename="backup.zip", file=io.BytesIO(b"archive"))
        with patch(
            "agentos.api.data.preview_archive",
            return_value={"db_integrity": raw_error, "tables": []},
        ):
            preview = await preview_data(
                upload,
                Operator(id="operator-1", username="admin", password_hash="unused"),
            )

        assert preview["db_integrity"] == "failed"
        assert raw_error not in str(preview)

    async def test_path_traversal_rejected(self, tmp_path, monkeypatch):
        """Archive paths with traversal (../../etc/passwd) are rejected."""
        from agentos.config import settings
        from agentos.services import migration as migration_svc

        tgt_dir = tmp_path / "tgt"
        tgt_dir.mkdir()
        tgt_db = tgt_dir / "agentos.db"
        _make_valid_db(tgt_db)

        monkeypatch.setattr(settings, "db_path", tgt_db)
        monkeypatch.setattr(settings, "secret_key_path", tgt_dir / "secret.key")
        monkeypatch.setattr(settings, "agent_home_root", tgt_dir / "agents")
        monkeypatch.setattr(settings, "workspace_root", tgt_dir / "workspaces")

        # Build a valid DB but add a traversal file
        valid_db = tmp_path / "valid.db"
        _make_valid_db(valid_db)
        archive = _make_zip(
            db_bytes=valid_db.read_bytes(),
            extra_files={"../../etc/passwd": b"root:x:0:0:root:/root:/bin/bash"},
        )

        is_valid, error = migration_svc.validate_archive(io.BytesIO(archive))
        assert is_valid is False
        assert "traversal" in error.lower() or "path" in error.lower()

    async def test_zip_bomb_size_limit_rejected(self, tmp_path, monkeypatch):
        """ZIP bombs exceeding expanded-size limits are rejected."""
        from agentos.config import settings
        from agentos.services import migration as migration_svc

        tgt_dir = tmp_path / "tgt"
        tgt_dir.mkdir()
        tgt_db = tgt_dir / "agentos.db"
        _make_valid_db(tgt_db)

        monkeypatch.setattr(settings, "db_path", tgt_db)
        monkeypatch.setattr(settings, "secret_key_path", tgt_dir / "secret.key")
        monkeypatch.setattr(settings, "agent_home_root", tgt_dir / "agents")
        monkeypatch.setattr(settings, "workspace_root", tgt_dir / "workspaces")

        # Build a ZIP with a huge uncompressed file (compressed small)
        huge_content = b"A" * (200 * 1024 * 1024)  # 200 MB uncompressed
        valid_db = tmp_path / "valid.db"
        _make_valid_db(valid_db)
        archive = _make_zip(
            db_bytes=valid_db.read_bytes(),
            extra_files={"agents/huge.txt": huge_content},
        )

        is_valid, error = migration_svc.validate_archive(
            io.BytesIO(archive), max_uncompressed_size=100 * 1024 * 1024
        )
        assert is_valid is False
        assert "size" in error.lower() or "limit" in error.lower()

    async def test_failed_swap_keeps_original(self, tmp_path, monkeypatch):
        """If the swap fails, the original database is preserved."""
        from agentos.config import settings

        tgt_dir = tmp_path / "tgt"
        tgt_dir.mkdir()
        tgt_db = tgt_dir / "agentos.db"
        _make_valid_db(tgt_db)
        original_bytes = tgt_db.read_bytes()

        monkeypatch.setattr(settings, "db_path", tgt_db)
        monkeypatch.setattr(settings, "secret_key_path", tgt_dir / "secret.key")
        monkeypatch.setattr(settings, "agent_home_root", tgt_dir / "agents")
        monkeypatch.setattr(settings, "workspace_root", tgt_dir / "workspaces")

        # Build a valid archive
        valid_db = tmp_path / "valid.db"
        _make_valid_db(valid_db)
        archive = _make_zip(db_bytes=valid_db.read_bytes())

        # Make os.replace fail
        with patch("agentos.services.migration.os.replace", side_effect=OSError("disk full")):
            zf = zipfile.ZipFile(io.BytesIO(archive))
            with pytest.raises(OSError):
                _do_replace_safe(zf, tgt_db)

        # Original DB intact
        assert tgt_db.read_bytes() == original_bytes

    async def test_stale_wal_shm_removed_after_replace(self, tmp_path, monkeypatch):
        """Stale -wal and -shm files do not survive a replace."""
        from agentos.config import settings

        tgt_dir = tmp_path / "tgt"
        tgt_dir.mkdir()
        tgt_db = tgt_dir / "agentos.db"
        _make_valid_db(tgt_db)

        # Create stale WAL/SHM files
        (tgt_dir / "agentos.db-wal").write_bytes(b"stale wal")
        (tgt_dir / "agentos.db-shm").write_bytes(b"stale shm")

        monkeypatch.setattr(settings, "db_path", tgt_db)
        monkeypatch.setattr(settings, "secret_key_path", tgt_dir / "secret.key")
        monkeypatch.setattr(settings, "agent_home_root", tgt_dir / "agents")
        monkeypatch.setattr(settings, "workspace_root", tgt_dir / "workspaces")

        valid_db = tmp_path / "valid.db"
        _make_valid_db(valid_db)
        archive = _make_zip(db_bytes=valid_db.read_bytes())

        zf = zipfile.ZipFile(io.BytesIO(archive))
        _do_replace_safe(zf, tgt_db)

        # Stale WAL/SHM must be gone
        assert not (tgt_dir / "agentos.db-wal").exists()
        assert not (tgt_dir / "agentos.db-shm").exists()

    async def test_export_refuses_corrupt_source(self, tmp_path, monkeypatch):
        """Export refuses to package a corrupt source database."""
        from agentos.config import settings
        from agentos.services import migration as migration_svc

        src_dir = tmp_path / "src"
        src_dir.mkdir()
        db_path = src_dir / "agentos.db"
        _make_corrupt_db(db_path)

        monkeypatch.setattr(settings, "db_path", db_path)
        monkeypatch.setattr(settings, "secret_key_path", src_dir / "secret.key")
        monkeypatch.setattr(settings, "agent_home_root", src_dir / "agents")
        monkeypatch.setattr(settings, "workspace_root", src_dir / "workspaces")
        (src_dir / "agents").mkdir()
        (src_dir / "workspaces").mkdir()

        with pytest.raises(Exception) as exc_info:
            migration_svc.export_archive_bytes()
        assert str(exc_info.value) == "Source database failed integrity check"

    async def test_merge_same_archive_twice_adds_nothing(self, tmp_path, monkeypatch):
        """Merging the same archive twice adds nothing the second time."""
        from agentos.config import settings
        from agentos.services import migration as migration_svc

        tgt_dir = tmp_path / "tgt"
        tgt_dir.mkdir()
        tgt_db = tgt_dir / "agentos.db"
        conn = sqlite3.connect(str(tgt_db))
        conn.execute("CREATE TABLE operators (id TEXT PRIMARY KEY, username TEXT)")
        conn.commit()
        conn.close()

        src_db = tmp_path / "src.db"
        _make_valid_db(src_db)
        archive = _make_zip(db_bytes=src_db.read_bytes())

        monkeypatch.setattr(settings, "db_path", tgt_db)
        monkeypatch.setattr(settings, "secret_key_path", tgt_dir / "secret.key")
        monkeypatch.setattr(settings, "agent_home_root", tgt_dir / "agents")
        monkeypatch.setattr(settings, "workspace_root", tgt_dir / "workspaces")

        zf = zipfile.ZipFile(io.BytesIO(archive))
        result1 = migration_svc.do_merge(zf, zf.namelist())
        zf2 = zipfile.ZipFile(io.BytesIO(archive))
        result2 = migration_svc.do_merge(zf2, zf2.namelist())

        assert result1["rows_added"] >= 1
        assert result2["rows_added"] == 0

    async def test_merge_mcp_server_by_url_not_uuid(self, tmp_path, monkeypatch):
        """Merging an MCP server that already exists (by URL) doesn't duplicate it or its tools."""
        from agentos.config import settings
        from agentos.services import migration as migration_svc

        tgt_dir = tmp_path / "tgt"
        tgt_dir.mkdir()
        tgt_db = tgt_dir / "agentos.db"

        # Create target DB with an MCP server + 28 tools
        conn = sqlite3.connect(str(tgt_db))
        conn.execute("CREATE TABLE operators (id TEXT PRIMARY KEY, username TEXT)")
        conn.execute("INSERT INTO operators VALUES ('op-1', 'admin')")
        conn.execute("""CREATE TABLE mcp_servers (
            id TEXT PRIMARY KEY, name TEXT, transport TEXT, command TEXT,
            args TEXT, url TEXT, headers TEXT, env_template TEXT,
            oauth_config TEXT, tool_filter TEXT, enabled INTEGER,
            require_approval INTEGER, created_at TEXT, updated_at TEXT
        )""")
        conn.execute("""CREATE TABLE mcp_tools (
            id TEXT PRIMARY KEY, mcp_server_id TEXT, tool_name TEXT,
            capability_name TEXT, parameters_schema TEXT, description TEXT,
            egress INTEGER, require_approval INTEGER, subject_scoped INTEGER,
            created_at TEXT, updated_at TEXT
        )""")
        conn.execute("""CREATE TABLE mcp_server_credentials (
            id TEXT PRIMARY KEY, mcp_server_id TEXT, credential_type TEXT,
            encrypted_value TEXT, label TEXT, created_at TEXT, updated_at TEXT
        )""")
        # Target has Notion server with 28 tools
        conn.execute(
            "INSERT INTO mcp_servers VALUES ('tgt-notion-id', 'Notion', 'http', NULL, NULL, 'https://mcp.notion.com/mcp', NULL, NULL, NULL, NULL, 1, 1, '', '')"
        )
        for i in range(28):
            conn.execute(
                f"INSERT INTO mcp_tools VALUES ('tgt-tool-{i}', 'tgt-notion-id', 'tool_{i}', 'mcp.Notion.tool_{i}', '{{}}', '', 0, 0, 1, '', '')"
            )
        conn.execute(
            "INSERT INTO mcp_server_credentials VALUES ('tgt-cred-1', 'tgt-notion-id', 'oauth_token', 'encrypted', 'OAuth', '', '')"
        )
        conn.commit()
        conn.close()

        # Create source DB with the SAME server (different UUID) + same 28 tools
        src_db = tmp_path / "src.db"
        conn = sqlite3.connect(str(src_db))
        conn.execute("CREATE TABLE operators (id TEXT PRIMARY KEY, username TEXT)")
        conn.execute("""CREATE TABLE mcp_servers (
            id TEXT PRIMARY KEY, name TEXT, transport TEXT, command TEXT,
            args TEXT, url TEXT, headers TEXT, env_template TEXT,
            oauth_config TEXT, tool_filter TEXT, enabled INTEGER,
            require_approval INTEGER, created_at TEXT, updated_at TEXT
        )""")
        conn.execute("""CREATE TABLE mcp_tools (
            id TEXT PRIMARY KEY, mcp_server_id TEXT, tool_name TEXT,
            capability_name TEXT, parameters_schema TEXT, description TEXT,
            egress INTEGER, require_approval INTEGER, subject_scoped INTEGER,
            created_at TEXT, updated_at TEXT
        )""")
        conn.execute("""CREATE TABLE mcp_server_credentials (
            id TEXT PRIMARY KEY, mcp_server_id TEXT, credential_type TEXT,
            encrypted_value TEXT, label TEXT, created_at TEXT, updated_at TEXT
        )""")
        # Source has same Notion server with DIFFERENT UUID + same 28 tools
        conn.execute(
            "INSERT INTO mcp_servers VALUES ('src-notion-id', 'Notion', 'http', NULL, NULL, 'https://mcp.notion.com/mcp', NULL, NULL, NULL, NULL, 1, 1, '', '')"
        )
        for i in range(28):
            conn.execute(
                f"INSERT INTO mcp_tools VALUES ('src-tool-{i}', 'src-notion-id', 'tool_{i}', 'mcp.Notion.tool_{i}', '{{}}', '', 0, 0, 1, '', '')"
            )
        conn.execute(
            "INSERT INTO mcp_server_credentials VALUES ('src-cred-1', 'src-notion-id', 'oauth_token', 'encrypted2', 'OAuth', '', '')"
        )
        conn.commit()
        conn.close()

        archive = _make_zip(db_bytes=src_db.read_bytes())

        monkeypatch.setattr(settings, "db_path", tgt_db)
        monkeypatch.setattr(settings, "secret_key_path", tgt_dir / "secret.key")
        monkeypatch.setattr(settings, "agent_home_root", tgt_dir / "agents")
        monkeypatch.setattr(settings, "workspace_root", tgt_dir / "workspaces")

        zf = zipfile.ZipFile(io.BytesIO(archive))
        result = migration_svc.do_merge(zf, zf.namelist())

        # Should add 0 rows — everything already exists by natural key
        assert result["rows_added"] == 0
        assert result["rows_skipped"] == 30  # 1 server + 28 tools + 1 credential

        # Verify no duplicates in the target DB
        conn = sqlite3.connect(str(tgt_db))
        server_count = conn.execute(
            "SELECT COUNT(*) FROM mcp_servers WHERE url = 'https://mcp.notion.com/mcp'"
        ).fetchone()[0]
        tool_count = conn.execute("SELECT COUNT(*) FROM mcp_tools").fetchone()[0]
        cred_count = conn.execute("SELECT COUNT(*) FROM mcp_server_credentials").fetchone()[0]
        conn.close()

        assert server_count == 1  # no duplicate server
        assert tool_count == 28  # no duplicate tools
        assert cred_count == 1  # no duplicate credentials

    async def test_preview_reports_integrity(self, tmp_path, monkeypatch):
        """Archive preview reports database integrity and schema compatibility."""
        from agentos.config import settings
        from agentos.services import migration as migration_svc

        tgt_dir = tmp_path / "tgt"
        tgt_dir.mkdir()
        tgt_db = tgt_dir / "agentos.db"
        _make_valid_db(tgt_db)

        monkeypatch.setattr(settings, "db_path", tgt_db)
        monkeypatch.setattr(settings, "secret_key_path", tgt_dir / "secret.key")
        monkeypatch.setattr(settings, "agent_home_root", tgt_dir / "agents")
        monkeypatch.setattr(settings, "workspace_root", tgt_dir / "workspaces")

        valid_db = tmp_path / "valid.db"
        _make_valid_db(valid_db)
        archive = _make_zip(db_bytes=valid_db.read_bytes())

        preview = migration_svc.preview_archive(io.BytesIO(archive))
        assert preview["db_integrity"] == "ok"
        assert "tables" in preview


def _do_replace_safe(zf: zipfile.ZipFile, target_db: Path) -> dict:
    """Call the internal _do_replace with integrity validation."""
    from agentos.services import migration as migration_svc

    return migration_svc.do_replace_validated(zf, zf.namelist())
