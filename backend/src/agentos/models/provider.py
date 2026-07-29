"""Model provider configuration (D39)."""

from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, IdMixin, TimestampMixin


class Provider(Base, IdMixin, TimestampMixin):
    __tablename__ = "providers"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    type: Mapped[str] = mapped_column(
        String(50), nullable=False
    )  # openai, anthropic, google, ollama, azure, ...
    encrypted_key: Mapped[str | None] = mapped_column(
        Text, nullable=True
    )  # Fernet-encrypted API key
    base_url: Mapped[str | None] = mapped_column(String(255), nullable=True)
    org_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    extra_params: Mapped[str] = mapped_column(Text, default="{}")  # JSON
