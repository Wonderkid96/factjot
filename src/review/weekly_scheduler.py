from __future__ import annotations

from datetime import datetime, timedelta, timezone

WEEKDAY_MAP = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}


def next_weekday_slot(day_code: str, hour_utc: int, from_dt: datetime | None = None) -> str:
    now = from_dt or datetime.now(timezone.utc)
    target_day = WEEKDAY_MAP[day_code.lower()]
    days_ahead = (target_day - now.weekday()) % 7
    if days_ahead == 0 and now.hour >= hour_utc:
        days_ahead = 7
    target = (now + timedelta(days=days_ahead)).replace(hour=hour_utc, minute=0, second=0, microsecond=0)
    return target.isoformat().replace("+00:00", "Z")
