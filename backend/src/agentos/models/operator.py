"""Operator auth model (D4)."""

from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, IdMixin, TimestampMixin


class Operator(Base, IdMixin, TimestampMixin):
    __tablename__ = "operators"

    username: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    must_change_password: Mapped[bool] = mapped_column(default=True)


class OperatorAuditLog(Base, IdMixin, TimestampMixin):
    __tablename__ = "operator_audit_logs"

    operator_id: Mapped[str] = mapped_column(String(36), nullable=False)
    action: Mapped[str] = mapped_column(String(255), nullable=False)
    target: Mapped[str] = mapped_column(Text, default="")
