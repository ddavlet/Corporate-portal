"""One-time: merge duplicate vendor_directory rows for Lemonfit Aqua
(tenant_id=3) that block the vendor+amount+payed_at auto-reconciliation
(requests.bank_expense_reconciliation.reconcile_bank_expenses_by_vendor_amount_date).

Each pair below is the *same* real-world counterparty entered twice in the
vendor directory -- once picked on the request form, once resolved from the
bank statement text -- with slightly different spelling/legal suffix:

    DON-NON                          (67)  vs  "DON-NON" MCHJ              (82)
    "O`ZBEKTELEKOM" AJ               (83)  vs  "O`ZBEKTELEKOM " AJ         (135)
    MURODOV DILSHOD DOLIM O'G'LI    (623)  vs  ЯТТ MURODOV DILSHOD ...    (641)
    AUTOMATIC FIRE SYSTEM           (800)  vs  "AUTOMATIC FIRE SYSTEM" MCHJ (801)
    AROMA HOUSE                     (110)  vs  "AROMA HOUSE" MCHJ          (145)

Because reconcile_bank_expenses_by_vendor_amount_date requires an exact
vendor_id match, requests filed against the "request-side" duplicate never
auto-link to bank expenses recorded under the "bank-side" one, even when
vendor + amount + date all agree.

This command repoints Request.vendor_ref_id from the request-side duplicate
to the bank-side vendor (the version already used by BankExpense rows) for
every request in tenant 3 currently pointing at it. It never touches
BankExpense.vendor and never deletes the now-unused duplicate vendor row --
only reassigns the FK on Request.

After --apply, run the existing reconciliation command to perform the
actual linking:

    python manage.py reconcile_bank_expenses_by_vendor --tenant=3

Deliberately excludes the "Молия вазирлиги Казначилиги" (91) vs
"Mirzo-Ulug'bek Tumani DSI" (92) pair seen on request 8021: both vendors
have substantial independent history on both sides (91: 11 requests / 19
bank expenses; 92: 1 request / 9 bank expenses), so they are not a
request-vs-bank duplicate of the same counterparty -- merging them would
misattribute real, distinct transactions.

Run with --dry-run (default) first to preview, then with --apply to write.

Examples:
    python manage.py merge_lemonaqua_duplicate_vendors
    python manage.py merge_lemonaqua_duplicate_vendors --apply
"""

from __future__ import annotations

from django.core.management.base import BaseCommand

from apps.modules.requests.models import Request
from apps.modules.vendors.models import Vendor

LEMONAQUA_TENANT_ID = 3

# (tenant_id, old_vendor_id, new_vendor_id, label)
VENDOR_MERGES: list[tuple[int, int, int, str]] = [
    (LEMONAQUA_TENANT_ID, 67, 82, "DON-NON"),
    (LEMONAQUA_TENANT_ID, 83, 135, "O`ZBEKTELEKOM AJ"),
    (LEMONAQUA_TENANT_ID, 623, 641, "MURODOV DILSHOD DOLIM O'G'LI"),
    (LEMONAQUA_TENANT_ID, 800, 801, "AUTOMATIC FIRE SYSTEM"),
    (LEMONAQUA_TENANT_ID, 110, 145, "AROMA HOUSE"),
]


class Command(BaseCommand):
    help = (
        "One-time fix: repoint Request.vendor_ref_id from request-side vendor "
        "duplicates to the bank-side vendor for tenant 3 (Lemonfit Aqua)."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Write changes. Without this flag the command only prints a report.",
        )

    def handle(self, *args, **options):
        apply_changes: bool = options["apply"]

        merged_requests = 0
        skipped: list[str] = []

        for tenant_id, old_vendor_id, new_vendor_id, label in VENDOR_MERGES:
            if not Vendor.objects.filter(pk=old_vendor_id, tenant_id=tenant_id).exists():
                skipped.append(f"{label}: old vendor {old_vendor_id} not found for tenant {tenant_id}")
                continue
            if not Vendor.objects.filter(pk=new_vendor_id, tenant_id=tenant_id).exists():
                skipped.append(f"{label}: new vendor {new_vendor_id} not found for tenant {tenant_id}")
                continue

            affected = list(
                Request.objects.filter(tenant_id=tenant_id, vendor_ref_id=old_vendor_id).values_list("id", flat=True)
            )
            if not affected:
                self.stdout.write(f"  = {label}: no requests reference vendor {old_vendor_id}")
                continue

            self.stdout.write(
                f"  + {label}: vendor_ref_id {old_vendor_id} -> {new_vendor_id} "
                f"on request(s) {affected}"
            )
            if apply_changes:
                Request.objects.filter(tenant_id=tenant_id, vendor_ref_id=old_vendor_id).update(
                    vendor_ref_id=new_vendor_id
                )
            merged_requests += len(affected)

        self.stdout.write("")
        self.stdout.write(
            self.style.SUCCESS(f"{'Repointed' if apply_changes else 'Would repoint'}: {merged_requests} request(s)")
        )
        if skipped:
            self.stdout.write(self.style.WARNING(f"Skipped ({len(skipped)}):"))
            for line in skipped:
                self.stdout.write(f"  - {line}")

        if not apply_changes:
            self.stdout.write(self.style.WARNING("Dry run complete — no changes made. Re-run with --apply to write."))
