"""
Timezone utilities for wallet balance calculations.

All calendar boundaries use Asia/Tashkent local midnight converted to UTC,
because datetime fields are stored as UTC but business logic follows local calendar year.
"""

from __future__ import annotations

import zoneinfo
from datetime import datetime

from django.utils import timezone

TASHKENT = zoneinfo.ZoneInfo("Asia/Tashkent")
_UTC = zoneinfo.ZoneInfo("UTC")


def now_tashkent() -> datetime:
    return timezone.now().astimezone(TASHKENT)


def start_of_year_utc(year: int) -> datetime:
    return datetime(year, 1, 1, 0, 0, 0, tzinfo=TASHKENT).astimezone(_UTC)


def end_of_year_utc(year: int) -> datetime:
    return datetime(year, 12, 31, 23, 59, 59, 999999, tzinfo=TASHKENT).astimezone(_UTC)


def ytd_bounds() -> tuple[datetime, datetime, int]:
    """Return (start_utc, now_utc_exclusive_cap, calendar_year_tashkent)."""
    now_t = now_tashkent()
    y = now_t.year
    return start_of_year_utc(y), timezone.now(), y


def prior_year_bounds(prior_year: int) -> tuple[datetime, datetime]:
    return start_of_year_utc(prior_year), end_of_year_utc(prior_year)
