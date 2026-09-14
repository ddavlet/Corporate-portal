"""One-time: link Lemonfit Aqua (tenant_id=3) request 7708 to its corporate
card transaction and correct its amount to match.

Request 7708 (130 000 UZS, "Платежная карта", payed 2026-08-13, vendor
FITLINE FITNESS CENTER GROUP, payment_purpose "Расходники АХО") has no
exact-amount match in the imported CardExpense ledger. The closest candidate
is CardExpense 126 (130 500 UZS, 2026-08-12, same vendor, UZCARD DUO) — one
day before the request was marked paid, 500 UZS off (most likely a card
processing fee folded into the actual charge).

Unlike card_expense_reconciliation (which only links on an *exact* amount
match) this is a manually reviewed, human-confirmed pairing, so this command
also corrects `Request.amount` to 130 500 to match the real transaction —
consistent with how split_lemonaqua_card_expense_requests repoints requests
onto their actual CardExpense amount.

Run with --dry-run (default) first to preview, then with --apply to write.

Examples:
    python manage.py fix_lemonaqua_request_7708_card_amount
    python manage.py fix_lemonaqua_request_7708_card_amount --apply
"""

from __future__ import annotations

from decimal import Decimal

from django.core.management.base import BaseCommand

from apps.modules.corporate_card.models import CardExpense
from apps.modules.requests.models import Request

LEMONAQUA_TENANT_ID = 3
REQUEST_ID = 7708
EXPENSE_ID = 126
ORIGINAL_AMOUNT = Decimal("130000.00")
CORRECTED_AMOUNT = Decimal("130500.00")


class Command(BaseCommand):
    help = (
        "One-time fix: link request 7708 (tenant 3, Lemonfit Aqua) to CardExpense 126 "
        "and correct its amount from 130000 to 130500."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Write changes. Without this flag the command only prints a report.",
        )

    def handle(self, *args, **options):
        apply_changes: bool = options["apply"]

        req = Request.objects.filter(pk=REQUEST_ID, tenant_id=LEMONAQUA_TENANT_ID).first()
        if req is None:
            self.stdout.write(self.style.WARNING(f"Request {REQUEST_ID}: not found for tenant {LEMONAQUA_TENANT_ID}"))
            return

        expense = CardExpense.objects.filter(pk=EXPENSE_ID, tenant_id=LEMONAQUA_TENANT_ID).first()
        if expense is None or expense.amount != CORRECTED_AMOUNT:
            found = expense.amount if expense else None
            self.stdout.write(
                self.style.WARNING(
                    f"CardExpense {EXPENSE_ID}: expected amount={CORRECTED_AMOUNT}, found {found} — skipped"
                )
            )
            return

        already_applied = (
            req.expense_ref_target == Request.EXPENSE_REF_TARGET_CARD
            and req.expense_ref_id == EXPENSE_ID
            and req.amount == CORRECTED_AMOUNT
        )
        if already_applied:
            self.stdout.write(self.style.SUCCESS(f"Request {REQUEST_ID}: already linked and corrected — no-op"))
            return

        if not (req.amount == ORIGINAL_AMOUNT and req.expense_ref_id is None):
            self.stdout.write(
                self.style.WARNING(
                    f"Request {REQUEST_ID}: expected amount={ORIGINAL_AMOUNT} and no expense_ref_id, "
                    f"found amount={req.amount} expense_ref_id={req.expense_ref_id} "
                    f"— skipped (unexpected state, resolve manually)"
                )
            )
            return

        claimed_by = (
            Request.all_objects.filter(
                tenant_id=LEMONAQUA_TENANT_ID,
                expense_ref_target=Request.EXPENSE_REF_TARGET_CARD,
                expense_ref_id=EXPENSE_ID,
            )
            .exclude(pk=REQUEST_ID)
            .first()
        )
        if claimed_by is not None:
            self.stdout.write(
                self.style.WARNING(
                    f"CardExpense {EXPENSE_ID}: already claimed by request {claimed_by.id} — skipped"
                )
            )
            return

        self.stdout.write(
            f"  + Request {REQUEST_ID}: amount {req.amount} -> {CORRECTED_AMOUNT}, "
            f"linked to CardExpense {EXPENSE_ID} (2026-08-12, 500 UZS card-fee discrepancy)"
        )
        if apply_changes:
            note = (
                f"[auto-link: сумма скорректирована с {ORIGINAL_AMOUNT} до {CORRECTED_AMOUNT} "
                f"по факту транзакции CardExpense {EXPENSE_ID} (расхождение 500 UZS, комиссия)]"
            )
            Request.objects.filter(pk=REQUEST_ID).update(
                amount=CORRECTED_AMOUNT,
                expense_ref_id=EXPENSE_ID,
                expense_ref_target=Request.EXPENSE_REF_TARGET_CARD,
                description=(f"{req.description}\n{note}" if req.description else note),
            )
            self.stdout.write(self.style.SUCCESS("Fixed: 1"))
        else:
            self.stdout.write(self.style.WARNING("Dry run complete — no changes made. Re-run with --apply to write."))
