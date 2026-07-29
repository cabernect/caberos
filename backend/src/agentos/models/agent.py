"""Agent and AgentVersion models."""

from sqlalchemy import Boolean, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, IdMixin, TimestampMixin


class Agent(Base, IdMixin, TimestampMixin):
    __tablename__ = "agents"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    active_version_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("agent_versions.id"), nullable=True
    )

    versions: Mapped[list["AgentVersion"]] = relationship(
        back_populates="agent",
        foreign_keys="AgentVersion.agent_id",
        order_by="AgentVersion.version_number",
    )


class AgentVersion(Base, IdMixin, TimestampMixin):
    __tablename__ = "agent_versions"

    agent_id: Mapped[str] = mapped_column(String(36), ForeignKey("agents.id"), nullable=False)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    config: Mapped[str] = mapped_column(Text, nullable=False)  # JSON-serialized AgentConfig
    is_active: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    agent: Mapped["Agent"] = relationship(back_populates="versions", foreign_keys=[agent_id])
