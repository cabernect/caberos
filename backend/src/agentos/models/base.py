"""SQLAlchemy declarative base and mixins."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, String, event, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _uuid() -> str:
    return str(uuid.uuid4())


class Base(DeclarativeBase):
    pass


# SQLite stores datetimes without timezone info even when the column is
# DateTime(timezone=True). Loaded rows come back naive and Pydantic serializes
# them without a UTC offset — browsers then parse them as *local* time and
# display UTC wall-time instead. Attach tzinfo=UTC on load so every datetime
# the API returns is timezone-aware and serializes with an offset. On Postgres
# the datetimes are already aware, so this is a no-op there.
@event.listens_for(Base, "load", propagate=True)
def _assume_utc(obj: object, _context: object) -> None:
    for key, value in vars(obj).items():
        if isinstance(value, datetime) and value.tzinfo is None:
            setattr(obj, key, value.replace(tzinfo=UTC))


class IdMixin:
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        default=_utcnow,
        onupdate=_utcnow,
    )
