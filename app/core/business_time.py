"""Business dates: policies, tiers and other dated rules are written in the tenant's local
calendar, while timestamps are stored in UTC. An order placed at 01:00 IST on the 26th is a
26th order even though its UTC date is the 25th."""

from datetime import date, datetime
from zoneinfo import ZoneInfo

DEFAULT_TIMEZONE = "Asia/Kolkata"


def business_date(moment: datetime, settings: dict) -> date:
    """The calendar date of `moment` in the tenant's `business_timezone` setting."""
    tz = ZoneInfo(settings.get("business_timezone") or DEFAULT_TIMEZONE)
    if moment.tzinfo is None:  # stored timestamps are tz-aware; a naive one is UTC
        raise ValueError("business_date needs a timezone-aware datetime")
    return moment.astimezone(tz).date()
