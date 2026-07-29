"""Connector and connector-capability models."""

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, IdMixin, TimestampMixin


class Connector(Base, IdMixin, TimestampMixin):
    __tablename__ = "connectors"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    type: Mapped[str] = mapped_column(String(50), nullable=False)  # outlook, gmail, calendar, ...
    credential_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)  # secret:// path


class ConnectorCapability(Base, IdMixin, TimestampMixin):
    __tablename__ = "connector_capabilities"

    connector_id: Mapped[str] = mapped_column(String(36), nullable=False)
    capability_name: Mapped[str] = mapped_column(String(255), nullable=False)
