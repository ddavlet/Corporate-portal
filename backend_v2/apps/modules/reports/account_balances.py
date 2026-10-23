"""«Остатки по счетам»: the balance of one wallet day by day, to find the day it stopped matching the bank.

The rules are the ones of the wallet balances on the Bank / Cash / Card pages (`wallets.services`):
`Wallet.opening_balance` is the balance at the start of 1 January of the current Tashkent year, cash and card
operations count only when confirmed, cash expense only when confirmed. A balance before that day is the opening
balance minus what moved between that day and 1 January.

Unconfirmed operations are listed (`counted: false`) but never change a balance: they are the usual reason why
the portal and the bank disagree.

A wallet type is shown only to users who may open its own page (the module of its `MovementSource`).

One `MovementSource` per wallet type; a new account type is a new subclass plus one entry in `MOVEMENT_SOURCES`.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Any

from django.db.models import Min, Q, QuerySet, Sum
from django.db.models.functions import Coalesce

from apps.modules.bank_expenses.models import BankExpense, BankRevenue
from apps.modules.cashier.models import CashExpense, CashRevenue
from apps.modules.corporate_card.models import CardExpense, CardRevenue
from apps.modules.wallets.calendar_utils import TASHKENT, now_tashkent
from apps.modules.wallets.models import Wallet

ZERO = Decimal("0")
DIRECTION_IN = "in"
DIRECTION_OUT = "out"

TYPE_LABELS = {
    Wallet.Type.BANK: "Банк",
    Wallet.Type.CASH: "Касса",
    Wallet.Type.CORPORATE_CARD: "Корпоративная карта",
}
TYPE_ORDER = (Wallet.Type.BANK, Wallet.Type.CASH, Wallet.Type.CORPORATE_CARD)


class WalletNotFound(LookupError):
    """No wallet with this id in the tenant."""


@dataclass(frozen=True)
class Movement:
    day: date
    at: datetime | None
    direction: str
    amount: Decimal
    title: str
    counterparty: str
    document: str
    source: str
    source_id: int
    counted: bool

    @property
    def signed(self) -> Decimal:
        return self.amount if self.direction == DIRECTION_IN else -self.amount


def _start_utc(day: date) -> datetime:
    return datetime.combine(day, time.min, tzinfo=TASHKENT)


def _local_day(value: datetime) -> date:
    return value.astimezone(TASHKENT).date()


def _sum(qs: QuerySet, field: str) -> Decimal:
    return qs.aggregate(s=Sum(field))["s"] or ZERO


def _earliest(*values: date | None) -> date | None:
    present = [value for value in values if value is not None]
    return min(present) if present else None


class MovementSource(ABC):
    """Money in and out of one wallet type. Days are Tashkent calendar days, both ends included."""

    wallet_type: str
    # The module whose page shows these wallets; its access rules decide who sees them here.
    module_key: str

    @abstractmethod
    def net(self, wallet: Wallet, start: date, end: date) -> Decimal:
        """Counted income minus counted expense."""

    @abstractmethod
    def movements(self, wallet: Wallet, start: date, end: date) -> list[Movement]:
        """Every operation of the days, counted or not."""

    @abstractmethod
    def first_day(self, wallet: Wallet) -> date | None:
        """The day of the wallet's earliest operation."""


