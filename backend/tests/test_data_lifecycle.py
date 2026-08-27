from pathlib import Path

import pytest

from agentos.config import settings
from agentos.services.data_lifecycle import DataResetError, delete_all_local_data


def test_delete_all_local_data_clears_local_paths(monkeypatch, tmp_path: Path):
    data_root = tmp_path / "data"
    db_path = data_root / "agentos.db"
    secret_path = data_root / "secret.key"
    workspace = data_root / "workspaces"
    knowledge = data_root / "knowledge"
    agents = data_root / "agents"
    backups = data_root / "backups"
    for directory in (workspace, knowledge, agents, backups):
        directory.mkdir(parents=True)
        (directory / "content").write_text("data")
    db_path.write_text("db")
    secret_path.write_text("secret")

    monkeypatch.setattr(settings, "database_url", "")
    monkeypatch.setattr(settings, "db_path", db_path)
    monkeypatch.setattr(settings, "secret_key_path", secret_path)
    monkeypatch.setattr(settings, "workspace_root", workspace)
    monkeypatch.setattr(settings, "knowledge_root", knowledge)
    monkeypatch.setattr(settings, "agent_home_root", agents)

    delete_all_local_data()

    assert not db_path.exists()
    assert not secret_path.exists()
    assert workspace.is_dir()
    assert knowledge.is_dir()
    assert agents.is_dir()
    assert not backups.exists()


def test_delete_all_local_data_rejects_postgres(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "database_url", "postgresql+asyncpg://localhost/caberos")
    monkeypatch.setattr(settings, "db_path", tmp_path / "agentos.db")
    with pytest.raises(DataResetError, match="local SQLite"):
        delete_all_local_data()
