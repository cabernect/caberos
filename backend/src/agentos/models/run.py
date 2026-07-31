"""Run and Message models."""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, IdMixin


class Run(Base, IdMixin):
    __tablename__ = "runs"

    session_id: Mapped[str] = mapped_column(String(36), ForeignKey("sessions.id"), nullable=False)
    contact_id: Mapped[str] = mapped_column(String(36), ForeignKey("contacts.id"), nullable=False)
    agent_id: Mapped[str] = mapped_column(String(36), ForeignKey("agents.id"), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), default="pending"
    )  # pending, running, completed, failed
    trigger: Mapped[str] = mapped_column(
        String(20), default="user_message"
    )  # user_message, heartbeat
    message_id: Mapped[str | None] = mapped_column(String(255), nullable=True)  # dedup key
    tokens_in: Mapped[int] = mapped_column(Integer, default=0)
    tokens_out: Mapped[int] = mapped_column(Integer, default=0)
    cost: Mapped[float] = mapped_column(Float, default=0.0)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    is_test: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


class Message(Base, IdMixin):
    __tablename__ = "messages"

    run_id: Mapped[str] = mapped_column(String(36), ForeignKey("runs.id"), nullable=False)
    role: Mapped[str] = mapped_column(
        String(20), nullable=False
    )  # user, assistant, system, tool, heartbeat, thinking, tool_call
    content: Mapped[str] = mapped_column(Text, nullable=False)
    seq: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    # Multimodal: JSON array of attachment metadata (type, mime_type, filename, url/data_ref)
    # Does NOT store base64 data — too large for SQLite. Images are sent to the model
    # at runtime from the InboundMessage; only metadata is persisted for history display.
    attachments: Mapped[str | None] = mapped_column(Text, nullable=True)
