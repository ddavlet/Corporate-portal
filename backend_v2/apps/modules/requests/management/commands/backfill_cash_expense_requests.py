"""Backfill: create a PAYED Request for each CashExpense that has no matched request
and is not exempt by the tenant's request_not_required_rules.

The created request is backdated to the expense's expense_at date with billing_date
and billing month set to the same month as the expense.

Run with --dry-run first to preview, then without to apply.

Examples:
    python manage.py backfill_cash_expense_requests --dry-run --tenant=1
    python manage.py backfill_cash_expense_requests --tenant=1 --user-id=2
"""

from __future__ import annotations

import datetime

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.modules.cashier.models import CashExpense
from apps.modules.requests.models import Request
from apps.modules.requests.request_required import is_request_required_for_expense
from apps.tenants.models import Tenant

User = get_user_model()

BACKFILL_DESCRIPTION_PREFIX = "[backfill:cash_expense]"


def _expense_date_to_epoch(dt: datetime.datetime) -> int:
    d = dt.date()
    naive = datetime.datetime(d.year, d.month, d.day, tzinfo=datetime.timezone.utc)
    return int(naive.timestamp())


class Command(BaseCommand):
    help = "Backfill PAYED Requests for CashExpenses that have no matched request (one-time)."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="Preview without making changes.")
        parser.add_argument("--tenant", type=int, required=True, help="Tenant ID to process.")
        parser.add_argument(
            "--user-id",
            type=int,
            help="ID of the user to set as created_by/requester. Defaults to first active tenant member.",
        )

    def handle(self, *args, **options):
        dry_run: bool = options["dry_run"]
        tenant_id: int = options["tenant"]
        user_id: int | None = options.get("user_id")

        try:
            tenant = Tenant.objects.get(id=tenant_id)
        except Tenant.DoesNotExist:
            raise CommandError(f"Tenant {tenant_id} not found.")

        if user_id:
            try:
                actor = User.objects.get(id=user_id)
            except User.DoesNotExist:
                raise CommandError(f"User {user_id} not found.")
        else:
            from apps.tenants.models import TenantMembership
            membership = (
                TenantMembership.objects.filter(tenant=tenant, is_active=True)
                .select_related("user")
                .first()
            )
            if not membership:
                raise CommandError(
                    f"No active member found for tenant {tenant_id}. Pass --user-id explicitly."
                )
            actor = membership.user

        self.stdout.write(f"Actor: user_id={actor.id} ({actor.email or 'no email'})")

        matched_cash_ids = set(
            Request.objects.filter(
                tenant=tenant,
                expense_ref_target=Request.EXPENSE_REF_TARGET_CASH,
                expense_ref_id__isnull=False,
            ).values_list("expense_ref_id", flat=True)
        )

        unmatched = list(
            CashExpense.objects.filter(tenant=tenant)
            .exclude(id__in=matched_cash_ids)
            .select_related("vendor")
            .order_by("expense_at", "id")
        )

        candidates = [
            e for e in unmatched
            if is_request_required_for_expense(
                tenant=tenant,
                payment_type=Request.PAYMENT_TYPE_CASH,
                expense_obj=e,
            )
        ]

        self.stdout.write(
            f"Found {len(unmatched)} unmatched CashExpenses, "
            f"{len(candidates)} require a request after applying rules."
        )

        if not candidates:
            self.stdout.write(self.style.SUCCESS("Nothing to do."))
            return

        if dry_run:
            for e in candidates:
                vendor_name = e.vendor.name if e.vendor else "—"
                self.stdout.write(
                    f"  [dry-run] Would create PAYED request for CashExpense id={e.id} "
                    f"date={e.expense_at.date()} amount={e.amount} {e.currency} "
                    f"title={e.title} vendor={vendor_name} ext_id={e.external_id}"
                )
            self.stdout.write(self.style.WARNING("Dry run complete — no changes made."))
            return

        created = 0
        for e in candidates:
            expense_date = e.expense_at.date()
            billing_date = datetime.date(e.expense_year, e.expense_month, 1)
            doc_dt = datetime.datetime(
                expense_date.year, expense_date.month, expense_date.day,
                tzinfo=timezone.get_current_timezone(),
            )
            description = (
                f"{BACKFILL_DESCRIPTION_PREFIX} "
                f"cash_expense_id={e.id} external_id={e.external_id} "
                f"expense_at={expense_date}"
            )
            req = Request.objects.create(
                tenant=tenant,
                created_by=actor,
                requester=actor,
                created_at=doc_dt,
                submitted_at=doc_dt,
                status=Request.STATUS_PAYED,
                payed_at=_expense_date_to_epoch(e.expense_at),
                payment_type=Request.PAYMENT_TYPE_CASH,
                amount=e.amount,
                currency=e.currency or Request.CURRENCY_UZS,
                title=e.title,
                description=description,
                vendor_ref=e.vendor,
                vendor=e.vendor.name if e.vendor else "",
                billing_date=billing_date,
                expense_year=e.expense_year,
                expense_month=e.expense_month,
                expense_day=e.expense_day,
                expense_id=e.external_id,
                expense_ref_id=e.id,
                expense_ref_target=Request.EXPENSE_REF_TARGET_CASH,
            )
            self.stdout.write(
                self.style.SUCCESS(
                    f"  Created request id={req.id} -> CashExpense id={e.id} "
                    f"date={expense_date} amount={e.amount} {e.currency} title={e.title[:50]}"
                )
            )
            created += 1

        self.stdout.write(self.style.SUCCESS(f"Done. Created {created} request(s)."))
