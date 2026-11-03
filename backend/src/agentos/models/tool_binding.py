"""Global tool bindings — how supported tools execute (provider/model/options).

Separate from per-agent authority: a binding chooses *how* a tool runs;
capability grants choose *who* may run it. Secrets never live here —
provider_id references the encrypted provider store only.
"""

from sqlalchemy import Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, IdMixin, TimestampMixin


class ToolBinding(Base, IdMixin, TimestampMixin):
    __tablename__ = "tool_bindings"

    # Binding key — matches a spec in capabilities/bindings.py
    # (e.g. "search.web", "media.tts"). One row per key.
    key: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    # Provider the tool executes against. Nullable: engine-based tools
    # (web search) don't need a provider.
    provider_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    # Model name — free text like Model Offering override; catalog suggests,
    # never required to match. Empty string = unset.
    model: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    # Validated tool-specific options (JSON object).
    options: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    # Optimistic-concurrency revision — bumped on every write; PUT carries
    # expected_revision and 409s on drift so concurrent operators can't
    # silently clobber each other.
    revision: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
