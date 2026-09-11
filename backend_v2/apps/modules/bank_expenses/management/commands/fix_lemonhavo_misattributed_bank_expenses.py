"""One-time: two bank payments were recorded against Lemonfit Havo (tenant_id=7,
subdomain "lemonhavo") because the transfer went out of that tenant's bank
account, but they actually pay for Lemonfit ONE (tenant_id=1, subdomain
"lemonfit") requests that were already filed and marked paid there:

    BankExpense 8615  (doc_no=121, 2026-08-17, 3 060 288 UZS, vendor 742
    ""MASSIVE DYNAMICS GROUP" MCHJ" -- cards for clients, contract 728 from
    2026-08-14) <-> Request 7738 (Lemonfit ONE, PAYED, expense_id="121",
    unlinked)

    BankExpense 23915 (doc_no=151, 2026-09-09, 3 060 288 UZS, same vendor,
    contract 802 from 2026-09-08) <-> Request 8011 (Lemonfit ONE, PAYED,
    expense_id="151", unlinked)

The payment itself is not reversed or cancelled -- the money did leave the
Havo bank account and BankExpense.wallet (which records which account the
payment came out of) is left untouched. Only the BankExpense's tenant is
corrected to Lemonfit ONE, so `requests.services._already_linked`'s
`BankExpense.objects.filter(tenant=request.tenant, id=ref_id)` lookup
resolves; vendor is remapped from 742 (Havo's own vendor-directory row) to
23, the equivalent "MASSIVE DYNAMICS GROUP" MCHJ row in Lemonfit ONE's
vendor directory (vendors are per-tenant, so 742 would otherwise be a
dangling cross-tenant reference).

The existing `reconcile_bank_expenses_by_vendor` backfill does not apply
here: it only considers requests with a blank `expense_id`
(`_unlinked_candidate_requests` in bank_expense_reconciliation.py), and both
of these requests already carry the bank doc_no entered by hand -- hence
this dedicated one-off does the tenant/vendor move and the request link in
a single step.

Run with --dry-run (default) first to preview, then with --apply to write.

Examples:
    python manage.py fix_lemonhavo_misattributed_bank_expenses
    python manage.py fix_lemonhavo_misattributed_bank_expenses --apply
"""

from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.modules.bank_expenses.models import BankExpense
from apps.modules.requests.models import Request
from apps.modules.vendors.models import Vendor

LEMONHAVO_TENANT_ID = 7
LEMONFIT_TENANT_ID = 1
CORRECT_VENDOR_ID = 23  # Lemonfit ONE's "MASSIVE DYNAMICS GROUP" MCHJ vendor row

# (bank_expense_id, request_id, expected_current_vendor_id, label)
MOVES: list[tuple[int, int, int, str]] = [
    (8615, 7738, 742, "contract 728 from 2026-08-14"),
    (23915, 8011, 742, "contract 802 from 2026-09-08"),
]


class Command(BaseCommand):
    help = (
        "One-time fix: move BankExpense 8615/23915 from Lemonfit Havo (tenant 7) to "
        "Lemonfit ONE (tenant 1), remap their vendor, and link them to requests 7738/8011."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Write changes. Without this flag the command only prints a report.",
        )

    def handle(self, *args, **options):
        apply_changes: bool = options["apply"]

        fixed = 0
        already_correct = 0
        skipped: list[str] = []

        if apply_changes and not Vendor.objects.filter(
            pk=CORRECT_VENDOR_ID, tenant_id=LEMONFIT_TENANT_ID
        ).exists():
            skipped.append(f"Target vendor {CORRECT_VENDOR_ID} not found for tenant {LEMONFIT_TENANT_ID}")
            self._report(fixed, already_correct, skipped, apply_changes)
            return

        for expense_id, request_id, expected_vendor_id, label in MOVES:
            expense = BankExpense.objects.filter(pk=expense_id).first()
            req = Request.objects.filter(pk=request_id).first()

            if expense is None:
                skipped.append(f"BankExpense {expense_id}: not found")
                continue
            if req is None:
                skipped.append(f"Request {request_id}: not found")
                continue

            if (
                expense.tenant_id == LEMONFIT_TENANT_ID
                and expense.vendor_id == CORRECT_VENDOR_ID
                and req.expense_ref_id == expense_id
                and req.expense_ref_target == Request.EXPENSE_REF_TARGET_BANK
            ):
                already_correct += 1
                self.stdout.write(f"  = BankExpense {expense_id} / Request {request_id}: already moved and linked")
                continue

            if expense.tenant_id != LEMONHAVO_TENANT_ID:
                skipped.append(
                    f"BankExpense {expense_id}: expected tenant_id={LEMONHAVO_TENANT_ID}, "
                    f"found {expense.tenant_id} — skipped (unexpected state, resolve manually)"
                )
                continue
            if expense.vendor_id != expected_vendor_id:
                skipped.append(
                    f"BankExpense {expense_id}: expected vendor_id={expected_vendor_id}, "
                    f"found {expense.vendor_id} — skipped (unexpected state, resolve manually)"
                )
                continue
            if req.tenant_id != LEMONFIT_TENANT_ID:
                skipped.append(
                    f"Request {request_id}: expected tenant_id={LEMONFIT_TENANT_ID}, "
                    f"found {req.tenant_id} — skipped (unexpected state, resolve manually)"
                )
                continue
            if req.expense_ref_id is not None:
                skipped.append(
                    f"Request {request_id}: already linked to expense_ref_id={req.expense_ref_id} "
                    "— skipped (unexpected state, resolve manually)"
                )
                continue

            fixed += 1
            self.stdout.write(
                f"  + BankExpense {expense_id}: tenant {expense.tenant_id} -> {LEMONFIT_TENANT_ID}, "
                f"vendor {expense.vendor_id} -> {CORRECT_VENDOR_ID}; link Request {request_id} ({label})"
            )
            if apply_changes:
                with transaction.atomic():
                    BankExpense.objects.filter(pk=expense_id).update(
                        tenant_id=LEMONFIT_TENANT_ID,
                        vendor_id=CORRECT_VENDOR_ID,
                    )
                    Request.objects.filter(pk=request_id, expense_ref_id__isnull=True).update(
                        expense_ref_id=expense_id,
                        expense_ref_target=Request.EXPENSE_REF_TARGET_BANK,
                    )

        self._report(fixed, already_correct, skipped, apply_changes)

    def _report(self, fixed, already_correct, skipped, apply_changes):
        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS(f"{'Fixed' if apply_changes else 'Would fix'}: {fixed}"))
        self.stdout.write(f"Already correct: {already_correct}")
        if skipped:
            self.stdout.write(self.style.WARNING(f"Skipped ({len(skipped)}):"))
            for line in skipped:
                self.stdout.write(f"  - {line}")

        if not apply_changes:
            self.stdout.write(self.style.WARNING("Dry run complete — no changes made. Re-run with --apply to write."))
