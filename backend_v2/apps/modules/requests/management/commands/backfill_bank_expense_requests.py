"""Backfill: create a PAYED Request for each BankExpense that has no matched request
and is not exempt by the tenant's request_not_required_rules.

The created request is backdated to the expense's doc_date so it appears on the
same calendar day as the payment. Each created request gets a comment from the
"Система" user (pk=1).

Dry-run by default; pass --apply to write.

Examples:
    python manage.py backfill_bank_expense_requests --tenant=lemonfit
    python manage.py backfill_bank_expense_requests --tenant=1 --tenant=6 --date-from=2026-09-01 --apply
    python manage.py backfill_bank_expense_requests --all-tenants --date-from=2026-09-01 --date-to=2026-09-30
    python manage.py backfill_bank_expense_requests --tenant=1 --user-id=2 --apply
"""

from __future__ import annotations

import datetime

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.modules.bank_expenses.models import BankExpense
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

BACKFILL_DESCRIPTION_PREFIX = "[backfill:bank_expense]"


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
    help = "Backfill PAYED Requests for BankExpenses that have no matched request. Dry-run by default."

    def add_arguments(self, parser):
        add_tenant_arguments(parser)
        add_date_range_arguments(parser, what="bank expenses with doc_date")
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
        matched_bank_ids = set(
            Request.all_objects.filter(
                tenant=tenant,
                expense_ref_target=Request.EXPENSE_REF_TARGET_BANK,
                expense_ref_id__isnull=False,
            ).values_list("expense_ref_id", flat=True)
        )
        qs = BankExpense.objects.filter(tenant=tenant).exclude(id__in=matched_bank_ids)
        if date_from:
            qs = qs.filter(doc_date__gte=date_from)
        if date_to:
            qs = qs.filter(doc_date__lte=date_to)
        unmatched = list(qs.select_related("vendor").order_by("doc_date", "id"))

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
            f"[{tenant.subdomain}] {len(unmatched)} unmatched BankExpenses, "
            f"{len(candidates)} require a request after applying rules."
        )

        for e in candidates:
            vendor_name = e.vendor.name if e.vendor else "—"
            self.stdout.write(
                f"  + BankExpense id={e.id} date={e.doc_date} amount={e.debit_turnover} "
                f"vendor={vendor_name} purpose={e.payment_purpose[:60]}"
            )
            if apply_changes:
                req = self._create_request(tenant=tenant, expense=e, actor=actor)
                self.stdout.write(f"    -> created request id={req.id}")
        return len(candidates)

    def _create_request(self, *, tenant, expense, actor) -> Request:
        e = expense
        doc_dt = datetime.datetime(
            e.doc_date.year, e.doc_date.month, e.doc_date.day,
            tzinfo=timezone.get_current_timezone(),
        )
        req = Request.objects.create(
            tenant=tenant,
            created_by=actor,
            requester=actor,
            created_at=doc_dt,
            submitted_at=doc_dt,
            status=Request.STATUS_PAYED,
            payed_at=date_to_payed_at(e.doc_date),
            payment_type=Request.PAYMENT_TYPE_TRANSFER,
            amount=e.debit_turnover,
            currency=Request.CURRENCY_UZS,
            title=_title_from_purpose(e.payment_purpose),
            description=f"{BACKFILL_DESCRIPTION_PREFIX} bank_expense_id={e.id} doc_no={e.doc_no} doc_date={e.doc_date}",
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
        comment_author = system_user()
        if comment_author is not None:
            RequestComment.objects.create(
                request=req,
                created_by=comment_author,
                body=(
                    f"Заявка создана автоматически по банковскому расходу {e.id} "
                    f"(п/п №{e.doc_no} от {e.doc_date:%d.%m.%Y}), для которого не было заявки."
                ),
            )
        return req
