"""
Time helpers for Calendar sync.

The app stores task deadlines as naive datetimes and the UI renders them as
wall-clock time, so a deadline is treated as local time in the user's timezone
(User.timezone). That keeps Google Calendar and the Today page showing the
same time. Google Calendar is always sent/read with an explicit timezone.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def user_tz(user) -> ZoneInfo:
    try:
        return ZoneInfo(user.timezone or "UTC")
    except (ZoneInfoNotFoundError, ValueError, KeyError):
        return ZoneInfo("UTC")


def now_local(tz: ZoneInfo) -> datetime:
    """Current wall-clock time in tz, as a naive datetime."""
    return datetime.now(tz).replace(tzinfo=None)


def start_of_day(local: datetime) -> datetime:
    return local.replace(hour=0, minute=0, second=0, microsecond=0)


def to_aware(local: datetime, tz: ZoneInfo) -> datetime:
    return local.replace(tzinfo=tz)


def to_google(local: datetime, tz: ZoneInfo) -> dict:
    """Naive local wall time -> Google Calendar start/end object."""
    return {"dateTime": local.replace(microsecond=0).isoformat(), "timeZone": tz.key}


def rfc3339(local: datetime, tz: ZoneInfo) -> str:
    """Naive local wall time -> RFC 3339 string with offset (for timeMin/timeMax)."""
    return to_aware(local, tz).isoformat()


def from_google(point: dict, tz: ZoneInfo) -> tuple[datetime, bool]:
    """Google start/end object -> (naive local wall time, is_all_day)."""
    if point.get("dateTime"):
        parsed = datetime.fromisoformat(point["dateTime"].replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            return parsed, False
        return parsed.astimezone(tz).replace(tzinfo=None), False
    day = date.fromisoformat(point["date"])
    return datetime(day.year, day.month, day.day), True


def parse_user_datetime(value: str, tz: ZoneInfo) -> datetime:
    """Parse an ISO-8601 string from the assistant into naive local time.

    A string with an offset (e.g. "...Z" or "+05:30") is converted to the user's
    timezone; a naive string is taken to already be in the user's timezone.
    """
    parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(tz).replace(tzinfo=None)
    return parsed.replace(microsecond=0)


def parse_google_timestamp(value: str | None) -> datetime | None:
    """Google's `updated` field (RFC 3339, UTC) -> naive UTC datetime."""
    if not value:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed.astimezone(timezone.utc).replace(tzinfo=None)
