"""Schedule entities (v0.2 W8).

A Schedule is a versioned trigger + execution spec owned by one agent.
Edits create a new immutable ScheduleRevision; an in-flight occurrence keeps
the revision it was launched with (captured on the Execution Manifest via
``schedule_revision_id``).

- ``Schedule`` — logical identity + mutable runtime state (enabled,
  ``next_fire_at``, failure counters). ``managed="heartbeat"`` marks the
  schedule that backs an agent's heartbeat config — it is edited through
  the heartbeat facade, not the schedules API.
- ``ScheduleRevision`` — immutable payload: trigger, task, policies,
  auto-approve scope, limits, optional plan/model overrides. Stored as
  canonical JSON in ``config`` so ``content_hash`` is stable.
- ``ScheduleOccurrence`` — one row per firing attempt (including skipped or
  missed ones with no run), so history shows what the schedule *decided*,
  not just what ran. ``retry_of`` chains retries to their parent occurrence.
"""

from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import TypeDecorator

from .base import Base, IdMixin, TimestampMixin
from .revision import RevisionedEntityMixin, RevisionMixin


class UTCDateTime(TypeDecorator):
    """DateTime that round-trips tz-aware UTC.

    SQLite has no tz-aware type — ``DateTime(timezone=True)`` returns naive
    values on re-read, which breaks arithmetic against ``datetime.now(UTC)``.
    Store naive-UTC, always hand back aware-UTC.
    """

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            return value
        return value.astimezone(UTC).replace(tzinfo=None)

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)


class Schedule(Base, IdMixin, TimestampMixin, RevisionedEntityMixin):
    __tablename__ = "schedules"
    __table_args__ = (Index("ix_schedules_due", "enabled", "next_fire_at"),)

    agent_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("agents.id"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # "heartbeat" = backs agent_config.heartbeat via the facade; None = user-created
    managed: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # Persisted fire instants (UTC) — the restart/sleep source of truth
    next_fire_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    last_fired_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    last_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    consecutive_failures: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class ScheduleRevision(Base, IdMixin, RevisionMixin):
    """Immutable schedule payload.

    ``config`` JSON shape:
      trigger:  {kind: "once"|"interval"|"cron",
                 at: iso (once), every_seconds: int (interval),
                 cron: str (cron), timezone: IANA name}
      task_prompt: str
      policies:  {missed: "skip"|"run_once"|"catch_up",
                  overlap: "skip"|"queue"|"cancel_previous"|"allow_parallel",
                  failure: {mode: "no_retry"|"bounded_retry",
                            max_attempts: int, backoff_seconds: int}}
      auto_approve: [capability names] — pre-approved within the agent ceiling
      limits:    {max_cost: float | None}
      plan_revision_id: str | None
      model_override: {provider_id, name} | None
      skill: str | None
    """

    __tablename__ = "schedule_revisions"
    __table_args__ = (Index("ix_schedule_revisions_schedule", "schedule_id"),)

    schedule_id: Mapped[str] = mapped_column(String(36), ForeignKey("schedules.id"), nullable=False)
    config: Mapped[str] = mapped_column(Text, nullable=False)  # canonical JSON


class ScheduleOccurrence(Base, IdMixin):
    """One row per scheduled firing decision — the persistent history.

    ``status``: queued | running | completed | failed | skipped_missed |
    skipped_overlap | cancelled. Missed/skipped occurrences have no run_id —
    that absence is the record.
    """

    __tablename__ = "schedule_occurrences"
    __table_args__ = (
        Index("ix_schedule_occurrences_schedule", "schedule_id", "scheduled_for"),
        Index("ix_schedule_occurrences_open", "schedule_id", "status"),
    )

    schedule_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("schedules.id"), nullable=False, index=True
    )
    revision_id: Mapped[str] = mapped_column(String(36), nullable=False)
    run_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    scheduled_for: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="queued")
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    retry_of: Mapped[str | None] = mapped_column(String(36), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=lambda: datetime.now(UTC), nullable=False
    )
