"""
Backfill: repair `Request.expense_ref_id` pointers to `bank_expenses` rows that
no longer exist ("dangling refs").

Found for 11 lemonaqua (tenant_id=3) requests paid 2026-09-02..09: each already
has `expense_ref_target="bank"` and a `vendor_ref` set from an earlier, correct
link, but `expense_ref_id` now points at a `BankExpense` row that doesn't exist
for that tenant — most likely the underlying statement rows for that period
were deleted and re-imported with new ids without the requests being updated.

Since these requests already carry the correct `vendor_ref` (unlike the
free-text-only lemonaqua requests handled by
lemonaqua_transfer_bank_expense_name_matching.py), repair is a direct
vendor_ref + exact amount + the same ±3 day payed_at window used elsewhere by
`reconcile_bank_expenses_by_vendor_amount_date`. Only repairs when exactly one
still-unclaimed candidate survives; anything else is reported, not guessed at.

Run with --dry-run (default) first, then --apply to write. A repair also
leaves a RequestComment from the system account (pk=1, displays as "Система"),
same convention as lemonaqua_transfer_bank_expense_name_matching.py.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from django.db.models import Exists, OuterRef

from apps.accounts.models import User
from apps.modules.bank_expenses.models import BankExpense
from apps.modules.requests.bank_expense_reconciliation import (
    BANK_EXPENSE_VENDOR_MATCH_WINDOW_DAYS,
    payed_at_to_date,
)
from apps.modules.requests.models import Request, RequestComment


@dataclass(frozen=True)
class RepairOutcome:
    request_id: int
    old_expense_ref_id: int
    amount: Decimal
    payed_date: date | None
    outcome: str  # "repaired" | "no_candidate" | "ambiguous" | "skipped"
    detail: str
    new_expense_ref_id: int | None = None


def _system_user() -> User | None:
    return User.objects.filter(pk=1).first()


def _dangling_bank_ref_requests():
    existing_expense = BankExpense.objects.filter(
        tenant_id=OuterRef("tenant_id"), id=OuterRef("expense_ref_id"),
    )
    return Request.objects.filter(
        expense_ref_target=Request.EXPENSE_REF_TARGET_BANK,
        expense_ref_id__isnull=False,
        vendor_ref_id__isnull=False,
        payed_at__isnull=False,
    ).filter(~Exists(existing_expense))


def _claimed_bank_expense_ids(*, tenant_id: int) -> set[int]:
    return set(
        Request.objects.filter(
            tenant_id=tenant_id,
            expense_ref_target=Request.EXPENSE_REF_TARGET_BANK,
            expense_ref_id__isnull=False,
        ).values_list("expense_ref_id", flat=True)
    )


def find_and_repair_dangling_bank_expense_refs(*, apply_changes: bool) -> list[RepairOutcome]:
    """
    Returns one RepairOutcome per request with a dangling bank expense_ref.
    When `apply_changes` is True, "repaired" outcomes are written. Safe to
    re-run: only ever touches requests whose current expense_ref_id still
    doesn't resolve to a real BankExpense row.
    """
    window = timedelta(days=BANK_EXPENSE_VENDOR_MATCH_WINDOW_DAYS)
    claimed_by_tenant: dict[int, set[int]] = {}

    results: list[RepairOutcome] = []
    for req in _dangling_bank_ref_requests().order_by("tenant_id", "payed_at", "id"):
        old_ref_id = req.expense_ref_id
        payed_date = payed_at_to_date(req.payed_at)
        if payed_date is None:
            results.append(
                RepairOutcome(req.id, old_ref_id, req.amount, payed_date, "skipped", "missing payed_at")
            )
            continue

        if req.tenant_id not in claimed_by_tenant:
            claimed_by_tenant[req.tenant_id] = _claimed_bank_expense_ids(tenant_id=req.tenant_id)
        claimed_expense_ids = claimed_by_tenant[req.tenant_id]

        candidates = list(
            BankExpense.objects.filter(
                tenant_id=req.tenant_id,
                vendor_id=req.vendor_ref_id,
                debit_turnover=req.amount,
                doc_date__gte=payed_date - window,
                doc_date__lte=payed_date + window,
            ).exclude(id__in=claimed_expense_ids)
        )
        if not candidates:
            results.append(
                RepairOutcome(
                    req.id, old_ref_id, req.amount, payed_date, "no_candidate",
                    f"no unclaimed BankExpense for vendor_id={req.vendor_ref_id} amount={req.amount} "
                    f"within +/-{BANK_EXPENSE_VENDOR_MATCH_WINDOW_DAYS}d of {payed_date}",
                )
            )
            continue
        if len(candidates) > 1:
            ids = ", ".join(str(c.id) for c in candidates)
            results.append(
                RepairOutcome(
                    req.id, old_ref_id, req.amount, payed_date, "ambiguous",
                    f"{len(candidates)} candidate BankExpense rows ({ids}) — resolve manually",
                )
            )
            continue

        expense = candidates[0]
        results.append(
            RepairOutcome(
                req.id, old_ref_id, req.amount, payed_date, "repaired",
                f"BankExpense {old_ref_id} (gone) -> {expense.id}",
                new_expense_ref_id=expense.id,
            )
        )
        claimed_expense_ids.add(expense.id)

        if apply_changes:
            updated = Request.objects.filter(pk=req.pk, expense_ref_id=old_ref_id).update(
                expense_ref_id=expense.id,
            )
            if not updated:
                claimed_expense_ids.discard(expense.id)
            else:
                system_user = _system_user()
                if system_user is not None:
                    RequestComment.objects.create(
                        request_id=req.pk,
                        created_by=system_user,
                        body=(
                            f"Ссылка на банковский расход исправлена автоматически: старый BankExpense "
                            f"#{old_ref_id} больше не существует, заявка перевязана на BankExpense "
                            f"#{expense.id} (тот же поставщик, сумма {req.amount}, дата в пределах "
                            f"{BANK_EXPENSE_VENDOR_MATCH_WINDOW_DAYS} дн. от даты оплаты)."
                        ),
                    )

    return results
