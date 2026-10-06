"""Skill and SkillRevision models (W6 Skills Studio).

Content lives on disk (the Agent Skills spec is file-native); these rows are
the resolution index — which revision each agent sees.

Storage convention: `SkillRevision.storage_path` is relative to a per-scope
base — `settings.skills_dir` for built-ins, the skills-store root
(`data/skills-store/`) for global and published agent-local snapshots.
Drafts have no revision; their working dir is derived from
`owner_agent_id` + `name` (`workspace/skill-drafts/{name}/`).
"""

from sqlalchemy import ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, IdMixin, TimestampMixin
from .revision import RevisionedEntityMixin, RevisionMixin


class Skill(Base, IdMixin, RevisionedEntityMixin, TimestampMixin):
    """A managed skill — the logical identity across revisions."""

    __tablename__ = "skills"
    __table_args__ = (
        # Within (scope, owner) a name is unique: one global "pdf", one
        # local "pdf" per agent. Cross-scope duplicates shadow by precedence.
        UniqueConstraint("name", "scope", "owner_agent_id", name="uq_skill_scope_name"),
        Index("ix_skills_status", "status"),
    )

    name: Mapped[str] = mapped_column(String(64), nullable=False)
    scope: Mapped[str] = mapped_column(
        String(20), nullable=False
    )  # built-in | global | agent-local
    owner_agent_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("agents.id"), nullable=True
    )
    availability: Mapped[str] = mapped_column(
        String(20), nullable=False, default="all"
    )  # all | selected (global only)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="draft"
    )  # draft | published | disabled | archived
    # Builder-mode sessions link here: the run detects "this session is
    # drafting this skill" from this field (no Session schema change).
    builder_session_id: Mapped[str | None] = mapped_column(String(36), nullable=True)

    revisions: Mapped[list["SkillRevision"]] = relationship(
        back_populates="skill", cascade="all, delete-orphan"
    )
    assignments: Mapped[list["SkillAssignment"]] = relationship(
        back_populates="skill", cascade="all, delete-orphan"
    )


class SkillRevision(Base, IdMixin, RevisionMixin):
    """An immutable snapshot of a skill's directory contents."""

    __tablename__ = "skill_revisions"
    __table_args__ = (
        UniqueConstraint("skill_id", "revision_number", name="uq_skill_revision_number"),
        Index("ix_skill_revisions_skill", "skill_id"),
    )

    skill_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("skills.id", ondelete="CASCADE"), nullable=False
    )
    storage_path: Mapped[str] = mapped_column(Text, nullable=False)
    source_run_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    validation_result: Mapped[str] = mapped_column(Text, nullable=False, default="{}")

    skill: Mapped[Skill] = relationship(back_populates="revisions")


class SkillAssignment(Base, IdMixin):
    """Global-skill visibility for one agent (availability=selected)."""

    __tablename__ = "skill_assignments"
    __table_args__ = (UniqueConstraint("skill_id", "agent_id", name="uq_skill_assignment"),)

    skill_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("skills.id", ondelete="CASCADE"), nullable=False
    )
    agent_id: Mapped[str] = mapped_column(String(36), nullable=False)

    skill: Mapped[Skill] = relationship(back_populates="assignments")
