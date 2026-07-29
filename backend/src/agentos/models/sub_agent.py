"""Sub-agent model (pooled capabilities)."""

from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, IdMixin, TimestampMixin


class SubAgent(Base, IdMixin, TimestampMixin):
    __tablename__ = "sub_agents"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    task: Mapped[str] = mapped_column(Text, default="")
    model: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )  # JSON ModelConfig or None
    capabilities: Mapped[str] = mapped_column(Text, default="[]")  # JSON list of capability names
