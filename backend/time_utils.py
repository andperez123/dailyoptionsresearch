from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from email.utils import parsedate_to_datetime
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def utc_now_iso() -> str:
    return utc_now().isoformat()


def parse_datetime(value: str | None) -> datetime:
    if not value:
        return utc_now()
    normalized = value.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def parse_rss_datetime(value: str | None) -> datetime:
    if not value:
        return utc_now()
    try:
        parsed = parsedate_to_datetime(value)
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except (TypeError, ValueError, IndexError):
        return utc_now()


def market_status_now() -> str:
    now_et = utc_now().astimezone(ET)
    if now_et.weekday() >= 5:
        return "closed_weekend"

    market_open = time(9, 30)
    market_close = time(16, 0)
    pre_market_open = time(4, 0)
    current = now_et.time()

    if market_open <= current < market_close:
        return "open"
    if pre_market_open <= current < market_open:
        return "pre_market"
    return "closed"
