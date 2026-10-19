"""Session-close skill reflection activity — one row per pass."""

import json
from datetime import datetime

from sqlalchemy import Index, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import DateTime, Text

from .base import Base, IdMixin, _utcnow


class SkillReflection(Base, IdMixin):
    __tablename__ = "skill_reflections"
    __table_args__ = (
        # One pass per frozen evidence boundary — a restart or duplicate
        # close sees the same fingerprint and claims nothing.
        UniqueConstraint("session_id", "source_fingerprint", name="uq_reflection_scope"),
        Index("ix_skill_reflections_run", "run_id", unique=True),
        Index("ix_skill_reflections_session", "session_id"),
    )

    run_id: Mapped[str] = mapped_column(String(36), nullable=False)
    session_id: Mapped[str] = mapped_column(String(36), nullable=False)
    agent_id: Mapped[str] = mapped_column(String(36), nullable=False)
    contact_id: Mapped[str] = mapped_column(String(36), nullable=False)
    source_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    _source_run_ids: Mapped[str] = mapped_column(
        "source_run_ids", Text, nullable=False, default="[]"
    )
    _source_message_ids: Mapped[str] = mapped_column(
        "source_message_ids", Text, nullable=False, default="[]"
    )
    outcome: Mapped[str] = mapped_column(
        String(16), nullable=False, default="running"
    )  # running | no_change | changed | conflict | failed
    _revision_ids: Mapped[str] = mapped_column("revision_ids", Text, nullable=False, default="[]")
    error: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), default=_utcnow
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    @property
    def source_run_ids(self) -> list[str]:
        return json.loads(self._source_run_ids)

    @property
    def source_message_ids(self) -> list[str]:
        return json.loads(self._source_message_ids)

    @property
    def revision_ids(self) -> list[str]:
        return json.loads(self._revision_ids)


__all__ = ["SkillReflection"]
