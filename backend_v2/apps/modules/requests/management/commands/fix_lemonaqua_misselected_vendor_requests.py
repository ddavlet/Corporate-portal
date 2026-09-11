"""One-time: correct Request.vendor_ref on two Lemonfit Aqua (tenant_id=3)
requests that were filed against "Молия вазирлиги Казначилиги" (vendor 91,
Treasury) but whose actual bank payment went to a different, unrelated
counterparty:

    Request 7936 (5 720 000 UZS, payed 2026-09-03, "Заработная плата
    август 2026") <-> BankExpense 26212 (vendor 93, the FITLINE payroll
    transit account) -- this was a salary payment, not a Treasury payment.

    Request 8021 (6 500 UZS, payed 2026-09-09, pension contribution
    prepayment) <-> BankExpense 23934 (vendor 92, "Mirzo-Ulug'bek Tumani
    DSI") -- a district social-fund payment, not Treasury.

Unlike the DON-NON/TASTIFY/etc. pairs handled by
merge_lemonaqua_duplicate_vendors, vendor 91 is not a directory duplicate
of 92 or 93 -- all three have substantial independent history (91: 11
requests / 19 bank expenses at the time of writing), so this is a
per-request "wrong vendor picked on the form" correction, not a
directory-wide merge.

This command only fixes Request.vendor_ref; it does not link the
requests to their bank expenses itself. After --apply, run the existing
reconciliation command to perform the actual linking:

    python manage.py reconcile_bank_expenses_by_vendor --tenant=3

Run with --dry-run (default) first to preview, then with --apply to write.

Examples:
    python manage.py fix_lemonaqua_misselected_vendor_requests
    python manage.py fix_lemonaqua_misselected_vendor_requests --apply
"""

from __future__ import annotations

from django.core.management.base import BaseCommand

from apps.modules.requests.models import Request
from apps.modules.vendors.models import Vendor

LEMONAQUA_TENANT_ID = 3

# (request_id, expected_current_vendor_ref_id, correct_vendor_ref_id, label)
REQUEST_FIXES: list[tuple[int, int, int, str]] = [
    (7936, 91, 93, "salary payment via FITLINE payroll transit account"),
    (8021, 91, 92, "pension contribution via Mirzo-Ulug'bek Tumani DSI"),
]


class Command(BaseCommand):
    help = (
        "One-time fix: repoint Request.vendor_ref_id on requests 7936 and 8021 "
        "(tenant 3, Lemonfit Aqua) from Treasury to their actual counterparty."
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

        for request_id, expected_vendor_id, correct_vendor_id, label in REQUEST_FIXES:
            req = Request.objects.filter(pk=request_id, tenant_id=LEMONAQUA_TENANT_ID).first()
            if req is None:
                skipped.append(f"Request {request_id}: not found for tenant {LEMONAQUA_TENANT_ID}")
                continue
            if req.vendor_ref_id == correct_vendor_id:
                already_correct += 1
                self.stdout.write(f"  = Request {request_id}: already vendor_ref_id={correct_vendor_id}")
                continue
            if req.vendor_ref_id != expected_vendor_id:
                skipped.append(
                    f"Request {request_id}: expected current vendor_ref_id={expected_vendor_id}, "
                    f"found {req.vendor_ref_id} — skipped (unexpected state, resolve manually)"
                )
                continue
            if not Vendor.objects.filter(pk=correct_vendor_id, tenant_id=LEMONAQUA_TENANT_ID).exists():
                skipped.append(f"Request {request_id}: target vendor {correct_vendor_id} not found for tenant")
                continue

            fixed += 1
            self.stdout.write(
                f"  + Request {request_id}: vendor_ref_id {req.vendor_ref_id} -> {correct_vendor_id} ({label})"
            )
            if apply_changes:
                Request.objects.filter(pk=request_id).update(vendor_ref_id=correct_vendor_id)

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS(f"{'Fixed' if apply_changes else 'Would fix'}: {fixed}"))
        self.stdout.write(f"Already correct: {already_correct}")
        if skipped:
            self.stdout.write(self.style.WARNING(f"Skipped ({len(skipped)}):"))
            for line in skipped:
                self.stdout.write(f"  - {line}")

        if not apply_changes:
            self.stdout.write(self.style.WARNING("Dry run complete — no changes made. Re-run with --apply to write."))
