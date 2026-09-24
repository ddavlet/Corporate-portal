"""Backfill: create a PAYED Request for each CashExpense that has no matched request
and is not exempt by the tenant's request_not_required_rules.

The created request is backdated to the expense's expense_at date with
billing_date on the first of the expense month. Each created request gets a
comment from the "Система" user (pk=1).

Dry-run by default; pass --apply to write.

Examples:
    python manage.py backfill_cash_expense_requests --tenant=lemonfit
    python manage.py backfill_cash_expense_requests --tenant=1 --date-from=2026-09-01 --date-to=2026-09-30 --apply
    python manage.py backfill_cash_expense_requests --all-tenants --date-from=2026-09-01
"""

from __future__ import annotations

import datetime

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.modules.cashier.models import CashExpense
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
from apps.modules.requests.request_required import is_request_required_for_expense

User = get_user_model()

BACKFILL_DESCRIPTION_PREFIX = "[backfill:cash_expense]"


class Command(BaseCommand):
    help = "Backfill PAYED Requests for CashExpenses that have no matched request. Dry-run by default."

    def add_arguments(self, parser):
        add_tenant_arguments(parser)
        add_date_range_arguments(parser, what="cash expenses with expense_at")
        parser.add_argument(
            "--user-id",
            type=int,
            help='User to set as created_by/requester. Defaults to the "Система" user (pk=1).',
        )
        add_apply_argument(parser)

    def handle(self, *args, **options):
        apply_changes: bool = options["apply"]
        tenants = resolve_tenants(options)
        date_from, date_to = resolve_date_range(options)
        actor = self._actor(options.get("user_id"))
        self.stdout.write(f"Actor: user_id={actor.id}")

        total = 0
        for tenant in tenants:
            total += self._process_tenant(
                tenant=tenant, date_from=date_from, date_to=date_to, actor=actor, apply_changes=apply_changes
            )

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS(f"{'Created' if apply_changes else 'Would create'}: {total}"))
        if not apply_changes:
            self.stdout.write(self.style.WARNING("Dry run complete — no changes made. Re-run with --apply to write."))

    def _actor(self, user_id: int | None):
        actor = User.objects.filter(pk=user_id).first() if user_id else system_user()
        if actor is None:
            raise CommandError(f"User {user_id or 1} not found.")
        return actor

    def _process_tenant(self, *, tenant, date_from, date_to, actor, apply_changes: bool) -> int:
        matched_cash_ids = set(
            Request.all_objects.filter(
                tenant=tenant,
                expense_ref_target=Request.EXPENSE_REF_TARGET_CASH,
                expense_ref_id__isnull=False,
            ).values_list("expense_ref_id", flat=True)
        )
        qs = CashExpense.objects.filter(tenant=tenant).exclude(id__in=matched_cash_ids)
        if date_from:
            qs = qs.filter(expense_at__date__gte=date_from)
        if date_to:
            qs = qs.filter(expense_at__date__lte=date_to)
        unmatched = list(qs.select_related("vendor").order_by("expense_at", "id"))

        candidates = [
            e for e in unmatched
            if is_request_required_for_expense(
                tenant=tenant,
                payment_type=Request.PAYMENT_TYPE_CASH,
                expense_obj=e,
            )
        ]
        self.stdout.write(
            f"[{tenant.subdomain}] {len(unmatched)} unmatched CashExpenses, "
            f"{len(candidates)} require a request after applying rules."
        )

        for e in candidates:
            vendor_name = e.vendor.name if e.vendor else "—"
            self.stdout.write(
                f"  + CashExpense id={e.id} date={timezone.localdate(e.expense_at)} amount={e.amount} {e.currency} "
                f"title={e.title} vendor={vendor_name} ext_id={e.external_id}"
            )
            if apply_changes:
                req = self._create_request(tenant=tenant, expense=e, actor=actor)
                self.stdout.write(f"    -> created request id={req.id}")
        return len(candidates)

    def _create_request(self, *, tenant, expense, actor) -> Request:
        e = expense
        expense_date = timezone.localdate(e.expense_at)
        doc_dt = datetime.datetime(
            expense_date.year, expense_date.month, expense_date.day,
            tzinfo=timezone.get_current_timezone(),
        )
        req = Request.objects.create(
            tenant=tenant,
            created_by=actor,
            requester=actor,
            created_at=doc_dt,
            submitted_at=doc_dt,
            status=Request.STATUS_PAYED,
            payed_at=date_to_payed_at(expense_date),
            payment_type=Request.PAYMENT_TYPE_CASH,
            amount=e.amount,
            currency=e.currency or Request.CURRENCY_UZS,
            title=e.title,
            description=(
                f"{BACKFILL_DESCRIPTION_PREFIX} cash_expense_id={e.id} "
                f"external_id={e.external_id} expense_at={expense_date}"
            ),
            vendor_ref=e.vendor,
            vendor=e.vendor.name if e.vendor else "",
            billing_date=datetime.date(e.expense_year, e.expense_month, 1),
            expense_year=e.expense_year,
            expense_month=e.expense_month,
            expense_day=e.expense_day,
            expense_id=e.external_id,
            expense_ref_id=e.id,
            expense_ref_target=Request.EXPENSE_REF_TARGET_CASH,
        )
        comment_author = system_user()
        if comment_author is not None:
            RequestComment.objects.create(
                request=req,
                created_by=comment_author,
                body=(
                    f"Заявка создана автоматически по кассовому расходу {e.id} "
                    f"от {expense_date:%d.%m.%Y}, для которого не было заявки."
                ),
            )
        return req
