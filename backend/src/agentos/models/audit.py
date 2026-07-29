"""Audit record model (immutable — inserts only, no updates)."""

from sqlalchemy import Boolean, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, IdMixin


class AuditRecord(Base, IdMixin):
    __tablename__ = "audit_records"

    run_id: Mapped[str] = mapped_column(String(36), ForeignKey("runs.id"), nullable=False)
    agent_id: Mapped[str] = mapped_column(String(36), nullable=False)
    sub_agent_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    capability_name: Mapped[str] = mapped_column(String(255), nullable=False)
    subject_contact_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    allowed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    denied_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    cost: Mapped[float] = mapped_column(Float, default=0.0)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    args: Mapped[str] = mapped_column(Text, default="{}")  # JSON of call args
    result: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON of result (truncated)
