"""Explicit local data lifecycle operations."""

import shutil
from collections.abc import Sequence
from pathlib import Path

from sqlalchemy import bindparam, delete, text
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..models.approval import ApprovalRequest
from ..models.audit import AuditRecord
from ..models.elicitation import ElicitationRequest
from ..models.execution_manifest import ExecutionManifest
from ..models.model_call import ModelCall
from ..models.run import Message, Run
from ..models.source import RunSource
from ..models.web_source import WebSource


class DataResetError(ValueError):
    pass


async def delete_runs(db: AsyncSession, run_ids: Sequence[str]) -> int:
    """Delete runs plus every FK'd child and index row. Returns runs deleted.

    Every run child is FK'd NO ACTION (SQLite foreign_keys=ON), so all
    children must go before the run rows or the delete raises
    IntegrityError. `messages_fts` is a standalone FTS5 index with no FK —
    rows must be removed explicitly or they ghost into recall results.

    Shared by session deletion, agent deletion, and retention sweeps —
    any caller purging runs. The caller owns the commit.
    """
    if not run_ids:
        return 0
    # web_sources FKs both messages.id and runs.id; run_id covers all rows
    await db.execute(delete(WebSource).where(WebSource.run_id.in_(run_ids)))
    await db.execute(delete(Message).where(Message.run_id.in_(run_ids)))
    await db.execute(delete(AuditRecord).where(AuditRecord.run_id.in_(run_ids)))
    await db.execute(delete(ApprovalRequest).where(ApprovalRequest.run_id.in_(run_ids)))
    await db.execute(delete(ElicitationRequest).where(ElicitationRequest.run_id.in_(run_ids)))
    await db.execute(delete(ExecutionManifest).where(ExecutionManifest.run_id.in_(run_ids)))
    await db.execute(delete(ModelCall).where(ModelCall.run_id.in_(run_ids)))
    await db.execute(delete(RunSource).where(RunSource.run_id.in_(run_ids)))
    if not settings.database_url:
        # SQLite-only FTS5 index — not FK-constrained, absent on Postgres
        await db.execute(
            text("DELETE FROM messages_fts WHERE run_id IN :ids").bindparams(
                bindparam("ids", expanding=True)
            ),
            {"ids": list(run_ids)},
        )
    result = await db.execute(delete(Run).where(Run.id.in_(run_ids)))
    return result.rowcount or 0


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
