"""Правила «месяца назначения» для выплат по инвестициям — те же, что на фронте в billingMonth.ts."""

from __future__ import annotations

from datetime import date

from apps.modules.investments.services import tashkent_today


def month_first_day(d: date) -> date:
    return date(d.year, d.month, 1)


def add_calendar_months(month_first: date, delta: int) -> date:
    total = month_first.year * 12 + (month_first.month - 1) + delta
    y, m0 = divmod(total, 12)
    return date(y, m0 + 1, 1)


def allowed_accrual_month_starts(*, today: date | None = None) -> list[date]:
    """
    До 20-го включительно: прошлый, текущий и следующий календарный месяц.
    С 21-го: только текущий и следующий.
    """
    d = today or tashkent_today()
    current = month_first_day(d)
    previous = add_calendar_months(current, -1)
    next_m = add_calendar_months(current, 1)
    if d.day <= 20:
        return [previous, current, next_m]
    return [current, next_m]


def is_accrual_month_allowed(candidate: date, *, today: date | None = None) -> bool:
    cand = month_first_day(candidate)
    return cand in allowed_accrual_month_starts(today=today)
