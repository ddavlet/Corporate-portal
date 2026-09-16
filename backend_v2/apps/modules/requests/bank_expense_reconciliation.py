"""
Additive backfill: link Transfer/Topup Requests that have no manual doc_no
to unclaimed BankExpense rows, by vendor + exact amount + a narrow window
around the day the request was marked paid (`payed_at`).

This is a thin wrapper around expense_reconciliation_core.find_and_reconcile
using the BANK adapter, restricted to `missing`-only requests with no
vendor name-fallback — so its behavior (and this function's name/signature)
is unchanged for n8n_integration.views's automatic post-import hook. For
the full missing/dangling/mismatch pass across bank/cash/card with
tenant/date/type filters, use the `reconcile_expense_links` management
command instead.
"""

from __future__ import annotations

from apps.modules.requests.expense_reconciliation_adapters import BANK
from apps.modules.requests.expense_reconciliation_core import (
    EXPENSE_MATCH_WINDOW_DAYS,
    find_and_reconcile,
    payed_at_to_date,
)

# Kept for backward-compatible imports (same value as EXPENSE_MATCH_WINDOW_DAYS).
BANK_EXPENSE_VENDOR_MATCH_WINDOW_DAYS = EXPENSE_MATCH_WINDOW_DAYS

__all__ = [
    "BANK_EXPENSE_VENDOR_MATCH_WINDOW_DAYS",
    "payed_at_to_date",
    "reconcile_bank_expenses_by_vendor_amount_date",
]


def reconcile_bank_expenses_by_vendor_amount_date(*, tenant) -> int:
    """
    Backfill `expense_ref_id`/`expense_ref_target` for unlinked Transfer/Topup
    requests. Returns the number of requests linked.
    """
    outcomes = find_and_reconcile(
        adapter=BANK,
        tenant=tenant,
        apply_changes=True,
        problems=frozenset({"missing"}),
        use_name_fallback=False,
    )
    return sum(1 for o in outcomes if o.outcome == "repaired")
