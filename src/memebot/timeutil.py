"""All episode dates refer to source publication dates in the configured timezone."""

from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

ZONE = "America/New_York"


def day_window(day: date, zone: str = ZONE) -> tuple[datetime, datetime]:
    tz = ZoneInfo(zone)
    return (
        datetime.combine(day, time.min, tz).astimezone(timezone.utc),
        datetime.combine(day + timedelta(days=1), time.min, tz).astimezone(timezone.utc),
    )


def yesterday(zone: str = ZONE) -> date:
    return datetime.now(ZoneInfo(zone)).date() - timedelta(days=1)


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_time(value: str) -> datetime:
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ValueError("Publication timestamps must include a timezone")
    return dt.astimezone(timezone.utc)
