"""One-time: clear two corrupted BankExpense links on Lemonfit ONE (tenant_id=1)
Transfer requests.

Both requests were left pointing (`expense_ref_id`/`expense_ref_target`) at a
BankExpense row whose `debit_turnover` does not match the request's own
`amount` -- i.e. each request is linked to someone else's bank transaction:

    Request 615 (amount=4 000 000)  -> BankExpense 27172 (debit_turnover=820 000)
    Request 670 (amount=5 263 158)  -> BankExpense 27158 (debit_turnover=980 000)

`annotate_bank_expense_compliance` / `reconcile_bank_expenses_by_vendor_amount_date`
both assume a linked BankExpense's amount matches the request's amount, so a
mismatched link like this hides the request from reconciliation instead of
surfacing it as unmatched. This command only clears the two bad refs so the
requests fall back to being reported as unmatched (and become eligible for a
correct link, manual or automatic, later) -- it does not try to find or
attach the right BankExpense itself.

Run with --dry-run (default) first to preview, then with --apply to write.

Examples:
    python manage.py unlink_bad_bank_expense_refs
    python manage.py unlink_bad_bank_expense_refs --apply
"""

from __future__ import annotations

from decimal import Decimal

from django.core.management.base import BaseCommand

from apps.modules.bank_expenses.models import BankExpense
from apps.modules.requests.models import Request

# (request_id, tenant_id, expected_current_expense_ref_id, expected_current_expense_ref_target)
BAD_REF_FIXES: list[tuple[int, int, int, str]] = [
    (615, 1, 27172, Request.EXPENSE_REF_TARGET_BANK),
    (670, 1, 27158, Request.EXPENSE_REF_TARGET_BANK),
]


class Command(BaseCommand):
    help = (
        "One-time fix: clear Request.expense_ref_id/expense_ref_target on requests "
        "615 and 670 (tenant 1), which point at a BankExpense with a different amount."
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
        already_clear = 0
        skipped: list[str] = []

        for request_id, tenant_id, expected_ref_id, expected_ref_target in BAD_REF_FIXES:
            req = Request.all_objects.filter(pk=request_id, tenant_id=tenant_id).first()
            if req is None:
                skipped.append(f"Request {request_id}: not found for tenant {tenant_id}")
                continue
            if req.expense_ref_id is None and req.expense_ref_target is None:
                already_clear += 1
                self.stdout.write(f"  = Request {request_id}: already unlinked")
                continue
            if req.expense_ref_id != expected_ref_id or req.expense_ref_target != expected_ref_target:
                skipped.append(
                    f"Request {request_id}: expected ref (expense_ref_id={expected_ref_id}, "
                    f"expense_ref_target={expected_ref_target!r}), found "
                    f"(expense_ref_id={req.expense_ref_id}, expense_ref_target={req.expense_ref_target!r}) "
                    "— skipped (unexpected state, resolve manually)"
                )
                continue

            expense = BankExpense.objects.filter(pk=expected_ref_id, tenant_id=tenant_id).first()
            if expense is not None and expense.debit_turnover == Decimal(req.amount):
                skipped.append(
                    f"Request {request_id}: linked BankExpense {expected_ref_id} amount "
                    f"({expense.debit_turnover}) now matches the request amount — link no longer "
                    "looks corrupted, skipped (resolve manually)"
                )
                continue

            fixed += 1
            self.stdout.write(
                f"  + Request {request_id}: clearing expense_ref_id={req.expense_ref_id} "
                f"expense_ref_target={req.expense_ref_target!r}"
            )
            if apply_changes:
                Request.all_objects.filter(pk=request_id, tenant_id=tenant_id).update(
                    expense_ref_id=None,
                    expense_ref_target=None,
                )

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS(f"{'Fixed' if apply_changes else 'Would fix'}: {fixed}"))
        self.stdout.write(f"Already unlinked: {already_clear}")
        if skipped:
            self.stdout.write(self.style.WARNING(f"Skipped ({len(skipped)}):"))
            for line in skipped:
                self.stdout.write(f"  - {line}")

        if not apply_changes:
            self.stdout.write(self.style.WARNING("Dry run complete — no changes made. Re-run with --apply to write."))
