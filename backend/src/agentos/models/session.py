"""Session model."""

from sqlalchemy import DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, IdMixin


class Session(Base, IdMixin):
    __tablename__ = "sessions"

    contact_id: Mapped[str] = mapped_column(String(36), ForeignKey("contacts.id"), nullable=False)
    agent_id: Mapped[str] = mapped_column(String(36), ForeignKey("agents.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="active")  # active, idle, closed
    started_at: Mapped[str] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_activity_at: Mapped[str] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    idle_timeout_min: Mapped[int] = mapped_column(Integer, default=60)
