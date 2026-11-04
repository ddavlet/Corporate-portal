"""Push the bot profile (commands, description, menu button) to every tenant bot.

Runs on every deploy (deploy.sh). Always exits 0: a Telegram outage must not fail a deploy.

    python manage.py sync_telegram_bots
    python manage.py sync_telegram_bots --tenant lemonfit
"""

from __future__ import annotations

import logging

from django.core.management.base import BaseCommand

from apps.modules.telegram_approvals.bot_profile import sync_bot_profile
from apps.tenants.models import Tenant

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Sync Telegram bot profile (commands, description, menu button) for all active tenants with a bot token."

    def add_arguments(self, parser):
        parser.add_argument("--tenant", help="Only this tenant (subdomain).")

    def handle(self, *args, **options):
        qs = Tenant.objects.filter(is_active=True).order_by("pk")
        if options.get("tenant"):
            qs = qs.filter(subdomain=options["tenant"])

        ok = partial = skipped = 0
        failures: list[str] = []
        for tenant in qs.iterator():
            try:
                result = sync_bot_profile(tenant)
            except Exception:
                logger.exception("sync_bot_profile crashed tenant=%s", tenant.pk)
                partial += 1
                failures.append(f"{tenant.subdomain}: crashed (see logs)")
                continue
            if result is None:
                skipped += 1
                continue
            failed = []
            if not result.commands_ok:
                failed.append("commands")
            if not result.description_ok:
                failed.append("description")
            if result.menu_button_ok is False:
                failed.append("menu_button")
            if failed:
                partial += 1
                failures.append(f"{tenant.subdomain}: {', '.join(failed)}")
            else:
                ok += 1

        self.stdout.write(
            f"sync_telegram_bots: {ok} bots fully synced, {partial} with errors, {skipped} without token"
        )
        for line in failures:
            self.stdout.write(line)
