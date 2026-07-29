"""Capability registry and agent-capability grants."""

from sqlalchemy import Boolean, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, IdMixin, TimestampMixin


class Capability(Base, IdMixin, TimestampMixin):
    __tablename__ = "capabilities"

    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    kind: Mapped[str] = mapped_column(
        String(50), nullable=False
    )  # tool, sub_agent, memory, connector_action
    description: Mapped[str] = mapped_column(Text, default="")
    parameters_schema: Mapped[str] = mapped_column(Text, default="{}")  # JSON schema
    egress: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    require_approval: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    subject_scoped: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class AgentCapability(Base, IdMixin, TimestampMixin):
    __tablename__ = "agent_capabilities"

    agent_version_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("agent_versions.id"), nullable=False
    )
    capability_name: Mapped[str] = mapped_column(String(255), nullable=False)
    subject_scope: Mapped[str] = mapped_column(String(50), default="none")  # self, any, none
    require_approval_override: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
