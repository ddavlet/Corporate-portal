"""One-time: repair Request.expense_ref_id pointers to bank_expenses rows that
no longer exist. See dangling_bank_expense_ref_repair.py for the full context
and matching rules.

Run with --dry-run (default) first to preview, then with --apply to write.

Examples:
    python manage.py repair_dangling_bank_expense_refs
    python manage.py repair_dangling_bank_expense_refs --apply
"""

from __future__ import annotations

from django.core.management.base import BaseCommand

from apps.modules.requests.dangling_bank_expense_ref_repair import (
    find_and_repair_dangling_bank_expense_refs,
)


class Command(BaseCommand):
    help = (
        "One-time: repair Request.expense_ref_id pointers to bank_expenses rows "
        "that no longer exist, by re-matching on vendor_ref + amount + payed_at window."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Write changes. Without this flag the command only prints a report.",
        )

    def handle(self, *args, **options):
        apply_changes: bool = options["apply"]
        results = find_and_repair_dangling_bank_expense_refs(apply_changes=apply_changes)

        by_outcome: dict[str, list] = {}
        for r in results:
            by_outcome.setdefault(r.outcome, []).append(r)

        repaired = by_outcome.pop("repaired", [])
        for r in repaired:
            self.stdout.write(f"  + Request {r.request_id} (amount {r.amount}): {r.detail}")

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS(f"{'Repaired' if apply_changes else 'Would repair'}: {len(repaired)}"))
        for outcome, items in by_outcome.items():
            self.stdout.write(self.style.WARNING(f"{outcome} ({len(items)}):"))
            for r in items:
                self.stdout.write(f"  - Request {r.request_id} (amount {r.amount}): {r.detail}")

        if not apply_changes:
            self.stdout.write(self.style.WARNING("Dry run complete — no changes made. Re-run with --apply to write."))
