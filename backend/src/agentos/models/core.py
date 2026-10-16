"""Core revision — immutable evidence record of a published core file.

MEMORY.md remains the authoritative editable curated document; each
CoreRevision is a frozen snapshot of one published whole-file state
(managed identity + curated content) with its provenance. Never an
editor — the file is the editor.
"""

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, IdMixin


class CoreRevision(Base, IdMixin):
    __tablename__ = "core_revisions"

    agent_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("agents.id", ondelete="CASCADE"), nullable=False
    )
    # Exact UTF-8 whole-file bytes published (managed identity + curated).
    content: Mapped[str] = mapped_column(Text, nullable=False)
    # Just the operator/agent-editable portion (no managed identity).
    curated_content: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    # AgentVersion whose soul/persona/task generated the managed prefix —
    # metadata only; the file carries a hash, not this id.
    identity_source_version_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    # JSON list of cited source message/entry ids for the change.
    source_refs: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    # Candidate snapshots stay False until the disk hash is verified to
    # match; unpublished candidates are long-tail evidence, not a queue.
    published: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[str] = mapped_column(DateTime(timezone=True), server_default=func.now())
