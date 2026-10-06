"""Model call accounting — one row per model request (v0.2 foundations).

Runs currently only aggregate tokens/cost. This table records each call:
which provider and model served it, how many tokens it used, what it cost,
how long it took, and how it ended. The observability workstream builds
per-model filtering and provider spend on top of these rows.
"""

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, IdMixin


class ModelCall(Base, IdMixin):
    __tablename__ = "model_calls"

    run_id: Mapped[str] = mapped_column(String(36), ForeignKey("runs.id"), nullable=False)
    agent_id: Mapped[str] = mapped_column(String(36), nullable=False)
    sub_agent_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    turn: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    provider_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    model_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Resolved LiteLLM model string (provider family + name) actually used.
    model_str: Mapped[str | None] = mapped_column(String(255), nullable=True)
    streamed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    tokens_in: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    tokens_out: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    cached_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cost: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # ok, error, timeout — mirrors the tool-result outcome vocabulary.
    status: Mapped[str] = mapped_column(String(20), default="ok", nullable=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[str] = mapped_column(DateTime(timezone=True), server_default=func.now())
