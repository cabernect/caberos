"""Approval request model."""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, IdMixin


class ApprovalRequest(Base, IdMixin):
    __tablename__ = "approval_requests"

    run_id: Mapped[str] = mapped_column(String(36), ForeignKey("runs.id"), nullable=False)
    capability_name: Mapped[str] = mapped_column(String(255), nullable=False)
    args: Mapped[str] = mapped_column(Text, default="{}")  # JSON
    status: Mapped[str] = mapped_column(
        String(20), default="pending"
    )  # pending, approved, rejected
    decided_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
