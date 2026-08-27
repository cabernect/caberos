"""Knowledge Vault document and indexed chunk models."""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, IdMixin, TimestampMixin


class Document(Base, IdMixin, TimestampMixin):
    """A source document shared across the Knowledge Vault."""

    __tablename__ = "documents"
    __table_args__ = (
        UniqueConstraint("agent_id", "source_path", "content_hash", name="uq_document_content"),
        Index("ix_documents_scope_status", "agent_id", "status"),
    )

    agent_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("agents.id"), nullable=True)
    source_path: Mapped[str] = mapped_column(Text, nullable=False)
    storage_path: Mapped[str] = mapped_column(Text, nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(255), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    indexed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    structure_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")

    chunks: Mapped[list["DocumentChunk"]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )


class DocumentChunk(Base, IdMixin):
    """A bounded searchable excerpt retaining source-location metadata."""

    __tablename__ = "document_chunks"
    __table_args__ = (
        UniqueConstraint("document_id", "seq", name="uq_document_chunk_sequence"),
        Index("ix_document_chunks_document", "document_id"),
    )

    document_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    heading_path: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    page_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_location: Mapped[str | None] = mapped_column(Text, nullable=True)
    block_type: Mapped[str] = mapped_column(String(30), nullable=False, default="paragraph")
    token_count: Mapped[int] = mapped_column(Integer, nullable=False)

    document: Mapped[Document] = relationship(back_populates="chunks")
