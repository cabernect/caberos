"""Skill activation events — one immutable row per recorded activation.

A SkillActivation is written after a successful skills_load or a successful
forced/slash skill injection. Identity is event-time truth: the stable Skill
row id plus name/scope/owner as resolved then. skill_id is a plain string,
not a foreign key — deleting a Skill must never erase its usage history.
"""

from datetime import datetime

from sqlalchemy import Index, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import DateTime

from .base import Base, IdMixin, _utcnow


class SkillActivation(Base, IdMixin):
    __tablename__ = "skill_activations"
    __table_args__ = (
        Index("ix_skill_activations_skill", "skill_id"),
        Index("ix_skill_activations_run", "run_id"),
        UniqueConstraint("event_key", name="uq_skill_activations_event_key"),
    )

    skill_id: Mapped[str] = mapped_column(String(36), nullable=False)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    scope: Mapped[str] = mapped_column(String(20), nullable=False)
    owner_agent_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    run_id: Mapped[str] = mapped_column(String(36), nullable=False)
    agent_id: Mapped[str] = mapped_column(String(36), nullable=False)
    sub_agent_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    source: Mapped[str] = mapped_column(String(16), nullable=False)  # load | forced
    call_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Deterministic over run/subagent/source/call — repeat dispatch of the
    # same logical call (idempotent replay) writes exactly one row; forced
    # injection has no call_id so it dedups to once per run.
    event_key: Mapped[str] = mapped_column(String(160), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), default=_utcnow
    )


__all__ = ["SkillActivation"]
