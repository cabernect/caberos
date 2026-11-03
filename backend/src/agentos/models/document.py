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
    # Semantic coverage in the *current active* generation: embedded | pending | na.
    # Recomputed on activate/rollback/repair; 'na' when no embeddings apply.
    semantic_state: Mapped[str] = mapped_column(String(20), nullable=False, default="na")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    indexed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    structure_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")

    chunks: Mapped[list["DocumentChunk"]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )
    sheets: Mapped[list["DocumentSheet"]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )


class DocumentSheet(Base, IdMixin):
    """One parsed sheet/table inside a tabular document.

    ``columns_json`` stores ``[{"id": "col_1", "label": "...", "kind": "..."}]`` —
    stable ids for querying, original labels for display (duplicates/blanks are
    never merged). ``warnings_json`` lists parser findings (never silent drops).
    """

    __tablename__ = "document_sheets"
    __table_args__ = (
        UniqueConstraint("document_id", "sheet_index", name="uq_document_sheet_index"),
        Index("ix_document_sheets_document", "document_id"),
    )

    document_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    sheet_index: Mapped[int] = mapped_column(Integer, nullable=False)
    columns_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    row_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    warnings_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")

    document: Mapped[Document] = relationship(back_populates="sheets")
    rows: Mapped[list["DocumentRow"]] = relationship(
        back_populates="sheet", cascade="all, delete-orphan"
    )


class DocumentRow(Base, IdMixin):
    """One source row of a parsed sheet — typed cells plus exact coordinates."""

    __tablename__ = "document_rows"
    __table_args__ = (
        UniqueConstraint("sheet_id", "row_number", name="uq_document_row_number"),
        Index("ix_document_rows_sheet", "sheet_id"),
    )

    sheet_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("document_sheets.id", ondelete="CASCADE"), nullable=False
    )
    # Original source row number — header row is 1, first data row is 2.
    row_number: Mapped[int] = mapped_column(Integer, nullable=False)
    cells_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    # e.g. "Sales!A42:F42" — or "csv!A42:F42" for the synthetic CSV sheet.
    coord: Mapped[str] = mapped_column(String(96), nullable=False)

    sheet: Mapped[DocumentSheet] = relationship(back_populates="rows")


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
    # parent = expansion-only container; child = retrievable unit inside a
    # parent; chunk = legacy flat row (still retrievable, never expands).
    kind: Mapped[str] = mapped_column(String(10), nullable=False, default="chunk")
    parent_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("document_chunks.id", ondelete="CASCADE"), nullable=True
    )
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    heading_path: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    page_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_location: Mapped[str | None] = mapped_column(Text, nullable=True)
    block_type: Mapped[str] = mapped_column(String(30), nullable=False, default="paragraph")
    token_count: Mapped[int] = mapped_column(Integer, nullable=False)

    document: Mapped[Document] = relationship(back_populates="chunks")
