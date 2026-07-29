"""Contact model (D8 — optional binding to internal record)."""

from sqlalchemy import String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, IdMixin, TimestampMixin


class Contact(Base, IdMixin, TimestampMixin):
    __tablename__ = "contacts"
    __table_args__ = (
        UniqueConstraint("channel", "bot_id", "external_user_id", name="uq_contact_channel"),
    )

    channel: Mapped[str] = mapped_column(
        String(50), nullable=False
    )  # dashboard_chat, telegram, ...
    bot_id: Mapped[str] = mapped_column(String(36), nullable=False)  # agent_id
    external_user_id: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), default="")
    binding: Mapped[str | None] = mapped_column(
        Text, nullable=True
    )  # JSON binding to internal record
