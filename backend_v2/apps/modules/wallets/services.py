"""
Balance math for wallets.

Calendar boundaries use Asia/Tashkent (local midnight Jan 1 → UTC for datetime fields).

current_balance = opening_balance (as of Jan 1 current year, stored on Wallet)
                + movements_net (YTD through "now" in Tashkent calendar year).

Full prior-year net (for suggested carry) is computed separately, not mixed into YTD.
"""

from __future__ import annotations

import zoneinfo
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from django.db.models import Q, Sum
from django.utils import timezone

from apps.modules.bank_expenses.models import BankExpense, BankRevenue
from apps.modules.cashier.models import CashExpense, CashRevenue
from apps.modules.corporate_card.models import CardExpense, CardRevenue

from apps.modules.wallets.models import Wallet

TASHKENT = zoneinfo.ZoneInfo("Asia/Tashkent")


def _now_tashkent() -> datetime:
    return timezone.now().astimezone(TASHKENT)


def _start_of_year_utc(year: int) -> datetime:
    local = datetime(year, 1, 1, 0, 0, 0, tzinfo=TASHKENT)
    return local.astimezone(zoneinfo.ZoneInfo("UTC"))


def _end_of_year_utc(year: int) -> datetime:
    local = datetime(year, 12, 31, 23, 59, 59, 999999, tzinfo=TASHKENT)
    return local.astimezone(zoneinfo.ZoneInfo("UTC"))


def ytd_bounds() -> tuple[datetime, datetime, int]:
    """Return (start_utc, now_utc_exclusive_cap, calendar_year_tashkent)."""
    now_t = _now_tashkent()
    y = now_t.year
    start = _start_of_year_utc(y)
    end_cap = timezone.now()
    return start, end_cap, y


def prior_year_bounds(prior_year: int) -> tuple[datetime, datetime]:
    return _start_of_year_utc(prior_year), _end_of_year_utc(prior_year)


def movements_net_cash_ytd(*, wallet: Wallet, start_utc: datetime, end_utc: datetime) -> Decimal:
    exp = (
        CashExpense.objects.filter(
            wallet=wallet,
            confirmed=True,
            expense_at__gte=start_utc,
            expense_at__lte=end_utc,
        ).aggregate(s=Sum("amount"))["s"]
        or Decimal("0")
    )
    rev = (
        CashRevenue.objects.filter(
            wallet=wallet,
            confirmed=True,
        )
        .filter(
            Q(revenue_at__gte=start_utc, revenue_at__lte=end_utc)
            | Q(revenue_at__isnull=True, created_at__gte=start_utc, created_at__lte=end_utc)
        )
        .aggregate(s=Sum("total_sum"))["s"]
        or Decimal("0")
    )
    return rev - exp


def movements_net_bank_ytd(*, wallet: Wallet, year: int, end_date: date) -> Decimal:
    start_d = date(year, 1, 1)
    exp = (
        BankExpense.objects.filter(
            wallet=wallet,
            doc_date__gte=start_d,
            doc_date__lte=end_date,
        ).aggregate(s=Sum("debit_turnover"))["s"]
        or Decimal("0")
    )
    rev = (
        BankRevenue.objects.filter(
            wallet=wallet,
            doc_date__gte=start_d,
            doc_date__lte=end_date,
        ).aggregate(s=Sum("kredit_turnover"))["s"]
        or Decimal("0")
    )
    return rev - exp


def movements_net_card_ytd(*, wallet: Wallet, start_utc: datetime, end_utc: datetime) -> Decimal:
    exp = (
        CardExpense.objects.filter(
            wallet=wallet,
            expense_at__gte=start_utc,
            expense_at__lte=end_utc,
        ).aggregate(s=Sum("amount"))["s"]
        or Decimal("0")
    )
    rev = (
        CardRevenue.objects.filter(
            wallet=wallet,
            confirmed=True,
            revenue_at__gte=start_utc,
            revenue_at__lte=end_utc,
        ).aggregate(s=Sum("amount"))["s"]
        or Decimal("0")
    )
    return rev - exp


def movements_net_full_year_cash(*, wallet: Wallet, year: int) -> Decimal:
    start, end = prior_year_bounds(year)
    exp = (
        CashExpense.objects.filter(
            wallet=wallet,
            confirmed=True,
            expense_at__gte=start,
            expense_at__lte=end,
        ).aggregate(s=Sum("amount"))["s"]
        or Decimal("0")
    )
    rev = (
        CashRevenue.objects.filter(
            wallet=wallet,
            confirmed=True,
        )
        .filter(
            Q(revenue_at__gte=start, revenue_at__lte=end)
            | Q(revenue_at__isnull=True, created_at__gte=start, created_at__lte=end)
        )
        .aggregate(s=Sum("total_sum"))["s"]
        or Decimal("0")
    )
    return rev - exp


