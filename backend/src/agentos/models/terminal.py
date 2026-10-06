"""TerminalSession — persisted metadata for background terminal processes.

The process itself lives only in memory; this row is the durable record so a
gateway restart can reconcile orphaned `running` rows to `interrupted` and the
UI can show terminal history after the in-memory entry is gone.
"""

from sqlalchemy import DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, IdMixin


class TerminalSession(IdMixin, Base):
    __tablename__ = "terminal_sessions"

    agent_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    session_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    run_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    workspace_path: Mapped[str] = mapped_column(String(512), nullable=False)
    process_group_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # running | completed | failed | timeout | closed | interrupted
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="running")
    command: Mapped[str] = mapped_column(String(2048), nullable=False, default="")
    stdout_path: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    stderr_path: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    stdout_bytes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    stderr_bytes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    truncated: Mapped[bool] = mapped_column(nullable=False, default=False)
    exit_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    started_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True), nullable=True)
