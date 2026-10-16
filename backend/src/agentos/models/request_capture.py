"""Model request capture — bounded, redacted record of what the SDK boundary
actually received (W11 step 14). The row's id IS the associated ModelCall.id
when one is recorded — the capture row never gates execution.
"""

from datetime import UTC, datetime

from sqlalchemy import Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, IdMixin


class ModelRequestCapture(Base, IdMixin):
    __tablename__ = "model_request_captures"

    # Redacted JSON body: {"rendered_context": {...}, "dispatch_input": {...}}.
    # Nullable — retention expires the body, never the row/metadata.
    payload: Mapped[str | None] = mapped_column(Text, nullable=True)
    payload_bytes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # available / partial / failed / expired / not_recorded / not_applicable
    state: Mapped[str] = mapped_column(String(24), nullable=False, default="available")
    # Approved metadata only: refs/counts/flags — never previews or secrets.
    capture_meta: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(UTC))
    expired_at: Mapped[datetime | None] = mapped_column(nullable=True)
    expiry_reason: Mapped[str | None] = mapped_column(String(32), nullable=True)