class BankMovementSource(MovementSource):
    """Bank statement lines by document date (as the bank balances count them); every line counts."""

    wallet_type = Wallet.Type.BANK
    module_key = "bank"

    def net(self, wallet: Wallet, start: date, end: date) -> Decimal:
        days = {"wallet": wallet, "doc_date__gte": start, "doc_date__lte": end}
        income = _sum(BankRevenue.objects.filter(**days), "kredit_turnover")
        expense = _sum(BankExpense.objects.filter(**days), "debit_turnover")
        return income - expense

    def movements(self, wallet: Wallet, start: date, end: date) -> list[Movement]:
        days = {"wallet": wallet, "doc_date__gte": start, "doc_date__lte": end}
        out = [
            Movement(
                day=row.doc_date,
                at=None,
                direction=DIRECTION_IN,
                amount=row.kredit_turnover,
                title=row.payment_purpose,
                counterparty=row.account_name,
                document=row.doc_no,
                source="bank_revenue",
                source_id=row.id,
                counted=True,
            )
            for row in BankRevenue.objects.filter(**days).order_by("doc_date", "id")
        ]
        out += [
            Movement(
                day=row.doc_date,
                at=None,
                direction=DIRECTION_OUT,
                amount=row.debit_turnover,
                title=row.payment_purpose,
                counterparty=row.vendor.name if row.vendor else "",
                document=row.doc_no,
                source="bank_expense",
                source_id=row.id,
                counted=True,
            )
            for row in BankExpense.objects.filter(**days).select_related("vendor").order_by("doc_date", "id")
        ]
        return out

    def first_day(self, wallet: Wallet) -> date | None:
        return _earliest(
            BankRevenue.objects.filter(wallet=wallet).aggregate(d=Min("doc_date"))["d"],
            BankExpense.objects.filter(wallet=wallet).aggregate(d=Min("doc_date"))["d"],
        )


def _cash_revenue_in(start: date, end: date) -> Q:
    """A cash revenue without `revenue_at` falls on the day it was entered (as in `wallets.services`)."""
    lower, upper = _start_utc(start), _start_utc(end + timedelta(days=1))
    return Q(revenue_at__gte=lower, revenue_at__lt=upper) | Q(
        revenue_at__isnull=True, created_at__gte=lower, created_at__lt=upper
    )


class CashMovementSource(MovementSource):
    wallet_type = Wallet.Type.CASH
    module_key = "cash"

    def net(self, wallet: Wallet, start: date, end: date) -> Decimal:
        lower, upper = _start_utc(start), _start_utc(end + timedelta(days=1))
        income = _sum(
            CashRevenue.objects.filter(wallet=wallet, confirmed=True).filter(_cash_revenue_in(start, end)), "total_sum"
        )
        expense = _sum(
            CashExpense.objects.filter(wallet=wallet, confirmed=True, expense_at__gte=lower, expense_at__lt=upper),
            "amount",
        )
        return income - expense

    def movements(self, wallet: Wallet, start: date, end: date) -> list[Movement]:
        lower, upper = _start_utc(start), _start_utc(end + timedelta(days=1))
        out = []
        for row in CashRevenue.objects.filter(wallet=wallet).filter(_cash_revenue_in(start, end)).order_by("id"):
            at = row.revenue_at or row.created_at
            out.append(
                Movement(
                    day=_local_day(at),
                    at=at,
                    direction=DIRECTION_IN,
                    amount=row.total_sum,
                    title=row.operation or row.comment,
                    counterparty=row.counterparty,
                    document=row.external_id,
                    source="cash_revenue",
                    source_id=row.id,
                    counted=row.confirmed,
                )
            )
        for row in (
            CashExpense.objects.filter(wallet=wallet, expense_at__gte=lower, expense_at__lt=upper)
            .select_related("vendor")
            .order_by("expense_at", "id")
        ):
            out.append(
                Movement(
                    day=_local_day(row.expense_at),
                    at=row.expense_at,
                    direction=DIRECTION_OUT,
                    amount=row.amount,
                    title=row.title or row.note,
                    counterparty=row.vendor.name if row.vendor else "",
                    document=row.external_id,
                    source="cash_expense",
                    source_id=row.id,
                    counted=row.confirmed,
                )
            )
        return out

    def first_day(self, wallet: Wallet) -> date | None:
        revenue = CashRevenue.objects.filter(wallet=wallet).aggregate(d=Min(Coalesce("revenue_at", "created_at")))["d"]
        expense = CashExpense.objects.filter(wallet=wallet).aggregate(d=Min("expense_at"))["d"]
        return _earliest(*(_local_day(value) for value in (revenue, expense) if value is not None))


