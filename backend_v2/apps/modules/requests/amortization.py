from __future__ import annotations

from datetime import date
from decimal import Decimal, ROUND_DOWN

from apps.modules.requests.models import Request


def is_request_amortized(request_obj: Request) -> bool:
    return int(request_obj.amortization_months or 0) > 1


def effective_amortization_start_date(request_obj: Request) -> date:
    start = request_obj.amortization_start_date or request_obj.billing_date
    return date(start.year, start.month, 1)


def _month_shift(month_anchor: date, delta_months: int) -> date:
    total_months = month_anchor.year * 12 + (month_anchor.month - 1) + delta_months
    year, month_zero_based = divmod(total_months, 12)
    return date(year, month_zero_based + 1, 1)


def build_amortization_schedule_rows(request_obj: Request) -> list[dict]:
    months = int(request_obj.amortization_months or 0)
    if months <= 1:
        return []

    amount = Decimal(request_obj.amount or Decimal("0"))
    monthly_base = (amount / months).quantize(Decimal("0.01"), rounding=ROUND_DOWN)
    monthly_last = amount - monthly_base * (months - 1)
    start_date = effective_amortization_start_date(request_obj)
    rows: list[dict] = []

    for idx in range(1, months + 1):
        row_amount = monthly_last if idx == months else monthly_base
        rows.append(
            {
                "period_index": idx,
                "period_month": _month_shift(start_date, idx - 1).isoformat(),
                "monthly_amount": str(row_amount),
            }
        )
    return rows
