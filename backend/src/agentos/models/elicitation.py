"""Elicitation request model — when the agent needs user input to continue."""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, IdMixin


class ElicitationRequest(Base, IdMixin):
    """A pending clarifying question from the agent to the user.

    Created when the agent calls `agent.ask_user(question)`.
    The run pauses until the user responds via the API.
    """

    __tablename__ = "elicitation_requests"

    run_id: Mapped[str] = mapped_column(String(36), ForeignKey("runs.id"), nullable=False)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    options: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON array of options, or None for free-text
    status: Mapped[str] = mapped_column(
        String(20), default="pending"
    )  # pending, answered, cancelled
    response: Mapped[str | None] = mapped_column(Text, nullable=True)  # user's answer
    responded_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    responded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
