"""Audit record model (immutable — inserts only, no updates)."""

from datetime import UTC, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, IdMixin


class AuditRecord(Base, IdMixin):
    __tablename__ = "audit_records"
    __table_args__ = (Index("ix_audit_run_call_sub", "run_id", "call_id", "sub_agent_id"),)

    run_id: Mapped[str] = mapped_column(String(36), ForeignKey("runs.id"), nullable=False)
    agent_id: Mapped[str] = mapped_column(String(36), nullable=False)
    sub_agent_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    # Correlation (W10): the tool call id this call answered. NULL on legacy
    # rows and on calls recorded before the correlation fields landed.
    call_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    capability_name: Mapped[str] = mapped_column(String(255), nullable=False)
    subject_contact_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    allowed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    # Outcome classification (v0.2): ok, denied, error, timeout, interrupted.
    # `allowed` is the policy decision; `outcome` is how the call ended.
    outcome: Mapped[str] = mapped_column(String(20), default="ok", nullable=False)
    denied_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    cost: Mapped[float] = mapped_column(Float, default=0.0)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    args: Mapped[str] = mapped_column(Text, default="{}")  # JSON of call args
    result: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON of result (truncated)
    # Capability effects snapshot at execution time (registry effects). NULL =
    # unknown (legacy rows) — history is never re-labelled from the registry.
    effects: Mapped[list | None] = mapped_column(JSON, nullable=True)
    # NULL on legacy rows (additive column, never backfilled); new rows get
    # real UTC. `created_at` landed late — older audits have no timestamp.
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        server_default=func.now(),
        nullable=True,
    )
