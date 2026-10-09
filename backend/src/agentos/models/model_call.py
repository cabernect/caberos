"""Model call accounting — one row per model request (v0.2 foundations).

Unified ledger: chat completions AND embedding calls land here. ``kind``
separates the transport kind (``chat`` | ``embedding``) and ``purpose`` the
caller's intent (``reasoning`` | ``embedding`` …). Embedding rows carry their
provenance in ``detail`` — exactly
``{resource_id, generation_id, operation, chunk_count}`` — which the
knowledge spend queries index into via ``detail['generation_id']`` /
``detail['operation']``.

Runs currently only aggregate tokens/cost. This table records each call:
which provider and model served it, how many tokens it used, what it cost,
how long it took, and how it ended. The observability workstream builds
per-model filtering and provider spend on top of these rows.
"""

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, IdMixin


class ModelCall(Base, IdMixin):
    __tablename__ = "model_calls"
    __table_args__ = (
        Index("ix_model_calls_run_created", "run_id", "created_at"),
        Index("ix_model_calls_provider_model", "provider_id", "model_name"),
        Index("ix_model_calls_kind_created", "kind", "created_at"),
    )

    # String reference to runs.id: missing runs do not invalidate historical
    # receipts. Conversation deletion still explicitly removes these rows.
    # The index retains efficient run lookups without FK enforcement.
    run_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    agent_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    sub_agent_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    turn: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    kind: Mapped[str] = mapped_column(
        String(20), default="chat", server_default="chat", nullable=False
    )
    purpose: Mapped[str] = mapped_column(
        String(20), default="reasoning", server_default="reasoning", nullable=False
    )
    provider_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    model_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Resolved LiteLLM model string (provider family + name) actually used.
    model_str: Mapped[str | None] = mapped_column(String(255), nullable=True)
    streamed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    tokens_in: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    tokens_out: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    cached_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    thinking_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Call-kind specific provenance. Embedding rows:
    # {resource_id, generation_id, operation, chunk_count}.
    detail: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    cost: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # ok, error, timeout — mirrors the tool-result outcome vocabulary.
    status: Mapped[str] = mapped_column(String(20), default="ok", nullable=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[str] = mapped_column(DateTime(timezone=True), server_default=func.now())
