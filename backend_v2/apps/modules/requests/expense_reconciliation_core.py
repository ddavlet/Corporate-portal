"""
Generic engine behind every per-type reconciliation pass (bank/cash/card).
Classifies each candidate Request as `missing` (no expense_ref_id),
`dangling` (expense_ref_id points at a row that no longer exists — e.g.
duplicate expenses were manually deleted and the request was never
updated) or `mismatch` (the row exists but its amount differs from the
request's), then tries to (re)link it to the one remaining unclaimed
expense that matches on vendor (if the adapter has one) + exact amount +
a narrow window around `payed_at`. Never guesses: 0 or >1 surviving
candidates are reported, not written.

This module has no per-type knowledge — see expense_reconciliation_adapters.py
for the BANK/CASH/CARD configs, and the reconcile_expense_links management
command for the user-facing entry point. bank_expense_reconciliation.py and
card_expense_reconciliation.py are now thin wrappers over
`find_and_reconcile` kept for n8n_integration.views's automatic post-import
hooks — see their module docstrings.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from django.db.models import Q

from apps.accounts.models import User
from apps.modules.requests.expense_reconciliation_adapters import ExpenseTypeAdapter
from apps.modules.requests.expense_vendor_name_matching import build_vendor_name_index, resolve_vendor_id_from_index
from apps.modules.requests.models import Request, RequestComment

EXPENSE_MATCH_WINDOW_DAYS = 3

_PROBLEM_REASON_RU = {
    "missing": "не было ссылки на расход",
    "dangling": "старая ссылка на расход больше не существует",
    "mismatch": "старая ссылка указывала на расход с другой суммой",
}


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


@dataclass(frozen=True)
class ReconcileOutcome:
    request_id: int
    old_expense_ref_id: int | None
    problem: str  # "missing" | "dangling" | "mismatch"
    amount: Decimal
    payed_date: date | None
    outcome: str  # "repaired" | "no_candidate" | "ambiguous" | "skipped"
    detail: str
    new_expense_ref_id: int | None = None


def _system_user() -> User | None:
    return User.objects.filter(pk=1).first()


def _amount_by_expense_id(*, adapter: ExpenseTypeAdapter, tenant) -> dict[int, Decimal]:
    return dict(adapter.model.objects.filter(tenant=tenant).values_list("id", adapter.amount_field))


def _claimed_expense_ids(*, adapter: ExpenseTypeAdapter, tenant, amount_by_id: dict[int, Decimal]) -> set[int]:
    claimed: set[int] = set()
    for ref_id, amount in Request.objects.filter(
        tenant=tenant, expense_ref_target=adapter.ref_target, expense_ref_id__isnull=False,
    ).values_list("expense_ref_id", "amount"):
        if amount_by_id.get(ref_id) == amount:
            claimed.add(ref_id)
    return claimed


def _candidate_requests(*, adapter: ExpenseTypeAdapter, tenant, date_from: int | None, date_to: int | None):
    qs = Request.objects.filter(
        tenant=tenant,
        status=Request.STATUS_PAYED,
        payment_type__in=adapter.payment_types,
        payed_at__isnull=False,
    ).filter(Q(expense_id__isnull=True) | Q(expense_id=""))
    if date_from is not None:
        qs = qs.filter(payed_at__gte=date_from)
    if date_to is not None:
        qs = qs.filter(payed_at__lte=date_to)
    return qs.order_by("payed_at", "id")


def _classify(request: Request, amount_by_id: dict[int, Decimal]) -> str | None:
    """Returns None when the request's current link is fine (nothing to do)."""
    if request.expense_ref_id is None:
        return "missing"
    resolved_amount = amount_by_id.get(request.expense_ref_id)
    if resolved_amount is None:
        return "dangling"
    if resolved_amount != request.amount:
        return "mismatch"
    return None


