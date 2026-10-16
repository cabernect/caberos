"""Immutable conversation-summary snapshot — evidence per compaction
generation. Sessions point at the active snapshot; prior generations stay
queryable for recovery/audit."""

from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, IdMixin


class ConversationSummary(Base, IdMixin):
    __tablename__ = "conversation_summaries"
    __table_args__ = (
        UniqueConstraint("session_id", "version", name="uq_conv_summary_session_version"),
        Index("ix_conversation_summaries_session_id", "session_id"),
    )

    session_id: Mapped[str] = mapped_column(String(36), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    prior_summary_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    covered_message_ids: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    retained_head_ids: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    retained_tail_ids: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    coverage_known: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
