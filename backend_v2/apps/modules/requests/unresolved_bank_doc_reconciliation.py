"""
Relink PAYED Transfer/Topup Requests whose manually-typed bank doc number
(`expense_id`) never resolved to a BankExpense — typically because the
cashier typed a bank-client draft number or a typo (e.g. "25" instead of
"205") — so `expense_ref_id` stayed empty.

expense_reconciliation_core deliberately skips these requests (a typed
`expense_id` is treated as authoritative), so they stay "without expense"
forever. This pass handles exactly that gap, in two steps per request:

  1. Re-try the regular doc_no + year + amount resolution (the bank row may
     have been imported after the request was paid).
  2. Otherwise, match by exact amount within ±EXPENSE_MATCH_WINDOW_DAYS of
     `payed_at` among unclaimed BankExpense rows. Vendor is NOT required:
     e.g. dividend card payouts are booked in the bank feed under the
     acquiring bank ("ANOR BANK"), not the payee on the request. Vendor
     differences are reported for review instead.

Same conservative rule as the core engine: 0 or >1 equally-close candidates
are reported, never guessed. On write, `expense_id` is replaced with the
real doc number and a RequestComment from "Система" records the old value.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal

from apps.modules.bank_expenses.models import BankExpense
from apps.modules.requests.command_options import system_user
from apps.modules.requests.expense_reconciliation_adapters import BANK
from apps.modules.requests.expense_reconciliation_core import (
    EXPENSE_MATCH_WINDOW_DAYS,
    _amount_by_expense_id,
    _claimed_expense_ids,
    _greedy_nearest_date_matches,
    payed_at_to_date,
)
from apps.modules.requests.expense_refs import resolve_request_expense_ref
from apps.modules.requests.models import Request, RequestComment


@dataclass(frozen=True)
class UnresolvedDocOutcome:
    request_id: int
    typed_doc_no: str
    amount: Decimal
    outcome: str  # "linked_by_doc_no" | "linked_by_amount_date" | "no_candidate" | "ambiguous" | "skipped"
    detail: str
    expense_id: int | None = None
    expense_doc_no: str | None = None
    vendor_differs: bool = False


def _unresolved_requests(*, tenant, date_from: int | None, date_to: int | None):
    qs = (
        Request.objects.filter(
            tenant=tenant,
            status=Request.STATUS_PAYED,
            payment_type__in=BANK.payment_types,
            payed_at__isnull=False,
            expense_ref_id__isnull=True,
        )
        .exclude(expense_id__isnull=True)
        .exclude(expense_id="")
    )
    if date_from is not None:
        qs = qs.filter(payed_at__gte=date_from)
    if date_to is not None:
        qs = qs.filter(payed_at__lte=date_to)
    return qs.order_by("payed_at", "id")


def _link(*, request: Request, expense: BankExpense, how: str) -> bool:
    new_doc_no = expense.doc_no or request.expense_id
    updated = Request.objects.filter(
        pk=request.pk, tenant_id=request.tenant_id, expense_ref_id__isnull=True, expense_id=request.expense_id,
    ).update(expense_ref_id=expense.id, expense_ref_target=Request.EXPENSE_REF_TARGET_BANK, expense_id=new_doc_no)
    if not updated:
        return False
    author = system_user()
    if author is not None:
        if how == "linked_by_doc_no":
            reason = f"по номеру документа №{request.expense_id} (банковская выписка загрузилась позже оплаты)"
        else:
            reason = (
                f"по сумме {request.amount} и дате (±{EXPENSE_MATCH_WINDOW_DAYS} дн. от оплаты): "
                f"в заявке был указан №{request.expense_id}, которого нет в выписке"
            )
        RequestComment.objects.create(
            request_id=request.pk,
            created_by=author,
            body=(
                f"Заявка привязана к банковскому расходу #{expense.id} "
                f"(п/п №{expense.doc_no or '—'} от {expense.doc_date:%d.%m.%Y}) автоматически {reason}."
            ),
        )
    return True


def relink_unresolved_bank_doc_numbers(
    *, tenant, date_from: int | None = None, date_to: int | None = None, apply_changes: bool,
) -> list[UnresolvedDocOutcome]:
    window = timedelta(days=EXPENSE_MATCH_WINDOW_DAYS)
    amount_by_id = _amount_by_expense_id(adapter=BANK, tenant=tenant)
    claimed_ids = _claimed_expense_ids(adapter=BANK, tenant=tenant, amount_by_id=amount_by_id)

    results: list[UnresolvedDocOutcome] = []
    by_amount: dict[Decimal, list[Request]] = defaultdict(list)

    for req in _unresolved_requests(tenant=tenant, date_from=date_from, date_to=date_to):
        payed_date = payed_at_to_date(req.payed_at)
        if payed_date is None:
            results.append(UnresolvedDocOutcome(req.id, req.expense_id, req.amount, "skipped", "missing payed_at"))
            continue

        ref_id, _ = resolve_request_expense_ref(
            tenant=tenant,
            payment_type=req.payment_type,
            category=req.category,
            expense_id_raw=req.expense_id,
            expense_year=req.expense_year,
            amount=req.amount,
        )
        if ref_id is not None and ref_id not in claimed_ids:
            expense = BankExpense.objects.get(pk=ref_id)
            outcome = UnresolvedDocOutcome(
                req.id, req.expense_id, req.amount, "linked_by_doc_no", f"doc_no {req.expense_id} -> {expense.id}",
                expense_id=expense.id, expense_doc_no=expense.doc_no,
                vendor_differs=bool(req.vendor_ref_id and expense.vendor_id != req.vendor_ref_id),
            )
            if apply_changes and not _link(request=req, expense=expense, how=outcome.outcome):
                outcome = UnresolvedDocOutcome(req.id, req.expense_id, req.amount, "skipped", "concurrent update")
            else:
                claimed_ids.add(expense.id)
            results.append(outcome)
            continue

        by_amount[req.amount].append(req)

    for amount, reqs in by_amount.items():
        payed = {r.id: payed_at_to_date(r.payed_at) for r in reqs}
        expenses = list(
            BankExpense.objects.filter(
                tenant=tenant,
                debit_turnover=amount,
                doc_date__gte=min(payed.values()) - window,
                doc_date__lte=max(payed.values()) + window,
            ).exclude(id__in=claimed_ids)
        )
        pairs = []
        for req in reqs:
            for expense in expenses:
                diff = abs((payed[req.id] - expense.doc_date).days)
                if diff <= EXPENSE_MATCH_WINDOW_DAYS:
                    pairs.append((diff, req, expense))

        matches, ambiguous = _greedy_nearest_date_matches(pairs)
        matched: set[int] = set()
        for req, expense in matches:
            matched.add(req.id)
            outcome = UnresolvedDocOutcome(
                req.id, req.expense_id, req.amount, "linked_by_amount_date",
                f"typed №{req.expense_id} -> BankExpense {expense.id} (№{expense.doc_no} от {expense.doc_date})",
                expense_id=expense.id, expense_doc_no=expense.doc_no,
                vendor_differs=bool(req.vendor_ref_id and expense.vendor_id != req.vendor_ref_id),
            )
            if apply_changes and not _link(request=req, expense=expense, how=outcome.outcome):
                outcome = UnresolvedDocOutcome(req.id, req.expense_id, req.amount, "skipped", "concurrent update")
            else:
                claimed_ids.add(expense.id)
            results.append(outcome)

        for req in reqs:
            if req.id in matched:
                continue
            if req.id in ambiguous:
                results.append(UnresolvedDocOutcome(
                    req.id, req.expense_id, req.amount, "ambiguous",
                    f"{ambiguous[req.id]} BankExpense rows tie for the closest date — resolve manually",
                ))
            else:
                results.append(UnresolvedDocOutcome(
                    req.id, req.expense_id, req.amount, "no_candidate",
                    f"no unclaimed BankExpense with this amount within +/-{EXPENSE_MATCH_WINDOW_DAYS}d",
                ))

    return results
