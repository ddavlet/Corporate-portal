"""Backfill: create a CardExpense for PAYED corporate-card requests that have none
(no link, or a link to a CardExpense that no longer exists in the tenant).

Uses the same create_expense_for_request_payment path as marking a request
paid in the UI. Each request that gets an expense also gets a comment from the
"Система" user (pk=1).

Dry-run by default; pass --apply to write. The date range filters by the
request's payed_at.

Examples:
    python manage.py backfill_card_expenses --tenant=lemonaqua
    python manage.py backfill_card_expenses --tenant=3 --date-from=2026-09-01 --date-to=2026-09-30 --apply
    python manage.py backfill_card_expenses --all-tenants --date-from=2026-09-01
"""

from __future__ import annotations

from django.core.management.base import BaseCommand
from rest_framework.exceptions import ValidationError

from apps.modules.corporate_card.models import CardExpense
from apps.modules.requests.command_options import (
    add_apply_argument,
    add_date_range_arguments,
    add_tenant_arguments,
    date_to_payed_at,
    resolve_date_range,
    resolve_tenants,
    system_user,
)
from apps.modules.requests.models import Request, RequestComment
from apps.modules.requests.services import create_expense_for_request_payment


class Command(BaseCommand):
    help = "Backfill missing CardExpenses for PAYED corporate-card requests. Dry-run by default."

    def add_arguments(self, parser):
        add_tenant_arguments(parser)
        add_date_range_arguments(parser, what="requests with payed_at")
        add_apply_argument(parser)

    def handle(self, *args, **options):
        apply_changes: bool = options["apply"]
        tenants = resolve_tenants(options)
        date_from, date_to = resolve_date_range(options)

        qs = Request.objects.filter(
            tenant__in=tenants,
            payment_type=Request.PAYMENT_TYPE_CARD,
            status=Request.STATUS_PAYED,
        ).select_related("tenant", "created_by", "vendor_ref").order_by("tenant_id", "payed_at", "id")
        if date_from:
            qs = qs.filter(payed_at__gte=date_to_payed_at(date_from))
        if date_to:
            qs = qs.filter(payed_at__lte=date_to_payed_at(date_to))

        candidates = [req for req in qs if self._is_missing_card_expense(req)]
        self.stdout.write(f"Found {len(candidates)} request(s) missing a CardExpense.")

        created = 0
        failed = 0
        for req in candidates:
            self.stdout.write(
                f"  + request id={req.id} tenant={req.tenant.subdomain} amount={req.amount} payed_at={req.payed_at}"
            )
            if not apply_changes:
                continue
            try:
                create_expense_for_request_payment(request_obj=req, actor_user=req.created_by)
            except ValidationError as exc:
                self.stdout.write(self.style.ERROR(f"    skipped: {exc.detail}"))
                failed += 1
                continue
            created += 1
            self.stdout.write(f"    -> CardExpense {req.expense_ref_id}")
            comment_author = system_user()
            if comment_author is not None:
                RequestComment.objects.create(
                    request=req,
                    created_by=comment_author,
                    body=f"Автоматически создан расход по корпоративной карте {req.expense_ref_id} для этой заявки.",
                )

        self.stdout.write("")
        if apply_changes:
            self.stdout.write(self.style.SUCCESS(f"Created: {created}, skipped (errors): {failed}"))
        else:
            self.stdout.write(self.style.SUCCESS(f"Would create: {len(candidates)}"))
            self.stdout.write(self.style.WARNING("Dry run complete — no changes made. Re-run with --apply to write."))

    @staticmethod
    def _is_missing_card_expense(req: Request) -> bool:
        if req.expense_ref_id is None:
            return True
        return not CardExpense.objects.filter(tenant_id=req.tenant_id, id=req.expense_ref_id).exists()
