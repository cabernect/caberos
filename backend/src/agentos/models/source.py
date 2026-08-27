"""Persisted Knowledge Vault sources retrieved during a run."""

from sqlalchemy import ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, IdMixin


class RunSource(Base, IdMixin):
    """A document excerpt returned by doc_search for a run."""

    __tablename__ = "run_sources"
    __table_args__ = (
        UniqueConstraint("run_id", "chunk_id", name="uq_run_source_chunk"),
        Index("ix_run_sources_run", "run_id"),
    )

    run_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("runs.id", ondelete="CASCADE"), nullable=False
    )
    message_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("messages.id", ondelete="CASCADE"), nullable=True
    )
    chunk_id: Mapped[str] = mapped_column(String(36), nullable=False)
    document_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    source_path: Mapped[str] = mapped_column(Text, nullable=False)
    storage_path: Mapped[str] = mapped_column(Text, nullable=False)
    heading_path: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    page_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sheet_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source_location: Mapped[str | None] = mapped_column(String(255), nullable=True)
    excerpt: Mapped[str] = mapped_column(Text, nullable=False)
    rank: Mapped[float | None] = mapped_column(nullable=True)
