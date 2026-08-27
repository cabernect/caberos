"""Web search sources retrieved during a run."""

from sqlalchemy import ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, IdMixin


class WebSource(Base, IdMixin):
    """A web search result that can be cited in an assistant response."""

    __tablename__ = "web_sources"
    __table_args__ = (
        UniqueConstraint("run_id", "url", name="uq_web_source_run_url"),
        Index("ix_web_sources_run", "run_id"),
    )

    run_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("runs.id", ondelete="CASCADE"), nullable=False
    )
    message_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("messages.id", ondelete="CASCADE"), nullable=True
    )
    url: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False, default="")
    excerpt: Mapped[str] = mapped_column(Text, nullable=False, default="")
    rank: Mapped[int | None] = mapped_column(Integer, nullable=True)
