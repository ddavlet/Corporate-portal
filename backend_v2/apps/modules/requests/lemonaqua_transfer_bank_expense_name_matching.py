"""
One-time backfill: link Lemonfit Aqua (tenant_id=3) "Перечисление"/"Пополнение"
requests that predate `vendor_ref` being required — so they only carry the
free-text `vendor` field — to already-imported, still-unclaimed `BankExpense`
rows.

`reconcile_bank_expenses_by_vendor_amount_date` (bank_expense_reconciliation.py)
already does vendor + amount + payed_at matching, but it requires
`vendor_ref_id` to already be set on the request, which none of these lemonaqua
rows have. This pass resolves the missing `vendor_ref` first, by normalizing
both the request's free-text `vendor` and the tenant's `Vendor` directory names
(stripping legal-entity suffixes like ООО/MCHJ/XK/АЖ, quotes and whitespace) and
requiring an *exact* normalized match, then narrows to an exact-amount match
inside the same ±3 day window around `payed_at` used by the vendor_ref pass.

Deliberately conservative: a request is only linked (and its `vendor_ref`
backfilled) when exactly one normalized-name match and exactly one unclaimed
BankExpense survive amount+date narrowing. Typos, abbreviated legal forms, or
several same-amount candidates are left unmatched and reported for manual
follow-up rather than guessed at — see `link_lemonaqua_transfer_bank_expenses`
management command output.

When a link is written, a RequestComment is also added on the request
(authored by the pk=1 system account, which already displays as "Система" —
the same account apps.modules.n8n_integration.views._system_user() uses for
other automated actions), so anyone opening the request sees why it changed.

Run with --dry-run (default) first, then --apply to write.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from django.db.models import Q

from apps.accounts.models import User
from apps.modules.bank_expenses.models import BankExpense
from apps.modules.requests.bank_expense_reconciliation import (
    BANK_EXPENSE_VENDOR_MATCH_WINDOW_DAYS,
    payed_at_to_date,
)
from apps.modules.requests.models import Request, RequestComment
from apps.modules.vendors.models import Vendor

LEMONAQUA_TENANT_ID = 3

_LEGAL_ENTITY_TOKENS = {
    "MCHJ", "OOO", "ООО", "XK", "ХК", "QK", "AJ", "АЖ", "IP", "ИП", "ЧП", "ЯТТ",
}
_QUOTE_CHARS = str.maketrans("", "", "\"'«»`")


def normalize_vendor_name(value: str) -> str:
    """Uppercase, drop quotes and legal-entity suffix tokens, collapse whitespace."""
    value = (value or "").translate(_QUOTE_CHARS).upper()
    value = re.sub(r"[.,]", " ", value)
    tokens = [t for t in re.split(r"\s+", value) if t and t not in _LEGAL_ENTITY_TOKENS]
    return " ".join(tokens)


@dataclass(frozen=True)
class MatchOutcome:
    request_id: int
    vendor_text: str
    amount: Decimal
    payed_date: date | None
    outcome: str  # "linked" | "no_name_match" | "no_expense_match" | "ambiguous" | "skipped"
    detail: str
    bank_expense_id: int | None = None
    vendor_id: int | None = None


def _unlinked_candidate_requests(*, tenant_id: int):
    return (
        Request.objects.filter(
            tenant_id=tenant_id,
            status=Request.STATUS_PAYED,
            payment_type__in=(Request.PAYMENT_TYPE_TRANSFER, Request.PAYMENT_TYPE_TOPUP),
            expense_ref_id__isnull=True,
            vendor_ref_id__isnull=True,
            payed_at__isnull=False,
        )
        .exclude(vendor="")
        .filter(Q(expense_id__isnull=True) | Q(expense_id=""))
    )


def _system_user() -> User | None:
    return User.objects.filter(pk=1).first()


def _claimed_bank_expense_ids(*, tenant_id: int) -> set[int]:
    return set(
        Request.objects.filter(
            tenant_id=tenant_id,
            expense_ref_target=Request.EXPENSE_REF_TARGET_BANK,
            expense_ref_id__isnull=False,
        ).values_list("expense_ref_id", flat=True)
    )


def _vendor_ids_by_normalized_name(*, tenant_id: int) -> dict[str, list[int]]:
    groups: dict[str, list[int]] = defaultdict(list)
    for vendor_id, name in Vendor.objects.filter(
        tenant_id=tenant_id, kind=Vendor.KIND_TRANSFER
    ).values_list("id", "name"):
        groups[normalize_vendor_name(name)].append(vendor_id)
    return groups


def find_and_link_lemonaqua_transfer_bank_expenses(*, apply_changes: bool) -> list[MatchOutcome]:
    """
    Returns one MatchOutcome per candidate request. When `apply_changes` is
    True, "linked" outcomes are written (expense_ref_id/target + vendor_ref).
    Safe to re-run: only ever touches requests still missing both fields.
    """
    tenant_id = LEMONAQUA_TENANT_ID
    window = timedelta(days=BANK_EXPENSE_VENDOR_MATCH_WINDOW_DAYS)
    vendor_groups = _vendor_ids_by_normalized_name(tenant_id=tenant_id)
    claimed_expense_ids = _claimed_bank_expense_ids(tenant_id=tenant_id)

    results: list[MatchOutcome] = []
    for req in _unlinked_candidate_requests(tenant_id=tenant_id).order_by("payed_at", "id"):
        normalized = normalize_vendor_name(req.vendor)
        payed_date = payed_at_to_date(req.payed_at)
        if not normalized or payed_date is None:
            results.append(
                MatchOutcome(req.id, req.vendor, req.amount, payed_date, "skipped", "empty vendor text or payed_at")
            )
            continue

        vendor_ids = vendor_groups.get(normalized)
        if not vendor_ids:
            results.append(
                MatchOutcome(
                    req.id, req.vendor, req.amount, payed_date, "no_name_match",
                    "no exact normalized-name match in vendor directory",
                )
            )
            continue

        candidates = list(
            BankExpense.objects.filter(
                tenant_id=tenant_id,
                vendor_id__in=vendor_ids,
                debit_turnover=req.amount,
                doc_date__gte=payed_date - window,
                doc_date__lte=payed_date + window,
            ).exclude(id__in=claimed_expense_ids)
        )
        if not candidates:
            results.append(
                MatchOutcome(
                    req.id, req.vendor, req.amount, payed_date, "no_expense_match",
                    f"no unclaimed BankExpense with amount={req.amount} within "
                    f"+/-{BANK_EXPENSE_VENDOR_MATCH_WINDOW_DAYS}d of {payed_date}",
                )
            )
            continue
        if len(candidates) > 1:
            ids = ", ".join(str(c.id) for c in candidates)
            results.append(
                MatchOutcome(
                    req.id, req.vendor, req.amount, payed_date, "ambiguous",
                    f"{len(candidates)} candidate BankExpense rows ({ids}) — resolve manually",
                )
            )
            continue

        expense = candidates[0]
        results.append(
            MatchOutcome(
                req.id, req.vendor, req.amount, payed_date, "linked",
                f"BankExpense {expense.id} (vendor_id={expense.vendor_id})",
                bank_expense_id=expense.id, vendor_id=expense.vendor_id,
            )
        )
        # Reserve within this pass too, so two requests matching the same
        # normalized name + amount don't both claim the same expense.
        claimed_expense_ids.add(expense.id)

        if apply_changes:
            updated = Request.objects.filter(pk=req.pk, expense_ref_id__isnull=True).update(
                expense_ref_id=expense.id,
                expense_ref_target=Request.EXPENSE_REF_TARGET_BANK,
                vendor_ref_id=expense.vendor_id,
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
                            f"Заявка автоматически связана с банковской выпиской (BankExpense #{expense.id}) "
                            f"по совпадению поставщика «{req.vendor.strip()}», суммы {req.amount} и даты оплаты "
                            f"(в пределах {BANK_EXPENSE_VENDOR_MATCH_WINDOW_DAYS} дн.)."
                        ),
                    )

    return results