class CardMovementSource(MovementSource):
    """Card expenses always count; card revenues (top-ups) only when confirmed."""

    wallet_type = Wallet.Type.CORPORATE_CARD
    module_key = "corporate_card"

    def net(self, wallet: Wallet, start: date, end: date) -> Decimal:
        lower, upper = _start_utc(start), _start_utc(end + timedelta(days=1))
        income = _sum(
            CardRevenue.objects.filter(wallet=wallet, confirmed=True, revenue_at__gte=lower, revenue_at__lt=upper),
            "total_sum",
        )
        expense = _sum(CardExpense.objects.filter(wallet=wallet, expense_at__gte=lower, expense_at__lt=upper), "amount")
        return income - expense

    def movements(self, wallet: Wallet, start: date, end: date) -> list[Movement]:
        lower, upper = _start_utc(start), _start_utc(end + timedelta(days=1))
        out = [
            Movement(
                day=_local_day(row.revenue_at),
                at=row.revenue_at,
                direction=DIRECTION_IN,
                amount=row.total_sum,
                title=row.operation or row.comment,
                counterparty=row.counterparty,
                document=row.external_id,
                source="card_revenue",
                source_id=row.id,
                counted=row.confirmed,
            )
            for row in CardRevenue.objects.filter(wallet=wallet, revenue_at__gte=lower, revenue_at__lt=upper).order_by(
                "revenue_at", "id"
            )
        ]
        out += [
            Movement(
                day=_local_day(row.expense_at),
                at=row.expense_at,
                direction=DIRECTION_OUT,
                amount=row.amount,
                title=row.title or row.note,
                counterparty="",
                document=row.external_id,
                source="card_expense",
                source_id=row.id,
                counted=True,
            )
            for row in CardExpense.objects.filter(wallet=wallet, expense_at__gte=lower, expense_at__lt=upper).order_by(
                "expense_at", "id"
            )
        ]
        return out

    def first_day(self, wallet: Wallet) -> date | None:
        return _earliest(
            *(
                _local_day(value)
                for value in (
                    CardRevenue.objects.filter(wallet=wallet).aggregate(d=Min("revenue_at"))["d"],
                    CardExpense.objects.filter(wallet=wallet).aggregate(d=Min("expense_at"))["d"],
                )
                if value is not None
            )
        )


MOVEMENT_SOURCES: dict[str, MovementSource] = {
    source.wallet_type: source for source in (BankMovementSource(), CashMovementSource(), CardMovementSource())
}


def opening_anchor_day(today: date | None = None) -> date:
    """The day `Wallet.opening_balance` describes: 1 January of the current Tashkent year."""
    return date((today or now_tashkent().date()).year, 1, 1)


def balance_at_start_of(wallet: Wallet, day: date, *, source: MovementSource, anchor: date) -> Decimal:
    if day == anchor:
        return wallet.opening_balance
    if day > anchor:
        return wallet.opening_balance + source.net(wallet, anchor, day - timedelta(days=1))
    return wallet.opening_balance - source.net(wallet, day, anchor - timedelta(days=1))


def wallet_display_name(wallet: Wallet) -> str:
    if wallet.cash_register_id:
        return (wallet.cash_register.name or "").strip() or wallet.currency
    if wallet.bank_account_id:
        return (wallet.bank_account.label or "").strip() or "Банковский счёт"
    if wallet.corporate_card_account_id:
        return (wallet.corporate_card_account.label or "").strip() or wallet.currency
    return wallet.currency


def allowed_wallet_types(*, user, tenant) -> list[str]:
    """Wallet types whose own module (Bank, Cash, Corporate card) the user may open."""
    from apps.tenants.permissions import has_effective_module_access

    return [
        source.wallet_type
        for source in MOVEMENT_SOURCES.values()
        if has_effective_module_access(user=user, tenant=tenant, module_key=source.module_key)
    ]


def _wallet_qs(tenant_id: int, wallet_types: list[str]) -> QuerySet:
    types = [wallet_type for wallet_type in wallet_types if wallet_type in MOVEMENT_SOURCES]
    return Wallet.objects.filter(tenant_id=tenant_id, wallet_type__in=types).select_related(
        "cash_register", "bank_account", "corporate_card_account"
    )


def account_to_dict(wallet: Wallet) -> dict[str, Any]:
    return {
        "wallet_id": wallet.id,
        "wallet_type": wallet.wallet_type,
        "type_label": TYPE_LABELS.get(wallet.wallet_type, wallet.wallet_type),
        "name": wallet_display_name(wallet),
        "currency": wallet.currency,
        "account_no": wallet.bank_account.account_no if wallet.bank_account_id else "",
        "hidden": wallet.wallet_type == Wallet.Type.CASH and not wallet.is_visible_in_cash_section,
    }


