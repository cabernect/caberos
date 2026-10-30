"""Operator-local calendar helpers for ``?tz=`` endpoints.

Day boundaries are an operator-facing concept ("today", "yesterday"), so
endpoints that bucket rows by calendar day accept a ``tz`` IANA name — the
dashboard sends the browser zone. Stored instants stay UTC; only bucketing
moves. Column-select rows bypass the ORM load hook and come back naive —
a naive datetime here is UTC.
"""

from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo


def operator_tz(name: str | None):
    """Resolve a ``?tz=`` value. Unknown or absent → UTC (previous behavior)."""
    if name:
        try:
            return ZoneInfo(name)
        except Exception:
            pass
    return UTC


def local_date(dt: datetime, tz) -> date:
    """Calendar date of ``dt`` in the operator's zone."""
    return as_utc(dt).astimezone(tz).date()


def as_utc(dt: datetime) -> datetime:
    """Re-attach UTC to a possibly-naive stored instant.

    ORM entity loads get tzinfo back via the ``_assume_utc`` listener, but
    column selects and aggregates (``func.max``) bypass it — without this,
    naive values serialize offset-less and browsers read them as local time,
    displaying the UTC wall clock.
    """
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)
