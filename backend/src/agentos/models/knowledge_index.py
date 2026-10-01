"""Knowledge Vault index models — embedding resources, retrieval profiles,
index generations, and per-generation chunk vectors.

Canonical chunks live on ``DocumentChunk`` (corpus state); these tables hold
index state: which model produced vectors, under which generation, with which
adapter. Rebuild = re-embed into a new generation; re-chunking requires
explicit re-ingest.
"""

from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, IdMixin, TimestampMixin


class EmbeddingResource(Base, IdMixin, TimestampMixin):
    """Provider + model producing embedding vectors for the Vault."""

    __tablename__ = "embedding_resources"

    provider_id: Mapped[str] = mapped_column(String(36), ForeignKey("providers.id"), nullable=False)
    model_name: Mapped[str] = mapped_column(String(255), nullable=False)
    dimensions: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="unvalidated"
    )  # unvalidated | ready | error
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_validated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Remote providers send vault text off-machine; explicit operator opt-in
    # required before the resource may go ready. Local endpoints pass without it.
    egress_allowed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class RetrievalProfile(Base, IdMixin, TimestampMixin):
    """Named retrieval tuning set — fusion mode and chunk/expansion bounds."""

    __tablename__ = "retrieval_profiles"
    __table_args__ = (Index("ix_retrieval_profiles_active", "active"),)

    name: Mapped[str] = mapped_column(String(100), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    config_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")


class IndexGeneration(Base, IdMixin, TimestampMixin):
    """One immutable derived index: embeddings + fusion config over the
    canonical chunk set. Exactly one row is ``active`` at a time."""

    __tablename__ = "index_generations"
    __table_args__ = (Index("ix_index_generations_status", "status"),)

    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    profile_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    profile_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    embedding_resource_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("embedding_resources.id"), nullable=True
    )
    embedding_model: Mapped[str | None] = mapped_column(String(255), nullable=True)
    dimensions: Mapped[int | None] = mapped_column(Integer, nullable=True)
    adapter: Mapped[str] = mapped_column(
        String(20), nullable=False, default="python"
    )  # sqlite-vec | python
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="building"
    )  # building | active | superseded | failed
    stats_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ChunkEmbedding(Base, IdMixin):
    """One chunk's vector inside one generation — vectors never mix generations."""

    __tablename__ = "chunk_embeddings"
    __table_args__ = (
        UniqueConstraint("chunk_id", "generation_id", name="uq_chunk_embedding_gen"),
        Index("ix_chunk_embeddings_generation", "generation_id"),
    )

    chunk_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("document_chunks.id", ondelete="CASCADE"), nullable=False
    )
    generation_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("index_generations.id", ondelete="CASCADE"), nullable=False
    )
    vector: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    dims: Mapped[int] = mapped_column(Integer, nullable=False)


class EmbeddingCall(Base, IdMixin):
    """Ledger row per embedding API call — tokens, cost, latency, outcome.

    Plain string refs (not FKs): the ledger must survive deletion of
    generations, resources, or runs. ``operation`` distinguishes
    validate | index | ingest | repair | query — generation-scoped spend
    sums the index/ingest/repair rows, never query embeds.
    """

    __tablename__ = "embedding_calls"
    __table_args__ = (Index("ix_embedding_calls_generation", "generation_id"),)

    resource_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    generation_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    run_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    agent_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    provider_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    model_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    operation: Mapped[str] = mapped_column(String(20), nullable=False)
    chunk_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tokens_in: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cost: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="ok")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
