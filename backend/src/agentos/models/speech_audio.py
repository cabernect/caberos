"""Operator read-aloud audio cache (W10 unit 5)."""

from sqlalchemy import Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, IdMixin, TimestampMixin


class SpeechAudioCache(Base, IdMixin, TimestampMixin):
    """Validated synthesized audio for replay without re-billing.

    cache_key binds the rendered speakable text, renderer version, and the
    frozen binding snapshot (provider/model/options/revision). Any change to
    those inputs is a different key and dispatches again — a stale row never
    silently answers a request that no longer matches what was billed.
    """

    __tablename__ = "speech_audio_cache"
    __table_args__ = (Index("ix_speech_audio_cache_created", "created_at"),)

    cache_key: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    message_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    session_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    agent_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    provider_id: Mapped[str] = mapped_column(String(36), nullable=False)
    provider_type: Mapped[str] = mapped_column(String(64), nullable=False)
    model: Mapped[str] = mapped_column(String(255), nullable=False)
    binding_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    mime: Mapped[str] = mapped_column(String(64), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    audio_path: Mapped[str] = mapped_column(Text, nullable=False)
    source_request_id: Mapped[str] = mapped_column(String(64), nullable=False)
