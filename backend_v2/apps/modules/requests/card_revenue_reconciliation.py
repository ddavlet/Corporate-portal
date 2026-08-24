"""
Additive backfill: link unclaimed "Пополнение" (corporate card top-up) Requests
to unclaimed CardRevenue rows by amount + a window around the day the request
was marked paid (`payed_at`).

Deliberately less strict than `bank_expense_reconciliation`: CardRevenue has no
vendor to match on (it's the corporate card's own incoming-funds ledger, not a
counterparty payment), so requests are grouped by amount only.

This intentionally does NOT touch `expense_refs.resolve_request_expense_ref`
or anything in the live request save/validate path — it is a separate,
idempotent reconciliation pass meant to be run after card revenues are
imported (see n8n_integration.views) or on demand via the
`reconcile_card_revenues_by_amount` management command. It never re-links a
Request or re-claims a CardRevenue that already has a link, in either
direction.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal

from django.db.models import Q

from apps.modules.corporate_card.models import CardRevenue
from apps.modules.requests.bank_expense_reconciliation import payed_at_to_date
from apps.modules.requests.models import Request

CARD_REVENUE_AMOUNT_MATCH_WINDOW_DAYS = 3


def _unlinked_candidate_requests(*, tenant):
    return Request.objects.filter(
        tenant=tenant,
        status=Request.STATUS_PAYED,
        payment_type=Request.PAYMENT_TYPE_TOPUP,
        expense_ref_id__isnull=True,
        payed_at__isnull=False,
    ).filter(Q(expense_id__isnull=True) | Q(expense_id=""))


def _claimed_card_revenue_ids(*, tenant) -> set[int]:
    return set(
        Request.objects.filter(
            tenant=tenant,
            expense_ref_target=Request.EXPENSE_REF_TARGET_CARD_REVENUE,
            expense_ref_id__isnull=False,
        ).values_list("expense_ref_id", flat=True)
    )


def _greedy_nearest_date_matches(pairs):
    """
    `pairs`: iterable of (day_diff, request, revenue), already restricted to the
    allowed window. Returns (request, revenue) pairs, closest date first, each
    request and each revenue used at most once — so several top-ups around the
    same time get paired by date proximity instead of being dropped as ambiguous.
    """
    ordered = sorted(pairs, key=lambda p: (p[0], p[1].id, p[2].id))
    used_requests: set[int] = set()
    used_revenues: set[int] = set()
    matches = []
    for _diff, req, revenue in ordered:
        if req.id in used_requests or revenue.id in used_revenues:
            continue
        used_requests.add(req.id)
        used_revenues.add(revenue.id)
        matches.append((req, revenue))
    return matches


def reconcile_card_revenues_by_amount_date(*, tenant) -> int:
    """
    Backfill `expense_ref_id`/`expense_ref_target` for unlinked Topup (corporate
    card top-up) requests. Returns the number of requests linked.
    """
    window = timedelta(days=CARD_REVENUE_AMOUNT_MATCH_WINDOW_DAYS)
    claimed_revenue_ids = _claimed_card_revenue_ids(tenant=tenant)

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
        revenues = list(
            CardRevenue.objects.filter(
                tenant=tenant,
                total_sum=amount,
                revenue_at__date__gte=min_date,
                revenue_at__date__lte=max_date,
            ).exclude(id__in=claimed_revenue_ids)
        )
        if not revenues:
            continue

        pairs = []
        for req in reqs:
            for revenue in revenues:
                diff = abs((req.payed_date - revenue.revenue_at.date()).days)
                if diff <= CARD_REVENUE_AMOUNT_MATCH_WINDOW_DAYS:
                    pairs.append((diff, req, revenue))

        for req, revenue in _greedy_nearest_date_matches(pairs):
            updated = Request.objects.filter(
                pk=req.pk, tenant_id=tenant.id, expense_ref_id__isnull=True,
            ).update(
                expense_ref_id=revenue.id,
                expense_ref_target=Request.EXPENSE_REF_TARGET_CARD_REVENUE,
            )
            if updated:
                claimed_revenue_ids.add(revenue.id)
                linked += 1

    return linked
