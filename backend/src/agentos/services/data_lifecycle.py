"""Explicit local data lifecycle operations."""

import shutil
from pathlib import Path

from ..config import settings


class DataResetError(ValueError):
    pass


def _check_path(path: Path) -> Path:
    resolved = path.expanduser().resolve()
    if resolved in {Path("/"), Path.home().resolve()}:
        raise DataResetError("Refusing to delete a protected directory")
    return resolved


def delete_all_local_data() -> None:
    if settings.database_url:
        raise DataResetError("Delete all data is only available for local SQLite storage")

    db_path = _check_path(Path(settings.db_path))
    data_root = _check_path(db_path.parent)
    targets = {
        db_path,
        Path(f"{db_path}-wal"),
        Path(f"{db_path}-shm"),
        _check_path(Path(settings.secret_key_path)),
        _check_path(Path(settings.workspace_root)),
        _check_path(Path(settings.knowledge_root)),
        _check_path(Path(settings.agent_home_root)),
        data_root / "backups",
    }
    for target in targets:
        if target.is_dir():
            shutil.rmtree(target)
        elif target.exists():
            target.unlink()

    data_root.mkdir(parents=True, exist_ok=True)
    Path(settings.workspace_root).mkdir(parents=True, exist_ok=True)
    Path(settings.knowledge_root).mkdir(parents=True, exist_ok=True)
    Path(settings.agent_home_root).mkdir(parents=True, exist_ok=True)