def _resolve_vendor_id(
    request: Request,
    adapter: ExpenseTypeAdapter,
    vendor_name_index: dict[str, list[int]],
    *,
    use_name_fallback: bool,
    apply_changes: bool,
) -> tuple[int | None, str | None]:
    """Returns (vendor_id, failure_reason). vendor_id is None + failure_reason is
    None when the adapter has no vendor concept at all (matching proceeds by
    amount+date only)."""
    if adapter.vendor_field is None:
        return None, None
    if request.vendor_ref_id is not None:
        return request.vendor_ref_id, None
    if not (use_name_fallback and adapter.supports_name_fallback):
        return None, "no vendor_ref set on the request"
    vendor_id = resolve_vendor_id_from_index(request.vendor, vendor_name_index)
    if vendor_id is None:
        return None, "no vendor_ref and no exact normalized-name match in vendor directory"
    if apply_changes:
        Request.objects.filter(pk=request.pk).update(vendor_ref_id=vendor_id)
        request.vendor_ref_id = vendor_id
    return vendor_id, None


def _greedy_nearest_date_matches(pairs):
    """
    `pairs`: iterable of (day_diff, request, expense), already restricted to
    the allowed window. Returns `(matches, ambiguous)`:

    - `matches`: list of (request, expense) pairs, each request and each
      expense used at most once.
    - `ambiguous`: dict of `request.id -> tied_candidate_count` for requests
      whose best still-available diff is shared by 2+ expenses at the
      moment they're processed — these are deliberately left unmatched
      rather than resolved by an arbitrary tiebreak (the engine never
      guesses).

    Requests are processed in order of their own best diff (ties broken by
    request id), so an unambiguous, closer-matching request claims its
    expense before a later request's remaining candidates are evaluated —
    this is what lets two simultaneous, clearly-closer-to-different-expenses
    requests both resolve correctly, while a single request with two
    genuinely equally-close candidates (nothing competing for them) is
    flagged ambiguous instead of silently picking the lower-id expense.
    """
    by_request: dict[int, list[tuple[int, object]]] = defaultdict(list)
    request_by_id: dict[int, object] = {}
    for diff, req, expense in pairs:
        by_request[req.id].append((diff, expense))
        request_by_id[req.id] = req
    for candidates in by_request.values():
        candidates.sort(key=lambda pair: (pair[0], pair[1].id))

    order = sorted(by_request.keys(), key=lambda rid: (by_request[rid][0][0], rid))

    used_expenses: set[int] = set()
    matches: list[tuple] = []
    ambiguous: dict[int, int] = {}
    for rid in order:
        remaining = [(diff, expense) for diff, expense in by_request[rid] if expense.id not in used_expenses]
        if not remaining:
            continue
        best_diff = remaining[0][0]
        tied = [expense for diff, expense in remaining if diff == best_diff]
        if len(tied) > 1:
            ambiguous[rid] = len(tied)
            continue
        expense = tied[0]
        matches.append((request_by_id[rid], expense))
        used_expenses.add(expense.id)
    return matches, ambiguous


def _leave_repair_comment(*, request: Request, adapter: ExpenseTypeAdapter, expense, problem: str, amount: Decimal):
    system_user = _system_user()
    if system_user is None:
        return
    RequestComment.objects.create(
        request_id=request.pk,
        created_by=system_user,
        body=(
            f"Ссылка на расход исправлена автоматически ({_PROBLEM_REASON_RU[problem]}): заявка привязана к "
            f"{adapter.model.__name__} #{expense.id} (сумма {amount}, дата в пределах "
            f"{EXPENSE_MATCH_WINDOW_DAYS} дн. от даты оплаты)."
        ),
    )


