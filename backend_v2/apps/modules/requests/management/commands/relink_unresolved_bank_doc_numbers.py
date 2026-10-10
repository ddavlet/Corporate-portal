"""
Relink PAYED Transfer/Topup заявки whose typed bank doc number (`expense_id`)
never resolved to a BankExpense (wrong/draft number, typo). See
apps.modules.requests.unresolved_bank_doc_reconciliation for the matching rules.

Dry-run by default; --apply writes, fixes `expense_id` to the real doc number
and leaves a RequestComment from "Система".

Examples:
    python manage.py relink_unresolved_bank_doc_numbers --tenant=lemonfit
    python manage.py relink_unresolved_bank_doc_numbers --tenant=1 --date-from=2026-09-01 --apply
"""

from __future__ import annotations

from django.core.management.base import BaseCommand

from apps.modules.requests.command_options import (
    add_apply_argument,
    add_date_range_arguments,
    add_tenant_arguments,
    date_to_payed_at,
    resolve_date_range,
    resolve_tenants,
)
from apps.modules.requests.unresolved_bank_doc_reconciliation import relink_unresolved_bank_doc_numbers

_LINKED = ("linked_by_doc_no", "linked_by_amount_date")


class Command(BaseCommand):
    help = (
        "Relink PAYED bank заявки whose typed doc number never resolved to a BankExpense "
        "(by doc_no, else by exact amount + date). Dry-run by default."
    )

    def add_arguments(self, parser):
        add_tenant_arguments(parser)
        add_date_range_arguments(parser, what="заявки paid")
        add_apply_argument(parser)

    def handle(self, *args, **options):
        tenants = resolve_tenants(options)
        date_from, date_to = resolve_date_range(options)
        apply_changes: bool = options["apply"]

        total_linked = 0
        for tenant in tenants:
            outcomes = relink_unresolved_bank_doc_numbers(
                tenant=tenant,
                date_from=date_to_payed_at(date_from) if date_from else None,
                date_to=date_to_payed_at(date_to) if date_to else None,
                apply_changes=apply_changes,
            )
            linked = [o for o in outcomes if o.outcome in _LINKED]
            total_linked += len(linked)
            self.stdout.write(self.style.SUCCESS(
                f"[{tenant.subdomain}] {'Linked' if apply_changes else 'Would link'}: {len(linked)}"
            ))
            for o in linked:
                vendor_note = " [vendor differs]" if o.vendor_differs else ""
                self.stdout.write(f"  + Request {o.request_id} ({o.amount}, {o.outcome}): {o.detail}{vendor_note}")
            for o in outcomes:
                if o.outcome not in _LINKED:
                    self.stdout.write(self.style.WARNING(
                        f"  - Request {o.request_id} ({o.amount}, typed №{o.typed_doc_no}) {o.outcome}: {o.detail}"
                    ))

        if not apply_changes:
            self.stdout.write(self.style.WARNING("Dry run complete — no changes made. Re-run with --apply to write."))
        else:
            self.stdout.write(self.style.SUCCESS(f"Done. Linked {total_linked} request(s)."))
