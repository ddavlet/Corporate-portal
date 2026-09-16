# apps/modules/requests/card_expense_reconciliation.py
"""
Additive backfill: link unclaimed "Платежная карта" (corporate card
expense) Requests to unclaimed CardExpense rows by amount + a window
around the day the request was marked paid (`payed_at`). CardExpense has
no vendor to match on, so requests are grouped by amount only (see the
CARD adapter's `vendor_field=None` in expense_reconciliation_adapters.py).

Thin wrapper around expense_reconciliation_core.find_and_reconcile using
the CARD adapter, restricted to `missing`-only requests — unchanged
behavior for n8n_integration.views's automatic post-import hook. For the
full missing/dangling/mismatch pass across bank/cash/card, use the
`reconcile_expense_links` management command instead.
"""

from __future__ import annotations

from apps.modules.requests.expense_reconciliation_adapters import CARD
from apps.modules.requests.expense_reconciliation_core import EXPENSE_MATCH_WINDOW_DAYS, find_and_reconcile

# Kept for backward-compatible imports (same value as EXPENSE_MATCH_WINDOW_DAYS).
CARD_EXPENSE_AMOUNT_MATCH_WINDOW_DAYS = EXPENSE_MATCH_WINDOW_DAYS

__all__ = ["CARD_EXPENSE_AMOUNT_MATCH_WINDOW_DAYS", "reconcile_card_expenses_by_amount_date"]


def reconcile_card_expenses_by_amount_date(*, tenant) -> int:
    """
    Backfill `expense_ref_id`/`expense_ref_target` for unlinked "Платежная
    карта" requests. Returns the number of requests linked.
    """
    outcomes = find_and_reconcile(
        adapter=CARD,
        tenant=tenant,
        apply_changes=True,
        problems=frozenset({"missing"}),
        use_name_fallback=False,
    )
    return sum(1 for o in outcomes if o.outcome == "repaired")
