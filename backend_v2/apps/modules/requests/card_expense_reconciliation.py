"""
Additive backfill: link unclaimed "Платежная карта" (corporate card expense)
Requests to unclaimed CardExpense rows by amount + a window around the day
the request was marked paid (`payed_at`).

Deliberately less strict than `bank_expense_reconciliation`, same as
`card_revenue_reconciliation`: CardExpense has no vendor to match on (it's a
single corporate card's own outgoing-funds ledger, not a multi-counterparty
bank statement), so requests are grouped by amount only.

This intentionally does NOT touch `expense_refs.resolve_request_expense_ref`
or anything in the live request save/validate path — it is a separate,
idempotent reconciliation pass meant to be run after card expenses are
imported (see n8n_integration.views) or on demand via the
`reconcile_card_expenses_by_amount` management command. It never re-links a
Request or re-claims a CardExpense that already has a link, in either
direction.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import timedelta
from decimal import Decimal

from django.db.models import Q

from apps.modules.corporate_card.models import CardExpense
from apps.modules.requests.bank_expense_reconciliation import payed_at_to_date
from apps.modules.requests.models import Request

CARD_EXPENSE_AMOUNT_MATCH_WINDOW_DAYS = 3


def _unlinked_candidate_requests(*, tenant):
    return Request.objects.filter(
        tenant=tenant,
        status=Request.STATUS_PAYED,
        payment_type=Request.PAYMENT_TYPE_CARD,
        expense_ref_id__isnull=True,
        payed_at__isnull=False,
    ).filter(Q(expense_id__isnull=True) | Q(expense_id=""))


def _claimed_card_expense_ids(*, tenant) -> set[int]:
    return set(
        Request.objects.filter(
            tenant=tenant,
            expense_ref_target=Request.EXPENSE_REF_TARGET_CARD,
            expense_ref_id__isnull=False,
        ).values_list("expense_ref_id", flat=True)
    )


def _greedy_nearest_date_matches(pairs):
    """
    `pairs`: iterable of (day_diff, request, expense), already restricted to the
    allowed window. Returns (request, expense) pairs, closest date first, each
    request and each expense used at most once — so several card charges of
    the same amount around the same time get paired by date proximity instead
    of being dropped as ambiguous.
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


def reconcile_card_expenses_by_amount_date(*, tenant) -> int:
    """
    Backfill `expense_ref_id`/`expense_ref_target` for unlinked "Платежная
    карта" requests. Returns the number of requests linked.
    """
    window = timedelta(days=CARD_EXPENSE_AMOUNT_MATCH_WINDOW_DAYS)
    claimed_expense_ids = _claimed_card_expense_ids(tenant=tenant)

    requests_by_amount: dict[Decimal, list] = defaultdict(list)
    for req in _unlinked_candidate_requests(tenant=tenant):
        payed_date = payed_at_to_date(req.payed_at)
        if payed_date is None:
            continue
        req.payed_date = payed_date
        requests_by_amount[req.amount].append(req)

    linked = 0
    for amount, reqs in requests_by_amount.items():
        min_date = min(r.payed_date for r in reqs) - window
        max_date = max(r.payed_date for r in reqs) + window
        expenses = list(
            CardExpense.objects.filter(
                tenant=tenant,
                amount=amount,
                expense_at__date__gte=min_date,
                expense_at__date__lte=max_date,
            ).exclude(id__in=claimed_expense_ids)
        )
        if not expenses:
            continue

        pairs = []
        for req in reqs:
            for expense in expenses:
                diff = abs((req.payed_date - expense.expense_at.date()).days)
                if diff <= CARD_EXPENSE_AMOUNT_MATCH_WINDOW_DAYS:
                    pairs.append((diff, req, expense))

        for req, expense in _greedy_nearest_date_matches(pairs):
            updated = Request.objects.filter(
                pk=req.pk, tenant_id=tenant.id, expense_ref_id__isnull=True,
            ).update(
                expense_ref_id=expense.id,
                expense_ref_target=Request.EXPENSE_REF_TARGET_CARD,
            )
            if updated:
                claimed_expense_ids.add(expense.id)
                linked += 1

    return linked
