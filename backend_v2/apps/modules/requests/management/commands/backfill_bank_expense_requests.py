"""Backfill: create a PAYED Request for each BankExpense that has no matched request
and is not exempt by the tenant's request_not_required_rules.

The created request is backdated to the expense's doc_date so it appears on the
same calendar day as the payment.

Run with --dry-run first to preview, then without to apply.

Examples:
    python manage.py backfill_bank_expense_requests --dry-run --tenant=1
    python manage.py backfill_bank_expense_requests --tenant=1 --user-id=2
"""

from __future__ import annotations

import datetime

from django.core.management.base import BaseCommand, CommandError
from django.contrib.auth import get_user_model
from django.utils import timezone

from apps.modules.bank_expenses.models import BankExpense
from apps.modules.requests.models import Request
from apps.modules.requests.request_required import is_request_required_for_expense
from apps.tenants.models import Tenant

User = get_user_model()

BACKFILL_DESCRIPTION_PREFIX = "[backfill:bank_expense]"


def _doc_date_to_epoch(doc_date: datetime.date) -> int:
    dt = datetime.datetime(doc_date.year, doc_date.month, doc_date.day, tzinfo=datetime.timezone.utc)
    return int(dt.timestamp())


def _title_from_purpose(payment_purpose: str) -> str:
    """Derive a human-readable title from the raw bank payment_purpose string."""
    # Strip leading purpose code (e.g. "00599 00599 оплата ..." → "оплата ...")
    parts = payment_purpose.strip().split(None, 2)
    if len(parts) >= 3 and parts[0].isdigit() and parts[1].isdigit():
        title = parts[2]
    elif len(parts) >= 2 and parts[0].isdigit():
        title = " ".join(parts[1:])
    else:
        title = payment_purpose
    return title[:200]


class Command(BaseCommand):
    help = "Backfill PAYED Requests for BankExpenses that have no matched request (one-time)."

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
            membership = TenantMembership.objects.filter(tenant=tenant, is_active=True).select_related("user").first()
            if not membership:
                raise CommandError(f"No active member found for tenant {tenant_id}. Pass --user-id explicitly.")
            actor = membership.user

        self.stdout.write(f"Actor: user_id={actor.id} ({actor.email or 'no email'})")

        # Collect all expense IDs already referenced by a request for this tenant
        matched_bank_ids = set(
            Request.objects.filter(
                tenant=tenant,
                expense_ref_target=Request.EXPENSE_REF_TARGET_BANK,
                expense_ref_id__isnull=False,
            ).values_list("expense_ref_id", flat=True)
        )

        unmatched = list(
            BankExpense.objects.filter(tenant=tenant)
            .exclude(id__in=matched_bank_ids)
            .select_related("vendor")
            .order_by("doc_date", "id")
        )

        # Apply "no request required" rules — only keep entries that genuinely need a request
        candidates = [
            e for e in unmatched
            if is_request_required_for_expense(
                tenant=tenant,
                payment_type=Request.PAYMENT_TYPE_TRANSFER,
                expense_obj=e,
            )
        ]

        self.stdout.write(
            f"Found {len(unmatched)} unmatched BankExpenses, "
            f"{len(candidates)} require a request after applying rules."
        )

        if not candidates:
            self.stdout.write(self.style.SUCCESS("Nothing to do."))
            return

        if dry_run:
            for e in candidates:
                vendor_name = e.vendor.name if e.vendor else "—"
                self.stdout.write(
                    f"  [dry-run] Would create PAYED request for BankExpense id={e.id} "
                    f"date={e.doc_date} amount={e.debit_turnover} vendor={vendor_name} "
                    f"purpose={e.payment_purpose[:60]}"
                )
            self.stdout.write(self.style.WARNING("Dry run complete — no changes made."))
            return

        created = 0
        for e in candidates:
            doc_dt = datetime.datetime(
                e.doc_date.year, e.doc_date.month, e.doc_date.day,
                tzinfo=timezone.get_current_timezone(),
            )
            title = _title_from_purpose(e.payment_purpose)
            description = (
                f"{BACKFILL_DESCRIPTION_PREFIX} "
                f"bank_expense_id={e.id} doc_no={e.doc_no} doc_date={e.doc_date}"
            )
            req = Request.objects.create(
                tenant=tenant,
                created_by=actor,
                requester=actor,
                created_at=doc_dt,
                submitted_at=doc_dt,
                status=Request.STATUS_PAYED,
                payed_at=_doc_date_to_epoch(e.doc_date),
                payment_type=Request.PAYMENT_TYPE_TRANSFER,
                amount=e.debit_turnover,
                currency=Request.CURRENCY_UZS,
                title=title,
                description=description,
                payment_purpose=e.payment_purpose,
                vendor_ref=e.vendor,
                vendor=e.vendor.name if e.vendor else "",
                billing_date=e.doc_date,
                expense_year=e.expense_year,
                expense_month=e.expense_month,
                expense_day=e.expense_day,
                expense_id=e.doc_no,
                expense_ref_id=e.id,
                expense_ref_target=Request.EXPENSE_REF_TARGET_BANK,
            )
            self.stdout.write(
                self.style.SUCCESS(
                    f"  Created request id={req.id} -> BankExpense id={e.id} "
                    f"date={e.doc_date} amount={e.debit_turnover} title={title[:50]}"
                )
            )
            created += 1

        self.stdout.write(self.style.SUCCESS(f"Done. Created {created} request(s)."))
