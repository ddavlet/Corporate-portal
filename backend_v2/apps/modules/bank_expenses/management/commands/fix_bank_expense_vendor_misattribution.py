"""One-time: fix vendor misattribution on two Lemonfit Aqua "charter capital
return" bank transfers dated 2026-08-19 (tenant_id=3), and the one request
that inherited the wrong vendor from it.

Both bank transfers' payment_purpose text names the same card holder --
"Ravshan Davletyarov", card {5614 6835 1180 6853} -- but BankExpense.vendor
was resolved to the intermediary bank ("ANOR BANK" AJ, vendor id=146) instead
of that person (vendor id=546, "DAVLETYAROV RAVSHAN BATIROVICH") on import.
Because the vendor + amount + payed_at auto-reconciliation
(requests.bank_expense_reconciliation.reconcile_bank_expenses_by_vendor_amount_date)
requires an exact vendor match, it never linked them to their matching
requests:

    BankExpense 9830  (doc_no=261, 84 000 000 UZS) <-> Request 7766 (84 000 000 UZS)
    BankExpense 10198 (doc_no=262, 36 000 000 UZS) <-> Request 7781 (36 000 000 UZS)

Request 7781 itself was also raised against the wrong vendor (id=761,
"Davletyarov Sardor Ravshanovich") -- confirmed against the bank text to
actually be Ravshan Davletyarov's transfer -- so its vendor_ref needs the
same correction to 546.

This command only fixes the vendor references; it does not link the requests
to the bank expenses itself. After --apply, run the existing reconciliation
command to perform the actual linking:

    python manage.py reconcile_bank_expenses_by_vendor --tenant=3

Run with --dry-run (default) first to preview, then with --apply to write.

Examples:
    python manage.py fix_bank_expense_vendor_misattribution
    python manage.py fix_bank_expense_vendor_misattribution --apply
"""

from __future__ import annotations

from django.core.management.base import BaseCommand

from apps.modules.bank_expenses.models import BankExpense
from apps.modules.requests.models import Request

CORRECT_VENDOR_ID = 546  # Vendor: DAVLETYAROV RAVSHAN BATIROVICH

# (bank_expense_id, tenant_id, expected_current_vendor_id)
BANK_EXPENSE_FIXES: list[tuple[int, int, int]] = [
    (9830, 3, 146),
    (10198, 3, 146),
]

# (request_id, tenant_id, expected_current_vendor_ref_id)
REQUEST_FIXES: list[tuple[int, int, int]] = [
    (7781, 3, 761),
]


class Command(BaseCommand):
    help = (
        "One-time fix: repoint BankExpense.vendor (9830, 10198) and "
        "Request.vendor_ref (7781) to vendor 546 so the vendor+amount+date "
        "auto-reconciliation can link them."
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

        for expense_id, tenant_id, expected_vendor_id in BANK_EXPENSE_FIXES:
            expense = BankExpense.objects.filter(pk=expense_id, tenant_id=tenant_id).first()
            if expense is None:
                skipped.append(f"BankExpense {expense_id}: not found for tenant {tenant_id}")
                continue
            if expense.vendor_id == CORRECT_VENDOR_ID:
                already_correct += 1
                self.stdout.write(f"  = BankExpense {expense_id}: already vendor_id={CORRECT_VENDOR_ID}")
                continue
            if expense.vendor_id != expected_vendor_id:
                skipped.append(
                    f"BankExpense {expense_id}: expected current vendor_id={expected_vendor_id}, "
                    f"found {expense.vendor_id} — skipped (unexpected state, resolve manually)"
                )
                continue

            fixed += 1
            self.stdout.write(f"  + BankExpense {expense_id}: vendor_id {expense.vendor_id} -> {CORRECT_VENDOR_ID}")
            if apply_changes:
                BankExpense.objects.filter(pk=expense_id).update(vendor_id=CORRECT_VENDOR_ID)

        for request_id, tenant_id, expected_vendor_ref_id in REQUEST_FIXES:
            req = Request.objects.filter(pk=request_id, tenant_id=tenant_id).first()
            if req is None:
                skipped.append(f"Request {request_id}: not found for tenant {tenant_id}")
                continue
            if req.vendor_ref_id == CORRECT_VENDOR_ID:
                already_correct += 1
                self.stdout.write(f"  = Request {request_id}: already vendor_ref_id={CORRECT_VENDOR_ID}")
                continue
            if req.vendor_ref_id != expected_vendor_ref_id:
                skipped.append(
                    f"Request {request_id}: expected current vendor_ref_id={expected_vendor_ref_id}, "
                    f"found {req.vendor_ref_id} — skipped (unexpected state, resolve manually)"
                )
                continue

            fixed += 1
            self.stdout.write(f"  + Request {request_id}: vendor_ref_id {req.vendor_ref_id} -> {CORRECT_VENDOR_ID}")
            if apply_changes:
                Request.objects.filter(pk=request_id).update(vendor_ref_id=CORRECT_VENDOR_ID)

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS(f"{'Fixed' if apply_changes else 'Would fix'}: {fixed}"))
        self.stdout.write(f"Already correct: {already_correct}")
        if skipped:
            self.stdout.write(self.style.WARNING(f"Skipped ({len(skipped)}):"))
            for line in skipped:
                self.stdout.write(f"  - {line}")

        if not apply_changes:
            self.stdout.write(self.style.WARNING("Dry run complete — no changes made. Re-run with --apply to write."))
