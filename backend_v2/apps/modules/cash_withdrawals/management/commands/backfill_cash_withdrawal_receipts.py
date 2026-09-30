"""Create pending receipts for PAYED withdrawal requests that never got a cash revenue.

Dry-run by default. Examples:
    python manage.py backfill_cash_withdrawal_receipts --tenant=lemonaqua --since=2026-09-01
    python manage.py backfill_cash_withdrawal_receipts --tenant=lemonaqua --since=2026-09-01 --apply [--no-send]
"""

from __future__ import annotations

import datetime as dt

from django.core.management.base import BaseCommand, CommandError

from apps.modules.cash_withdrawals.services import create_receipt_for_request, find_rule, get_active_config
from apps.modules.cashier.models import CashRevenue
from apps.modules.requests.models import Request
from apps.tenants.models import Tenant


class Command(BaseCommand):
    help = "Backfill cash-withdrawal receipts for PAYED requests without a cash revenue (dry-run by default)."

    def add_arguments(self, parser):
        parser.add_argument("--tenant", required=True, help="Tenant subdomain or id.")
        parser.add_argument("--since", required=True, help="YYYY-MM-DD, compared with Request.payed_at.")
        parser.add_argument("--apply", action="store_true")
        parser.add_argument("--no-send", action="store_true", help="With --apply: create receipts without Telegram cards.")

    def handle(self, *args, **options):
        raw_tenant = str(options["tenant"]).strip()
        tenant = (
            Tenant.objects.filter(pk=int(raw_tenant)).first() if raw_tenant.isdigit()
            else Tenant.objects.filter(subdomain=raw_tenant).first()
        )
        if tenant is None:
            raise CommandError(f"Tenant not found: {raw_tenant}")
        try:
            since = dt.date.fromisoformat(options["since"])
        except ValueError as exc:
            raise CommandError(f"Invalid --since: {exc}") from exc
        config = get_active_config(tenant)
        if config is None:
            raise CommandError("Cash-withdrawal config is missing or inactive for this tenant.")

        since_int = int(since.strftime("%Y%m%d"))
        candidates = (
            Request.objects.filter(tenant=tenant, status=Request.STATUS_PAYED, payed_at__gte=since_int)
            .filter(cash_withdrawal_receipt__isnull=True)
            .order_by("payed_at", "id")
        )
        existing_external_ids = set(
            CashRevenue.objects.filter(tenant=tenant, external_id__startswith="cash-").values_list("external_id", flat=True)
        )
        picked = []
        for req in candidates:
            rule = find_rule(config, req)
            if rule is None or f"cash-{req.pk}" in existing_external_ids:
                continue
            if (req.currency or "").strip().upper() != (rule.wallet.currency or "").strip().upper():
                self.stdout.write(self.style.WARNING(f"#{req.pk} skipped: currency {req.currency} != {rule.wallet.currency}"))
                continue
            picked.append(req)
            self.stdout.write(f"#{req.pk} payed_at={req.payed_at} amount={req.amount} {req.currency} → wallet {rule.wallet_id}")

        if not options["apply"]:
            self.stdout.write(self.style.SUCCESS(f"Dry-run: {len(picked)} request(s) would get a receipt."))
            return
        created = 0
        for req in picked:
            if create_receipt_for_request(request_obj=req, send=not options["no_send"]) is not None:
                created += 1
        self.stdout.write(self.style.SUCCESS(f"Created receipts: {created}"))