def find_and_reconcile(
    *,
    adapter: ExpenseTypeAdapter,
    tenant,
    date_from: int | None = None,
    date_to: int | None = None,
    apply_changes: bool,
    problems: frozenset[str] = frozenset({"missing", "dangling", "mismatch"}),
    use_name_fallback: bool = True,
) -> list[ReconcileOutcome]:
    """
    Finds every Request matching `adapter` whose expense link is missing,
    dangling, or amount-mismatched (restricted to `problems`), and tries to
    (re)link each one. Returns one ReconcileOutcome per request that had a
    problem in scope; requests whose current link is fine are not reported
    at all. Safe to re-run.
    """
    window = timedelta(days=EXPENSE_MATCH_WINDOW_DAYS)
    amount_by_id = _amount_by_expense_id(adapter=adapter, tenant=tenant)
    claimed_ids = _claimed_expense_ids(adapter=adapter, tenant=tenant, amount_by_id=amount_by_id)
    vendor_name_index: dict[str, list[int]] = {}
    if use_name_fallback and adapter.supports_name_fallback:
        vendor_name_index = build_vendor_name_index(tenant_id=tenant.id, kind=adapter.vendor_kind)

    results: list[ReconcileOutcome] = []
    groups: dict[tuple[int | None, Decimal], list[Request]] = defaultdict(list)
    meta: dict[int, dict] = {}

    for req in _candidate_requests(adapter=adapter, tenant=tenant, date_from=date_from, date_to=date_to):
        problem = _classify(req, amount_by_id)
        if problem is None or problem not in problems:
            continue

        payed_date = payed_at_to_date(req.payed_at)
        if payed_date is None:
            results.append(
                ReconcileOutcome(req.id, req.expense_ref_id, problem, req.amount, None, "skipped", "missing payed_at")
            )
            continue

        vendor_id, failure = _resolve_vendor_id(
            req, adapter, vendor_name_index, use_name_fallback=use_name_fallback, apply_changes=apply_changes,
        )
        if failure is not None:
            results.append(ReconcileOutcome(req.id, req.expense_ref_id, problem, req.amount, payed_date, "no_candidate", failure))
            continue

        meta[req.id] = {"problem": problem, "payed_date": payed_date}
        groups[(vendor_id, req.amount)].append(req)

    for (vendor_id, amount), reqs in groups.items():
        min_date = min(meta[r.id]["payed_date"] for r in reqs) - window
        max_date = max(meta[r.id]["payed_date"] for r in reqs) + window

        expense_qs = adapter.model.objects.filter(tenant=tenant, **{adapter.amount_field: amount})
        date_lookup_prefix = f"{adapter.date_field}__date" if adapter.date_is_datetime else adapter.date_field
        expense_qs = expense_qs.filter(**{f"{date_lookup_prefix}__gte": min_date, f"{date_lookup_prefix}__lte": max_date})
        if vendor_id is not None:
            expense_qs = expense_qs.filter(**{adapter.vendor_field: vendor_id})
        expenses = list(expense_qs.exclude(id__in=claimed_ids))

        pairs = []
        for req in reqs:
            req_date = meta[req.id]["payed_date"]
            for expense in expenses:
                expense_date = getattr(expense, adapter.date_field)
                if adapter.date_is_datetime:
                    expense_date = expense_date.date()
                diff = abs((req_date - expense_date).days)
                if diff <= EXPENSE_MATCH_WINDOW_DAYS:
                    pairs.append((diff, req, expense))

        matches, ambiguous = _greedy_nearest_date_matches(pairs)
        matched_ids: set[int] = set()
        for req, expense in matches:
            matched_ids.add(req.id)
            problem = meta[req.id]["problem"]
            outcome = ReconcileOutcome(
                req.id, req.expense_ref_id, problem, req.amount, meta[req.id]["payed_date"], "repaired",
                f"{adapter.model.__name__} {req.expense_ref_id} ({problem}) -> {expense.id}",
                new_expense_ref_id=expense.id,
            )
            claimed_ids.add(expense.id)
            if apply_changes:
                updated = Request.objects.filter(pk=req.pk, expense_ref_id=req.expense_ref_id).update(
                    expense_ref_id=expense.id, expense_ref_target=adapter.ref_target,
                )
                if not updated:
                    claimed_ids.discard(expense.id)
                    outcome = ReconcileOutcome(
                        req.id, req.expense_ref_id, problem, req.amount, meta[req.id]["payed_date"], "skipped",
                        "concurrent update — request changed under us",
                    )
                else:
                    _leave_repair_comment(request=req, adapter=adapter, expense=expense, problem=problem, amount=req.amount)
            results.append(outcome)

        for req in reqs:
            if req.id in matched_ids:
                continue
            problem = meta[req.id]["problem"]
            if req.id in ambiguous:
                results.append(ReconcileOutcome(
                    req.id, req.expense_ref_id, problem, req.amount, meta[req.id]["payed_date"], "ambiguous",
                    f"{ambiguous[req.id]} candidate {adapter.model.__name__} rows tie for the closest date — resolve manually",
                ))
            else:
                results.append(ReconcileOutcome(
                    req.id, req.expense_ref_id, problem, req.amount, meta[req.id]["payed_date"], "no_candidate",
                    f"no unclaimed {adapter.model.__name__} within +/-{EXPENSE_MATCH_WINDOW_DAYS}d",
                ))

    return results
