"""Execution Manifest — immutable provenance captured at run start (v0.2).

Every run records exactly which revisions of versioned things it uses:
agent config, plan, schedule, skills, retrieval profile, knowledge
snapshots, browser profile, and artifact bases. Later edits to those
entities produce new revisions and never affect a captured run.

The manifest stores IDs, version numbers, and safe hashes only — never
secrets, cookies, or private content.
"""

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, IdMixin


class ExecutionManifest(Base, IdMixin):
    __tablename__ = "execution_manifests"

    run_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("runs.id"), nullable=False, unique=True
    )
    # The AgentVersion row active when the run started.
    agent_version_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    agent_version_number: Mapped[int | None] = mapped_column(nullable=True)
    # Effective model identity at run start (override-aware). No secrets.
    model_provider_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    model_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Versioned entities captured by reference. Null/empty until those
    # modules exist — the columns are the contract downstream pillars use.
    plan_revision_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    schedule_revision_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    skill_revision_ids: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    retrieval_profile_revision_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    knowledge_snapshot_ids: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    browser_profile_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    artifact_base_revision_ids: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    created_at: Mapped[str] = mapped_column(DateTime(timezone=True), server_default=func.now())
