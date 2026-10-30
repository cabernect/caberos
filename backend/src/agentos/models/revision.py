"""Shared immutable-revision conventions (v0.2 foundations).

Plans, Skills, Artifacts, Schedules, and Retrieval Profiles all version the
same way. These mixins are the convention those models build on:

- A stable logical identity points at a current revision.
- Edits create a new revision; history is never rewritten.
- Restore creates another revision, not a rollback.
- Active runs retain the revision captured in their Execution Manifest.
- Deletion is archive (tombstone) by default; purge removes rows.

Usage:

    class Plan(Base, IdMixin, RevisionedEntityMixin): ...
    class PlanRevision(Base, IdMixin, RevisionMixin): ...
"""

from datetime import UTC, datetime

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column


def _utcnow() -> datetime:
    return datetime.now(UTC)


class RevisionedEntityMixin:
    """The logical identity half of a revisioned pair.

    `current_revision_id` points at the live revision. `archived_at` is the
    tombstone: set it to hide the entity without destroying revisions, so
    restore and audit remain possible. Permanent purge deletes the rows.
    """

    current_revision_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class RevisionMixin:
    """The immutable snapshot half of a revisioned pair.

    `content_hash` is a safe hash of the revision's payload (used for
    provenance and dedup) — never a secret or raw private content.
    """

    revision_number: Mapped[int] = mapped_column(Integer, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    change_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
