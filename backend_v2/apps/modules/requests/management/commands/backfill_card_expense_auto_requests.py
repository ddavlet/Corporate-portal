"""Backfill automatic "Платежная карта" requests for existing CardExpenses.

Takes only cards with an enabled CardExpenseAutoRequestConfig whose "description
contains" condition matches, and expenses not yet linked to any request. For each
expense, in (expense_at, id) order, either closes an approved unpaid card request of
the same amount/currency or creates a PAYED request (same service as the n8n import
hook). Does not run amount/date reconciliation itself — run
`make reconcile-expense-links` first if needed.

Dry-run by default; pass --apply to write.

Examples:
    python manage.py backfill_card_expense_auto_requests --tenant=lemonfit
    python manage.py backfill_card_expense_auto_requests --tenant=1 --date-from=2026-09-01 --apply
    python manage.py backfill_card_expense_auto_requests --all-tenants --date-to=2026-10-31
"""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.modules.requests.card_expense_auto_requests import (
    ACTION_CLOSED,
    ACTION_CREATED,
    find_auto_request_candidates,
    plan_card_expense_auto_request,
    process_card_expense_auto_request,
)
from apps.modules.requests.card_expense_pending_request_close import format_card_expense_amount
from apps.modules.requests.command_options import (
    add_apply_argument,
    add_date_range_arguments,
    add_tenant_arguments,
    resolve_date_range,
    resolve_tenants,
    system_user,
)


def _expense_label(expense) -> str:
    return (
        f"{format_card_expense_amount(expense.amount)} {expense.currency}, "
        f"{timezone.localtime(expense.expense_at):%d.%m.%Y}"
    )


class Command(BaseCommand):
    help = (
        "Close approved card requests or create PAYED requests for CardExpenses on cards "
        "with enabled auto-request settings. Dry-run by default."
    )

    def add_arguments(self, parser):
        add_tenant_arguments(parser)
        add_date_range_arguments(parser, what="card expenses with local expense date")
        add_apply_argument(parser)

    def handle(self, *args, **options):
        apply_changes: bool = options["apply"]
        tenants = resolve_tenants(options)
        date_from, date_to = resolve_date_range(options)
        actor = system_user()
        if actor is None:
            raise CommandError('User 1 ("Система") not found.')

        totals = {ACTION_CLOSED: 0, ACTION_CREATED: 0, "skipped": 0}
        for tenant in tenants:
            candidates = find_auto_request_candidates(tenant=tenant, date_from=date_from, date_to=date_to)
            self.stdout.write(f"[{tenant.subdomain}] {len(candidates)} card expenses without a request.")
            reserved_request_ids: set[int] = set()
            for expense, config in candidates:
                if apply_changes:
                    result = process_card_expense_auto_request(expense.pk, actor=actor)
                else:
                    result = plan_card_expense_auto_request(
                        expense, config, reserved_request_ids=reserved_request_ids, actor=actor
                    )
                totals[result.action if result.action in totals else "skipped"] += 1
                self.stdout.write("  " + self._line(expense=expense, result=result, apply_changes=apply_changes))

        self.stdout.write("")
        if apply_changes:
            summary = (
                f"Closed: {totals[ACTION_CLOSED]}, Created: {totals[ACTION_CREATED]}, "
                f"Skipped: {totals['skipped']}"
            )
        else:
            summary = (
                f"Would close: {totals[ACTION_CLOSED]}, Would create: {totals[ACTION_CREATED]}, "
                f"Skipped: {totals['skipped']}"
            )
        self.stdout.write(self.style.SUCCESS(summary))
        if not apply_changes:
            self.stdout.write(self.style.WARNING("Dry run complete — no changes made. Re-run with --apply to write."))

    @staticmethod
    def _line(*, expense, result, apply_changes: bool) -> str:
        label = _expense_label(expense)
        if result.action == ACTION_CLOSED:
            verb = "Закрыта" if apply_changes else "Будет закрыта"
            return f"{verb} заявка #{result.request_id} по расходу #{expense.pk} ({label})"
        if result.action == ACTION_CREATED:
            if apply_changes:
                return f"Создана заявка #{result.request_id} по расходу #{expense.pk} ({label})"
            return f"Будет создана заявка по расходу #{expense.pk} ({label})"
        return f"Пропуск расхода #{expense.pk}: {result.reason}"
