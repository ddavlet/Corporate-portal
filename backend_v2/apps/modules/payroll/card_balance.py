"""Read-only sums of salary card payouts (transit account 23106) for payroll documents.

Card rows already attached to a document always count for it (cash limit, remaining, overpaid),
whatever PayrollCardSettings says now: moving or clearing card_start_period must never let the
cash desk pay that money a second time. The setting only gates what is new: attaching rows,
the expected-card prefill and the expected-card reserve (counts_card). A document with no card
rows and no expected card behaves exactly as before.
No writes, no bank calls: payouts.py and the API read card money through this module.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from decimal import Decimal

from django.db.models import Sum

from apps.modules.payroll.models import (
    PayrollCardPayout,
    PayrollCardSettings,
    PayrollDocument,
    PayrollExpectedCard,
    PayrollLine,
    PayrollPayout,
)

ZERO = Decimal("0.00")


def card_start_period(tenant_id) -> date | None:
    return (
        PayrollCardSettings.objects.filter(tenant_id=tenant_id)
        .values_list("card_start_period", flat=True)
        .first()
    )


def counts_card(*, payout_mode: str, period_month: date | None, start: date | None) -> bool:
    return (
        start is not None
        and payout_mode == PayrollDocument.PAYOUT_MODE_PORTAL
        and period_month is not None
        and period_month >= start
    )


def card_enabled_for_document(document: PayrollDocument) -> bool:
    return counts_card(
        payout_mode=document.payout_mode,
        period_month=document.period_month,
        start=card_start_period(document.tenant_id),
    )


def card_amounts(document: PayrollDocument) -> dict[int, dict[str, Decimal]]:
    """{employee_id: {"fact": paid to the card, "expected": expected on the card}}.
    fact: every row attached to the document. expected: only while the document counts card
    payouts, only for a salary document and only for employees that still have lines in it
    (a draft changed to an advance or without the employee keeps no stale reserve)."""
    out: dict[int, dict[str, Decimal]] = {}
    facts = (
        PayrollCardPayout.objects.filter(document=document, employee__isnull=False)
        .values("employee_id")
        .annotate(s=Sum("amount"))
        .values_list("employee_id", "s")
    )
    for employee_id, total in facts:
        out.setdefault(employee_id, {"fact": ZERO, "expected": ZERO})["fact"] = total or ZERO
    if document.kind == PayrollDocument.KIND_SALARY and card_enabled_for_document(document):
        expected = PayrollExpectedCard.objects.filter(
            document=document,
            employee_id__in=PayrollLine.objects.filter(document=document, employee_fk__isnull=False).values(
                "employee_fk_id"
            ),
        ).values_list("employee_id", "amount")
        for employee_id, amount in expected:
            out.setdefault(employee_id, {"fact": ZERO, "expected": ZERO})["expected"] = amount
    return out


def card_totals_by_document(doc_ids) -> dict[int, dict[int, Decimal]]:
    """Card fact per document and employee in one query (no N+1); every attached row counts."""
    out: dict[int, dict[int, Decimal]] = defaultdict(dict)
    rows = (
        PayrollCardPayout.objects.filter(document_id__in=list(doc_ids), employee__isnull=False)
        .values("document_id", "employee_id")
        .annotate(s=Sum("amount"))
        .values_list("document_id", "employee_id", "s")
    )
    for doc_id, employee_id, total in rows:
        out[doc_id][employee_id] = total or ZERO
    return dict(out)


def document_card_summary(doc_ids) -> dict[int, dict]:
    """{doc_id: {"card_paid_total", "overpaid_total", "remaining_total",
    "employees": {employee_id: {accrued, cash, card, overpaid, remaining}}}} for documents with card
    payouts. Per employee overpaid = max(cash + card − accrued, 0), remaining = max(accrued − cash −
    card, 0); remaining_total is the sum of employee remainders plus lines without an employee, so
    an overpaid employee never hides another one's debt (same rule as payouts.payout_state)."""
    card = card_totals_by_document(doc_ids)
    if not card:
        return {}
    accrued: dict[int, dict[int, Decimal]] = defaultdict(dict)
    for doc_id, employee_id, total in (
        PayrollLine.objects.filter(document_id__in=list(card), employee_fk__isnull=False)
        .values("document_id", "employee_fk_id")
        .annotate(s=Sum("sum"))
        .values_list("document_id", "employee_fk_id", "s")
    ):
        accrued[doc_id][employee_id] = total or ZERO
    cash: dict[int, dict[int, Decimal]] = defaultdict(dict)
    for doc_id, employee_id, total in (
        PayrollPayout.objects.filter(document_id__in=list(card))
        .values("document_id", "employee_id")
        .annotate(s=Sum("amount"))
        .values_list("document_id", "employee_id", "s")
    ):
        cash[doc_id][employee_id] = total or ZERO
    unassigned = dict(
        PayrollLine.objects.filter(document_id__in=list(card), employee_fk__isnull=True)
        .values("document_id")
        .annotate(s=Sum("sum"))
        .values_list("document_id", "s")
    )
    out: dict[int, dict] = {}
    for doc_id, per_employee in card.items():
        doc_accrued = accrued.get(doc_id, {})
        doc_cash = cash.get(doc_id, {})
        employees = {}
        for employee_id in set(per_employee) | set(doc_accrued) | set(doc_cash):
            a = doc_accrued.get(employee_id, ZERO)
            c = doc_cash.get(employee_id, ZERO)
            k = per_employee.get(employee_id, ZERO)
            employees[employee_id] = {
                "accrued": a,
                "cash": c,
                "card": k,
                "overpaid": max(c + k - a, ZERO),
                "remaining": max(a - c - k, ZERO),
            }
        out[doc_id] = {
            "card_paid_total": sum(per_employee.values(), ZERO),
            "overpaid_total": sum((e["overpaid"] for e in employees.values()), ZERO),
            "remaining_total": sum((e["remaining"] for e in employees.values()), ZERO)
            + (unassigned.get(doc_id) or ZERO),
            "employees": employees,
        }
    return out


def has_card_payouts(document: PayrollDocument) -> bool:
    """Any card row attached to the document, whatever the settings say now."""
    return PayrollCardPayout.objects.filter(document=document).exists()


def auto_close_allowed(document: PayrollDocument, state: dict) -> bool:
    """A document whose balance was covered without card money closes as before; with card money
    only when the tenant switched card auto-close on (it fires n8n new-payed-request)."""
    if (state.get("card_paid_total") or ZERO) <= ZERO:
        return True
    return PayrollCardSettings.objects.filter(tenant_id=document.tenant_id, auto_close_enabled=True).exists()


def previous_month(day: date) -> date:
    """First day of the month before ``day``: salary paid in October is for September."""
    first = day.replace(day=1)
    return date(first.year - 1, 12, 1) if first.month == 1 else date(first.year, first.month - 1, 1)
