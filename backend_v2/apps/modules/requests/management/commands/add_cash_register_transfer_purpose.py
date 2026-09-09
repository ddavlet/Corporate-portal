"""One-time: add the "Перевод между кассами" payment purpose (with the same-named
category) to the "Наличные" payment type config, across all tenants that already
have "Наличные" configured in their request form — mirrors what was added by hand
for lemonfit, so the cash-register-transfer button works everywhere.

Tenants without a RequestFormConfig, or without a "Наличные" payment type config
in it, are skipped — this command never creates payment-type support a tenant
hasn't opted into.

Run with no flags first to preview, then with --apply to write.

Examples:
    python manage.py add_cash_register_transfer_purpose
    python manage.py add_cash_register_transfer_purpose --apply
    python manage.py add_cash_register_transfer_purpose --apply --tenant=1
"""

from __future__ import annotations

from django.core.management.base import BaseCommand

from apps.modules.requests.models import Request, RequestFormPaymentTypeConfig, RequestPaymentPurposeConfig
from apps.tenants.models import Tenant

PAYMENT_TYPE = Request.PAYMENT_TYPE_CASH
PURPOSE_NAME = "Перевод между кассами"
PURPOSE_CATEGORY = "Перевод между кассами"


class Command(BaseCommand):
    help = (
        "Backfill: add the 'Перевод между кассами' payment purpose to the 'Наличные' "
        "payment type config for every tenant that has it configured (one-time)."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Write changes. Without this flag the command only prints a report.",
        )
        parser.add_argument(
            "--tenant",
            type=int,
            default=None,
            help="Limit to a single tenant id (default: all tenants).",
        )

    def handle(self, *args, **options):
        apply_changes: bool = options["apply"]
        tenant_id: int | None = options["tenant"]

        tenants = Tenant.objects.all().order_by("subdomain")
        if tenant_id is not None:
            tenants = tenants.filter(id=tenant_id)
        tenants = list(tenants)
        if not tenants:
            self.stdout.write(self.style.WARNING("No matching tenants."))
            return

        created = 0
        already_present = 0
        skipped: list[str] = []

        for tenant in tenants:
            form_config = getattr(tenant, "request_form_config", None)
            if form_config is None:
                skipped.append(f"[{tenant.subdomain}] no RequestFormConfig — skipped")
                continue

            pt_cfg = RequestFormPaymentTypeConfig.objects.filter(
                config=form_config,
                payment_type=PAYMENT_TYPE,
            ).first()
            if pt_cfg is None:
                skipped.append(f"[{tenant.subdomain}] no '{PAYMENT_TYPE}' payment type config — skipped")
                continue

            existing = RequestPaymentPurposeConfig.objects.filter(
                payment_type_config=pt_cfg,
                name=PURPOSE_NAME,
            ).first()
            if existing is not None:
                already_present += 1
                note = "" if existing.category == PURPOSE_CATEGORY else f" (category differs: '{existing.category}', not touched)"
                self.stdout.write(f"  = [{tenant.subdomain}] already present{note}")
                continue

            created += 1
            self.stdout.write(f"  + [{tenant.subdomain}] would create '{PURPOSE_NAME}' (category='{PURPOSE_CATEGORY}')")
            if apply_changes:
                RequestPaymentPurposeConfig.objects.create(
                    payment_type_config=pt_cfg,
                    name=PURPOSE_NAME,
                    category=PURPOSE_CATEGORY,
                    is_active=True,
                )

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS(f"{'Created' if apply_changes else 'Would create'}: {created}"))
        self.stdout.write(f"Already present: {already_present}")
        if skipped:
            self.stdout.write(self.style.WARNING(f"Skipped ({len(skipped)}):"))
            for line in skipped:
                self.stdout.write(f"  - {line}")

        if not apply_changes:
            self.stdout.write(self.style.WARNING("Dry run complete — no changes made. Re-run with --apply to write."))
