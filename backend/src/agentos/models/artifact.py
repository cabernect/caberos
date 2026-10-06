"""Artifact + ArtifactRevision — versioned workspace deliverables (W2).

The workspace holds the current file; managed app data holds immutable
revision bytes. Follows the shared revision convention (models/revision.py):
edits create revisions, restore creates a new revision, archive tombstones.
"""

from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, IdMixin, TimestampMixin
from .revision import RevisionedEntityMixin, RevisionMixin


class Artifact(Base, IdMixin, RevisionedEntityMixin, TimestampMixin):
    """Logical identity of a tracked workspace file.

    `current_path` is workspace-relative so artifacts survive data-dir
    relocation. `tracking_status`: tracked | external_modified | conflict.
    """

    __tablename__ = "artifacts"

    workspace_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    current_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    format: Mapped[str] = mapped_column(String(16), nullable=False)
    tracking_status: Mapped[str] = mapped_column(String(32), default="tracked", nullable=False)
    created_by: Mapped[str | None] = mapped_column(String(255), nullable=True)


class ArtifactRevision(Base, IdMixin, RevisionMixin):
    """Immutable bytes snapshot of an artifact at a point in time.

    `storage_path` is relative to the managed artifacts dir. Provenance
    fields link the revision to the run/message/plan step that produced it.
    """

    __tablename__ = "artifact_revisions"

    artifact_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("artifacts.id"), nullable=False, index=True
    )
    storage_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    byte_size: Mapped[int] = mapped_column(Integer, nullable=False)
    preview_status: Mapped[str] = mapped_column(String(16), default="none", nullable=False)
    source_run_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    source_message_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    source_plan_step_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    base_revision_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
