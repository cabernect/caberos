"""Persistent operator notifications + per-surface delivery state (W9)."""

from sqlalchemy import Boolean, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, IdMixin, TimestampMixin


class Notification(Base, IdMixin, TimestampMixin):
    __tablename__ = "notifications"

    notification_type: Mapped[str] = mapped_column(String(50), nullable=False)
    severity: Mapped[str] = mapped_column(String(20), nullable=False, default="info")
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    action_path: Mapped[str | None] = mapped_column(String(255), nullable=True)
    entity_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    entity_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    # Which agent produced the event (null for system-scoped events — MCP,
    # vault, skills, providers). agent_name is a snapshot: the badge shows the
    # name as it was at emit time, surviving renames/deletes without a join.
    agent_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    agent_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Deterministic emitter key — INSERT-or-ignore dedups re-emitted events.
    event_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    read: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class NotificationDelivery(Base, IdMixin, TimestampMixin):
    """One row per (notification, adapter) — delivered/suppressed/failed."""

    __tablename__ = "notification_deliveries"
    __table_args__ = (
        UniqueConstraint("notification_id", "adapter", name="uq_delivery_adapter"),
    )

    notification_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    adapter: Mapped[str] = mapped_column(String(30), nullable=False)
    state: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


class NotificationPrefs(Base, IdMixin, TimestampMixin):
    """Singleton operator prefs — event x surface matrix + quiet hours."""

    __tablename__ = "notification_prefs"

    prefs: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
