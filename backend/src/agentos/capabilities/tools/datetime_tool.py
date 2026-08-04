"""Datetime capability — datetime_now.

Gives the agent awareness of the current date and time. Essential for
scheduling, timestamps, and general context ("what day is it?").
"""

from datetime import UTC, datetime
from typing import Any


async def datetime_now(args: dict[str, Any], **_kwargs: Any) -> dict[str, Any]:
    """Return the current date and time.

    Args:
        timezone: Optional timezone name (e.g. "America/New_York"). Defaults to UTC.
    """
    tz_name = args.get("timezone")
    tz = UTC

    if tz_name:
        try:
            from zoneinfo import ZoneInfo

            tz = ZoneInfo(tz_name)
        except (ImportError, Exception):
            return {
                "error": f"Unknown timezone: {tz_name}",
                "utc": datetime.now(UTC).isoformat(),
            }

    now = datetime.now(tz)
    return {
        "iso": now.isoformat(),
        "date": now.strftime("%Y-%m-%d"),
        "time": now.strftime("%H:%M:%S"),
        "timezone": str(tz),
        "weekday": now.strftime("%A"),
        "unix": int(now.timestamp()),
    }