def list_balance_accounts(*, tenant_id: int, wallet_types: list[str]) -> list[dict[str, Any]]:
    """The tenant's wallets of these types, bank first, then cash, then cards."""
    wallets = sorted(_wallet_qs(tenant_id, wallet_types), key=lambda w: (TYPE_ORDER.index(w.wallet_type), w.currency != "UZS", w.id))
    return [account_to_dict(wallet) for wallet in wallets]


def _operation_dict(movement: Movement, balance_after: Decimal | None) -> dict[str, Any]:
    return {
        "source": movement.source,
        "id": movement.source_id,
        "date": movement.day.isoformat(),
        "at": movement.at.astimezone(TASHKENT).isoformat() if movement.at else None,
        "direction": movement.direction,
        "amount": str(movement.amount),
        "title": movement.title,
        "counterparty": movement.counterparty,
        "document": movement.document,
        "counted": movement.counted,
        "balance_after": str(balance_after) if balance_after is not None else None,
    }


def _ordered(movements: list[Movement]) -> list[Movement]:
    # Bank lines have no time: within a day income goes before expense, then the order they were loaded in.
    return sorted(
        movements,
        key=lambda m: (m.day, m.at.timestamp() if m.at else 0.0, m.direction != DIRECTION_IN, m.source_id),
    )


def build_account_balances(
    *,
    tenant_id: int,
    wallet_id: int,
    date_from: date | None,
    date_to: date,
    wallet_types: list[str],
    today: date | None = None,
) -> dict[str, Any]:
    """The wallet's balance at the start and end of the period and of every day with operations in it.

    Without `date_from` the period starts at the wallet's first operation («на дату»: everything up to `date_to`).
    A wallet of another company, or of a type outside `wallet_types`, is `WalletNotFound`.
    """
    wallet = _wallet_qs(tenant_id, wallet_types).filter(id=wallet_id).first()
    if wallet is None:
        raise WalletNotFound(wallet_id)
    source = MOVEMENT_SOURCES[wallet.wallet_type]
    anchor = opening_anchor_day(today)
    start = date_from or _earliest(source.first_day(wallet), date_to) or date_to
    start = min(start, date_to)

    opening = balance_at_start_of(wallet, start, source=source, anchor=anchor)
    by_day: dict[date, list[Movement]] = defaultdict(list)
    for movement in _ordered(source.movements(wallet, start, date_to)):
        by_day[movement.day].append(movement)

    balance = opening
    income = expense = ZERO
    pending_in = pending_out = ZERO
    pending_count = 0
    days: list[dict[str, Any]] = []
    for day in sorted(by_day):
        day_opening = balance
        day_in = day_out = ZERO
        operations = []
        for movement in by_day[day]:
            if movement.counted:
                balance += movement.signed
                if movement.direction == DIRECTION_IN:
                    day_in += movement.amount
                else:
                    day_out += movement.amount
                operations.append(_operation_dict(movement, balance))
                continue
            pending_count += 1
            if movement.direction == DIRECTION_IN:
                pending_in += movement.amount
            else:
                pending_out += movement.amount
            operations.append(_operation_dict(movement, None))
        income += day_in
        expense += day_out
        days.append(
            {
                "date": day.isoformat(),
                "opening": str(day_opening),
                "income": str(day_in),
                "expense": str(day_out),
                "closing": str(balance),
                "operations": operations,
            }
        )

    return {
        "account": account_to_dict(wallet),
        "date_from": start.isoformat(),
        "date_to": date_to.isoformat(),
        "since_first_operation": date_from is None,
        "opening_balance_day": anchor.isoformat(),
        "opening": str(opening),
        "income": str(income),
        "expense": str(expense),
        "closing": str(balance),
        "operations_count": sum(len(day["operations"]) for day in days),
        "unconfirmed": {"count": pending_count, "income": str(pending_in), "expense": str(pending_out)},
        "days": days,
    }
