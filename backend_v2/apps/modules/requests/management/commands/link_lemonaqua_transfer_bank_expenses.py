"""One-time: link Lemonfit Aqua (tenant_id=3) "Перечисление"/"Пополнение"
requests that have no `vendor_ref` to already-imported bank expenses, by
normalized vendor name + exact amount + payed_at window. See
lemonaqua_transfer_bank_expense_name_matching.py for the full matching rules.

Run with --dry-run (default) first to preview, then with --apply to write.

Examples:
    python manage.py link_lemonaqua_transfer_bank_expenses
    python manage.py link_lemonaqua_transfer_bank_expenses --apply
"""

from __future__ import annotations

from django.core.management.base import BaseCommand

from apps.modules.requests.lemonaqua_transfer_bank_expense_name_matching import (
    find_and_link_lemonaqua_transfer_bank_expenses,
)


class Command(BaseCommand):
    help = (
        "One-time: link Lemonfit Aqua Transfer/Topup requests without vendor_ref to "
        "bank expenses by normalized vendor name + amount + payed_at window."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Write changes. Without this flag the command only prints a report.",
        )

    def handle(self, *args, **options):
        apply_changes: bool = options["apply"]
        results = find_and_link_lemonaqua_transfer_bank_expenses(apply_changes=apply_changes)

        by_outcome: dict[str, list] = {}
        for r in results:
            by_outcome.setdefault(r.outcome, []).append(r)

        linked = by_outcome.pop("linked", [])
        for r in linked:
            self.stdout.write(f"  + Request {r.request_id} ('{r.vendor_text.strip()}', {r.amount}) -> {r.detail}")

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS(f"{'Linked' if apply_changes else 'Would link'}: {len(linked)}"))
        for outcome, items in by_outcome.items():
            self.stdout.write(self.style.WARNING(f"{outcome} ({len(items)}):"))
            for r in items:
                self.stdout.write(f"  - Request {r.request_id} ('{r.vendor_text.strip()}', {r.amount}): {r.detail}")

        if not apply_changes:
            self.stdout.write(self.style.WARNING("Dry run complete — no changes made. Re-run with --apply to write."))
