"""Session model."""

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, IdMixin


class Session(Base, IdMixin):
    __tablename__ = "sessions"

    contact_id: Mapped[str] = mapped_column(String(36), ForeignKey("contacts.id"), nullable=False)
    agent_id: Mapped[str] = mapped_column(String(36), ForeignKey("agents.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="active")  # active, idle, closed
    # auto-generated from first user message
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Set once the LLM title task lands a title — gates the background
    # generator so it fires once per session, not once per completed run.
    title_generated: Mapped[bool] = mapped_column(Boolean, default=False)
    started_at: Mapped[str] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_activity_at: Mapped[str] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    # Legacy per-session override — unused: the agent's live
    # limits.session_idle_timeout_min is the authoritative idle threshold.
    idle_timeout_min: Mapped[int] = mapped_column(Integer, default=30)
    # Episodic memory: 3-5 sentence summary generated at session close.
    # FTS5-indexed for topical recall at run start.
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Idempotency guard: once closed, session_close_extract() won't re-fire.
    closed: Mapped[bool] = mapped_column(Boolean, default=False)
    # Running compaction summary — updated by the compaction pipeline when
    # the context window overflows. Stores the structured summary of older
    # messages that have been compacted out of the verbatim context.
    conversation_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    # JSON array of covered Message ids — NULL means unknown legacy coverage
    # (older rows store originals alongside the prior summary rather than
    # guessing which records the summary consumed).
    conversation_summary_coverage: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Optimistic version for conditional summary writes.
    conversation_summary_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    active_conversation_summary_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    conversation_summary_coverage_known: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    # JSON array of Message ids already fed to a successful session-close
    # extraction — the incremental-learning watermark. NULL = nothing proven
    # learned (legacy or pre-close) → everything is presented again.
    learned_coverage: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Pinned core snapshot for this session — later runs/restarts load
    # exactly this revision regardless of later notebook updates.
    core_revision_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    # Channel that created this session (null = dashboard).
    # Used to keep channel sessions persistent — one session per channel+chat.
    channel: Mapped[str | None] = mapped_column(String(50), nullable=True)
    external_user_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
