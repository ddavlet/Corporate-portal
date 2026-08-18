"""
Additive backfill: link Transfer/Topup Requests that have no manual doc_no to
unclaimed BankExpense rows, by vendor + exact amount + a narrow window around
the day the request was marked paid (`payed_at`).

This intentionally does NOT touch `expense_refs.resolve_request_expense_ref`
or anything in the live request save/validate path — it is a separate,
idempotent reconciliation pass meant to be run after bank expenses are
imported (see n8n_integration.views) or on demand via the
`reconcile_bank_expenses_by_vendor` management command. It never re-links a
Request or re-claims a BankExpense that already has a link, in either
direction.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal

from django.db.models import Q

from apps.modules.bank_expenses.models import BankExpense
from apps.modules.requests.models import Request

BANK_EXPENSE_VENDOR_MATCH_WINDOW_DAYS = 3


def payed_at_to_date(payed_at: int | None) -> date | None:
    """`payed_at` is an int YYYYMMDD (see approval_workflow._recalculate_request_status)."""
    if not payed_at:
        return None
    try:
        year, rem = divmod(int(payed_at), 10000)
        month, day = divmod(rem, 100)
        return date(year, month, day)
    except (ValueError, TypeError):
        return None


def _unlinked_candidate_requests(*, tenant):
    return Request.objects.filter(
        tenant=tenant,
        status=Request.STATUS_PAYED,
        payment_type__in=(Request.PAYMENT_TYPE_TRANSFER, Request.PAYMENT_TYPE_TOPUP),
        expense_ref_id__isnull=True,
        vendor_ref_id__isnull=False,
        payed_at__isnull=False,
    ).filter(Q(expense_id__isnull=True) | Q(expense_id=""))


def _claimed_bank_expense_ids(*, tenant) -> set[int]:
    return set(
        Request.objects.filter(
            tenant=tenant,
            expense_ref_target=Request.EXPENSE_REF_TARGET_BANK,
            expense_ref_id__isnull=False,
        ).values_list("expense_ref_id", flat=True)
    )


def _greedy_nearest_date_matches(pairs):
    """
    `pairs`: iterable of (day_diff, request, expense), already restricted to the
    allowed window. Returns (request, expense) pairs, closest date first, each
    request and each expense used at most once — so several payments to the
    same vendor around the same time get paired by date proximity instead of
    being dropped as ambiguous.
    """
    ordered = sorted(pairs, key=lambda p: (p[0], p[1].id, p[2].id))
    used_requests: set[int] = set()
    used_expenses: set[int] = set()
    matches = []
    for _diff, req, expense in ordered:
        if req.id in used_requests or expense.id in used_expenses:
            continue
        used_requests.add(req.id)
        used_expenses.add(expense.id)
        matches.append((req, expense))
    return matches


def reconcile_bank_expenses_by_vendor_amount_date(*, tenant) -> int:
    """
    Backfill `expense_ref_id`/`expense_ref_target` for unlinked Transfer/Topup
    requests. Returns the number of requests linked.
    """
    window = timedelta(days=BANK_EXPENSE_VENDOR_MATCH_WINDOW_DAYS)
    claimed_expense_ids = _claimed_bank_expense_ids(tenant=tenant)

    requests_by_group: dict[tuple[int, Decimal], list] = defaultdict(list)
    for req in _unlinked_candidate_requests(tenant=tenant):
        payed_date = payed_at_to_date(req.payed_at)
        if payed_date is None:
            continue
        req.payed_date = payed_date
        requests_by_group[(req.vendor_ref_id, req.amount)].append(req)

    linked = 0
    for (vendor_id, amount), reqs in requests_by_group.items():
        min_date = min(r.payed_date for r in reqs) - window
        max_date = max(r.payed_date for r in reqs) + window
        expenses = list(
            BankExpense.objects.filter(
                tenant=tenant,
                vendor_id=vendor_id,
                debit_turnover=amount,
                doc_date__gte=min_date,
                doc_date__lte=max_date,
            ).exclude(id__in=claimed_expense_ids)
        )
        if not expenses:
            continue

        pairs = []
        for req in reqs:
            for expense in expenses:
                diff = abs((req.payed_date - expense.doc_date).days)
                if diff <= BANK_EXPENSE_VENDOR_MATCH_WINDOW_DAYS:
                    pairs.append((diff, req, expense))

        for req, expense in _greedy_nearest_date_matches(pairs):
            updated = Request.objects.filter(
                pk=req.pk, tenant_id=tenant.id, expense_ref_id__isnull=True,
            ).update(
                expense_ref_id=expense.id,
                expense_ref_target=Request.EXPENSE_REF_TARGET_BANK,
            )
            if updated:
                claimed_expense_ids.add(expense.id)
                linked += 1

    return linked
