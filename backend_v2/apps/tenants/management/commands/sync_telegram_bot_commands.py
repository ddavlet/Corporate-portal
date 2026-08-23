"""Backfill: register the wallet-balance slash-command hints (/bank_ostatki,
/cash_ostatki, /card_ostatki) in Telegram's command menu for tenants that
already have a bot token configured.

New/updated tokens are synced automatically (see TenantIntegrationConfigView.put
and TenantAdminForm.save); this command is for tenants configured before that
sync existed.

Examples:
    python manage.py sync_telegram_bot_commands
    python manage.py sync_telegram_bot_commands --tenant=1
"""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from apps.tenants.models import Tenant
from apps.tenants.views import sync_telegram_bot_commands


class Command(BaseCommand):
    help = "Register the wallet-balance command menu with Telegram for already-configured tenant bots."

    def add_arguments(self, parser):
        parser.add_argument("--tenant", type=int, help="Only sync this tenant ID. Defaults to all configured tenants.")

    def handle(self, *args, **options):
        tenant_id = options.get("tenant")
        if tenant_id is not None:
            try:
                tenants = [Tenant.objects.get(pk=tenant_id)]
            except Tenant.DoesNotExist:
                raise CommandError(f"Tenant {tenant_id} not found.")
        else:
            tenants = list(Tenant.objects.exclude(telegram_bot_token_enc="").iterator())

        if not tenants:
            self.stdout.write("No tenants with a configured Telegram bot token.")
            return

        ok_count = 0
        for tenant in tenants:
            if not tenant.get_telegram_bot_token():
                continue
            if sync_telegram_bot_commands(tenant):
                ok_count += 1
                self.stdout.write(self.style.SUCCESS(f"tenant={tenant.pk} ({tenant.subdomain}): ok"))
            else:
                self.stdout.write(self.style.WARNING(f"tenant={tenant.pk} ({tenant.subdomain}): failed — see logs"))

        self.stdout.write(self.style.SUCCESS(f"Done: {ok_count}/{len(tenants)} succeeded."))
