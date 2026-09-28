"""
Cross-tenant reconciliation for a shared bank account: two tenants can have
requests for the same underlying transactions, but only one imports the
actual bank statement. For every BankExpense in `tenant` that still has no
matching request there, look for exactly one matching PAYED request in
`other_tenant`; if found, move the expense there (remapping its tenant-scoped
vendor) and link it to that request.

The expense's wallet is deliberately left untouched: it records which bank
account the money actually left, and wallet balances (wallets.services) are
reconciled against that account's statement by wallet alone.

Shared by the n8n endpoint (N8nBankExpenseReassignUnmatchedView) and the
`reassign_unmatched_bank_expenses` management command.
"""

from __future__ import annotations

from dataclasses import dataclass

from django.db import transaction

from apps.modules.bank_expenses.models import BankExpense
from apps.modules.requests.models import Request
from apps.modules.vendors.models import Vendor


@dataclass(frozen=True)
class BankExpenseReassignment:
    expense: BankExpense
    request: Request


def get_or_create_reassign_vendor(*, tenant, source_vendor, created_by):
    """
    Find-or-create the equivalent Vendor in `tenant`, keyed by account_number —
    same natural key already used for n8n vendor upsert-by-account (N8nVendorUpsertView).
    Returns None when the source has no vendor or no account_number to match on.
    """
    if source_vendor is None:
        return None
    account_number = (source_vendor.account_number or "").strip()
    if not account_number:
        return None
    existing = Vendor.objects.filter(tenant=tenant, account_number=account_number).first()
    if existing is not None:
        return existing
    return Vendor.objects.create(
        tenant=tenant,
        kind=source_vendor.kind,
        name=source_vendor.name,
        inn=source_vendor.inn,
        account_number=account_number,
        created_by=created_by,
    )


def reassign_unmatched_bank_expenses(
    *, tenant, other_tenant, created_by, dry_run: bool = False
) -> list[BankExpenseReassignment]:
    """
    Re-scans all currently-unmatched expenses on every call (not just a given
    batch) — idempotent and self-healing if a match becomes available later.
    With dry_run=True returns what would be moved without writing anything.
    """
    linked_expense_ids = set(
        Request.objects.filter(
            tenant=tenant,
            expense_ref_target=Request.EXPENSE_REF_TARGET_BANK,
            expense_ref_id__isnull=False,
        ).values_list("expense_ref_id", flat=True)
    )
    candidates = (
        BankExpense.objects.filter(tenant=tenant)
        .exclude(pk__in=linked_expense_ids)
        .select_related("vendor")
    )

    reassigned: list[BankExpenseReassignment] = []
    for expense in candidates:
        # If THIS tenant has any request claiming the same doc_no/year/amount —
        # even one not relinked yet — the expense is spoken for locally. Leave it
        # for the regular in-tenant relink instead of moving it out; when both
        # tenants claim the same transaction, ownership is ambiguous and staying
        # put is the safe answer.
        locally_claimed = Request.objects.filter(
            tenant=tenant,
            payment_type__in=(Request.PAYMENT_TYPE_TRANSFER, Request.PAYMENT_TYPE_TOPUP),
            expense_id=expense.doc_no,
            expense_year=expense.expense_year,
            amount=expense.debit_turnover,
        ).exists()
        if locally_claimed:
            continue

        # Only requests not yet linked to an expense may attract one — otherwise a
        # second expense with the same doc_no/amount could steal an already-satisfied
        # request's link and orphan the previously moved expense.
        matches = list(
            Request.objects.filter(
                tenant=other_tenant,
                payment_type__in=(Request.PAYMENT_TYPE_TRANSFER, Request.PAYMENT_TYPE_TOPUP),
                status=Request.STATUS_PAYED,
                expense_id=expense.doc_no,
                expense_year=expense.expense_year,
                amount=expense.debit_turnover,
                expense_ref_id__isnull=True,
            )[:2]
        )
        if len(matches) != 1:
            continue
        matched_request = matches[0]

        if not dry_run:
            with transaction.atomic():
                vendor = get_or_create_reassign_vendor(
                    tenant=other_tenant, source_vendor=expense.vendor, created_by=created_by
                )
                BankExpense.objects.filter(pk=expense.pk).update(
                    tenant=other_tenant, vendor=vendor,
                )
                Request.objects.filter(pk=matched_request.pk).update(
                    expense_ref_id=expense.pk,
                    expense_ref_target=Request.EXPENSE_REF_TARGET_BANK,
                )
        reassigned.append(BankExpenseReassignment(expense=expense, request=matched_request))

    return reassigned
