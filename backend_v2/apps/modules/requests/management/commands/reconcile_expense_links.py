"""
On-demand reconciliation for заявки (Request) whose expense link is "red"
in the UI — missing, dangling (points at a since-deleted/reimported
expense row), or mismatched (points at a real row with a different
amount) — across bank/cash/card. Unlike the automatic n8n post-import
hooks (which only fill in missing links, immediately, for one tenant at a
time), this command:

  * requires an explicit tenant (no cross-tenant runs)
  * can filter by expense type and by payed_at date range
  * detects and repairs dangling/mismatched links too, not just missing
  * defaults to dry-run; --apply writes and leaves a RequestComment from
    the system account ("Система") on each repair

Same conservative rule as the underlying engine: a request is only
(re)linked when exactly one unclaimed candidate expense survives; 0 or >1
candidates are reported, never guessed at.

Examples:
    python manage.py reconcile_expense_links --tenant=3
    python manage.py reconcile_expense_links --tenant=3 --type=bank --type=cash --apply
    python manage.py reconcile_expense_links --tenant=3 --date-from=2026-09-01 --date-to=2026-09-09
"""

from __future__ import annotations

from datetime import datetime

from django.core.management.base import BaseCommand, CommandError

from apps.modules.requests.expense_reconciliation_adapters import ALL_ADAPTERS
from apps.modules.requests.expense_reconciliation_core import find_and_reconcile
from apps.tenants.models import Tenant


def _parse_date(value: str) -> int:
    try:
        parsed = datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        raise CommandError(f"Invalid date '{value}', expected YYYY-MM-DD.")
    return parsed.year * 10000 + parsed.month * 100 + parsed.day


class Command(BaseCommand):
    help = (
        "Find and repair Request<->expense links that are missing, dangling, or "
        "amount-mismatched, across bank/cash/card. Dry-run by default."
    )

    def add_arguments(self, parser):
        parser.add_argument("--tenant", type=int, required=True, help="Tenant ID to process (required).")
        parser.add_argument(
            "--type",
            dest="type",
            action="append",
            choices=sorted(ALL_ADAPTERS),
            help="Expense type to reconcile. Repeatable. Omit to process bank+cash+card.",
        )
        parser.add_argument("--date-from", help="Only заявки paid on/after this date (YYYY-MM-DD).")
        parser.add_argument("--date-to", help="Only заявки paid on/before this date (YYYY-MM-DD).")
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Write changes and leave a system comment. Without this flag, only a report is printed.",
        )

    def handle(self, *args, **options):
        try:
            tenant = Tenant.objects.get(id=options["tenant"])
        except Tenant.DoesNotExist:
            raise CommandError(f"Tenant {options['tenant']} not found.")

        type_keys = options["type"] or sorted(ALL_ADAPTERS)
        date_from = _parse_date(options["date_from"]) if options.get("date_from") else None
        date_to = _parse_date(options["date_to"]) if options.get("date_to") else None
        apply_changes: bool = options["apply"]

        total_repaired = 0
        for type_key in type_keys:
            adapter = ALL_ADAPTERS[type_key]
            outcomes = find_and_reconcile(
                adapter=adapter, tenant=tenant, date_from=date_from, date_to=date_to, apply_changes=apply_changes,
            )
            by_outcome: dict[str, list] = {}
            for outcome in outcomes:
                by_outcome.setdefault(outcome.outcome, []).append(outcome)

            repaired = by_outcome.pop("repaired", [])
            total_repaired += len(repaired)
            self.stdout.write(self.style.SUCCESS(
                f"[{type_key}] {'Repaired' if apply_changes else 'Would repair'}: {len(repaired)}"
            ))
            for o in repaired:
                self.stdout.write(f"  + Request {o.request_id} ({o.problem}, {o.amount}) -> {o.detail}")
            for outcome_name, items in by_outcome.items():
                self.stdout.write(self.style.WARNING(f"[{type_key}] {outcome_name} ({len(items)}):"))
                for o in items:
                    self.stdout.write(f"  - Request {o.request_id} ({o.problem}, {o.amount}): {o.detail}")

        if not apply_changes:
            self.stdout.write(self.style.WARNING("Dry run complete — no changes made. Re-run with --apply to write."))
        else:
            self.stdout.write(self.style.SUCCESS(f"Done. Repaired {total_repaired} request(s)."))
