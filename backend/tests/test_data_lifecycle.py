from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from agentos.api.data import DeleteAllDataRequest, delete_all_data
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


@pytest.mark.asyncio
async def test_delete_all_endpoint_reseeds_default_agents():
    with (
        patch("agentos.db.engine", SimpleNamespace(dispose=AsyncMock())),
        patch("agentos.db.init_db", new_callable=AsyncMock),
        patch("agentos.seed.seed_operator_if_needed", new_callable=AsyncMock),
        patch("agentos.seed.seed_default_agents", new_callable=AsyncMock) as seed_agents,
        patch("agentos.api.data.delete_all_local_data"),
    ):
        result = await delete_all_data(DeleteAllDataRequest(confirmation="DELETE ALL DATA"), None)

    assert result == {"status": "deleted", "requires_relogin": True}
    seed_agents.assert_awaited_once()
