"""Hard-delete AI-assistant reply-chain branches and confirmations older than CHAIN_TTL_DAYS.

Owner-approved exception to the no-delete rule; touches only ChainNode and
PendingConfirmation. Invoked daily by the `backend_cron` service (backend_v2/cron/crontab).

Example:
    python manage.py purge_ai_assistant_chains
"""

from __future__ import annotations

from django.core.management.base import BaseCommand

from apps.modules.ai_assistant.purge import purge_expired_chains


class Command(BaseCommand):
    help = "Hard-delete reply-chain branches and pending confirmations older than CHAIN_TTL_DAYS."

    def handle(self, *args, **options):
        nodes, pendings = purge_expired_chains()
        self.stdout.write(
            self.style.SUCCESS(f"ai_assistant purge: deleted {nodes} chain nodes, {pendings} pending confirmations")
        )
