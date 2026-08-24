"""Run the amount/payed_at corporate card revenue reconciliation pass on demand.

The n8n card revenue upsert endpoints already trigger this after each import
(see n8n_integration.views), which covers the common case (statement arrives
after the request was marked paid). This command exists for the reverse
timing (request marked paid after the statement already landed) and for
backfilling historical unmatched pairs. Safe to re-run: it only fills in
requests that are still unlinked and never re-claims an already-linked
CardRevenue.

Examples:
    python manage.py reconcile_card_revenues_by_amount --tenant=1
    python manage.py reconcile_card_revenues_by_amount  # all tenants
"""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from apps.modules.requests.card_revenue_reconciliation import (
    reconcile_card_revenues_by_amount_date,
)
from apps.tenants.models import Tenant


class Command(BaseCommand):
    help = "Link unmatched Topup (corporate card) requests to card revenues by amount + payed_at window."

    def add_arguments(self, parser):
        parser.add_argument("--tenant", type=int, help="Tenant ID to process. Omit to process all tenants.")

    def handle(self, *args, **options):
        tenant_id: int | None = options.get("tenant")

        if tenant_id:
            try:
                tenants = [Tenant.objects.get(id=tenant_id)]
            except Tenant.DoesNotExist:
                raise CommandError(f"Tenant {tenant_id} not found.")
        else:
            tenants = list(Tenant.objects.all())

        total = 0
        for tenant in tenants:
            linked = reconcile_card_revenues_by_amount_date(tenant=tenant)
            if linked:
                self.stdout.write(f"  tenant={tenant.id} ({tenant.name}): linked {linked} request(s)")
            total += linked

        self.stdout.write(self.style.SUCCESS(f"Done. Linked {total} request(s) across {len(tenants)} tenant(s)."))
