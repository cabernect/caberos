"""Memory models (D34 — knowledge graph triples and raw entries).

Note: MEMORY.md is NOT a DB table — it's a markdown file in the agent home dir.
"""

from sqlalchemy import ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, IdMixin, TimestampMixin


class MemoryEntry(Base, IdMixin, TimestampMixin):
    __tablename__ = "memory_entries"
    __table_args__ = (Index("ix_memory_entries_contact_agent", "contact_id", "agent_id"),)

    contact_id: Mapped[str] = mapped_column(String(36), ForeignKey("contacts.id"), nullable=False)
    agent_id: Mapped[str] = mapped_column(String(36), ForeignKey("agents.id"), nullable=False)
    key: Mapped[str] = mapped_column(String(255), nullable=False)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    tags: Mapped[str] = mapped_column(Text, default="[]")  # JSON list
    # Run-scoped working memory: entries are deleted at run end unless
    # promoted (included in MEMORY.md by the consolidation LLM).
    run_id: Mapped[str | None] = mapped_column(String(36), nullable=True)


class MemoryTriple(Base, IdMixin, TimestampMixin):
    __tablename__ = "memory_triples"
    __table_args__ = (Index("ix_memory_triples_contact_agent", "contact_id", "agent_id"),)

    contact_id: Mapped[str] = mapped_column(String(36), ForeignKey("contacts.id"), nullable=False)
    agent_id: Mapped[str] = mapped_column(String(36), ForeignKey("agents.id"), nullable=False)
    subject: Mapped[str] = mapped_column(String(255), nullable=False)
    predicate: Mapped[str] = mapped_column(String(255), nullable=False)
    object: Mapped[str] = mapped_column(Text, nullable=False)
    source_run_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