def movements_net_full_year_bank(*, wallet: Wallet, year: int) -> Decimal:
    start_d = date(year, 1, 1)
    end_d = date(year, 12, 31)
    exp = (
        BankExpense.objects.filter(wallet=wallet, doc_date__gte=start_d, doc_date__lte=end_d).aggregate(
            s=Sum("debit_turnover")
        )["s"]
        or Decimal("0")
    )
    rev = (
        BankRevenue.objects.filter(wallet=wallet, doc_date__gte=start_d, doc_date__lte=end_d).aggregate(
            s=Sum("kredit_turnover")
        )["s"]
        or Decimal("0")
    )
    return rev - exp


def movements_net_full_year_card(*, wallet: Wallet, year: int) -> Decimal:
    start, end = prior_year_bounds(year)
    exp = (
        CardExpense.objects.filter(
            wallet=wallet,
            expense_at__gte=start,
            expense_at__lte=end,
        ).aggregate(s=Sum("amount"))["s"]
        or Decimal("0")
    )
    rev = (
        CardRevenue.objects.filter(
            wallet=wallet,
            confirmed=True,
            revenue_at__gte=start,
            revenue_at__lte=end,
        ).aggregate(s=Sum("amount"))["s"]
        or Decimal("0")
    )
    return rev - exp


def wallet_balance_payload(*, wallet: Wallet) -> dict[str, Any]:
    start_utc, end_utc, y = ytd_bounds()
    now_t = _now_tashkent()

    if wallet.wallet_type == Wallet.Type.CASH:
        net = movements_net_cash_ytd(wallet=wallet, start_utc=start_utc, end_utc=end_utc)
    elif wallet.wallet_type == Wallet.Type.BANK:
        # Upper bound for bank YTD: «сегодня» по календарю Ташкента (doc_date — date).
        net = movements_net_bank_ytd(wallet=wallet, year=y, end_date=now_t.date())
    else:
        net = movements_net_card_ytd(wallet=wallet, start_utc=start_utc, end_utc=end_utc)

    ob = wallet.opening_balance
    prior_y = _now_tashkent().year - 1
    if wallet.wallet_type == Wallet.Type.CASH:
        prior_full = movements_net_full_year_cash(wallet=wallet, year=prior_y)
    elif wallet.wallet_type == Wallet.Type.BANK:
        prior_full = movements_net_full_year_bank(wallet=wallet, year=prior_y)
    else:
        prior_full = movements_net_full_year_card(wallet=wallet, year=prior_y)

    return {
        "wallet_id": wallet.id,
        "opening_balance": str(ob),
        "movements_net": str(net),
        "current_balance": str(ob + net),
        "currency": wallet.currency,
        "prior_calendar_year": prior_y,
        "prior_calendar_year_net": str(prior_full),
    }


def balances_for_tenant_channel(*, tenant_id: int, wallet_type: str) -> list[dict[str, Any]]:
    qs = Wallet.objects.filter(tenant_id=tenant_id, wallet_type=wallet_type).select_related(
        "cash_register",
        "bank_account",
        "corporate_card_account",
    )
    if wallet_type == Wallet.Type.CASH:
        qs = qs.filter(is_visible_in_cash_section=True)
    out: list[dict[str, Any]] = []
    for w in qs:
        base = wallet_balance_payload(wallet=w)
        anchor_name = ""
        anchor_id = None
        anchor_active = True
        if w.cash_register_id:
            reg = w.cash_register
            anchor_id = reg.id
            anchor_name = (reg.name or "").strip() or reg.currency
            anchor_active = reg.is_active
        elif w.bank_account_id:
            anchor_id = w.bank_account.id
            anchor_name = w.bank_account.label
        elif w.corporate_card_account_id:
            c = w.corporate_card_account
            anchor_id = c.id
            anchor_name = (c.label or "").strip() or c.currency

        base.update(
            {
                "cash_register_id": w.cash_register_id,
                "bank_account_id": w.bank_account_id,
                "corporate_card_account_id": w.corporate_card_account_id,
                "display_name": anchor_name,
                "anchor_is_active": anchor_active,
            }
        )
        out.append(base)
    return out
