"""
Per-expense-type configuration for the generic reconciliation engine in
expense_reconciliation_core.py. Adding a new expense type means adding a
new adapter here — the engine itself never needs to change.
"""

from __future__ import annotations

from dataclasses import dataclass

from apps.modules.bank_expenses.models import BankExpense
from apps.modules.cashier.models import CashExpense
from apps.modules.corporate_card.models import CardExpense
from apps.modules.requests.models import Request
from apps.modules.vendors.models import Vendor


@dataclass(frozen=True)
class ExpenseTypeAdapter:
    key: str
    model: type
    ref_target: str
    payment_types: tuple[str, ...]
    amount_field: str
    date_field: str
    date_is_datetime: bool
    vendor_field: str | None
    vendor_kind: str | None
    supports_name_fallback: bool


BANK = ExpenseTypeAdapter(
    key="bank",
    model=BankExpense,
    ref_target=Request.EXPENSE_REF_TARGET_BANK,
    payment_types=(Request.PAYMENT_TYPE_TRANSFER, Request.PAYMENT_TYPE_TOPUP),
    amount_field="debit_turnover",
    date_field="doc_date",
    date_is_datetime=False,
    vendor_field="vendor_id",
    vendor_kind=Vendor.KIND_TRANSFER,
    supports_name_fallback=True,
)

CASH = ExpenseTypeAdapter(
    key="cash",
    model=CashExpense,
    ref_target=Request.EXPENSE_REF_TARGET_CASH,
    payment_types=(Request.PAYMENT_TYPE_CASH,),
    amount_field="amount",
    date_field="expense_at",
    date_is_datetime=True,
    vendor_field="vendor_id",
    vendor_kind=Vendor.KIND_CASH,
    supports_name_fallback=True,
)

CARD = ExpenseTypeAdapter(
    key="card",
    model=CardExpense,
    ref_target=Request.EXPENSE_REF_TARGET_CARD,
    payment_types=(Request.PAYMENT_TYPE_CARD,),
    amount_field="amount",
    date_field="expense_at",
    date_is_datetime=True,
    vendor_field=None,
    vendor_kind=None,
    supports_name_fallback=False,
)

ALL_ADAPTERS: dict[str, ExpenseTypeAdapter] = {a.key: a for a in (BANK, CASH, CARD)}
